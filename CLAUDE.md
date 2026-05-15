# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`aluminum-ice/pwnagotchi` is a fork of [evilsocket/pwnagotchi](https://github.com/evilsocket/pwnagotchi) that targets Raspberry Pi Zero 2 W, 3B+, and 4 (the original Pi Zero W is unsupported — issues filed for it will be closed). The fork removes the Kali-Pi dependency, pins to Raspberry Pi OS Bullseye 32-bit Lite (2024-03-12), and compiles `nexmon`, `bettercap`, and Go from source during image build.

The application itself is a deep-RL agent (A2C with LSTM+MLP policy from `stable-baselines`) that drives `bettercap` over its REST/WebSocket API to capture WPA/WPA2 handshakes and PMKIDs, learning over time which channel-hop / association / deauth parameters work best in the surrounding RF environment.

## Build and dev commands

There is **no Python test suite** in this repo. Validation happens by building the SD-card image and booting it on a Pi.

Versioning: `pwnagotchi/_version.py` holds `__version__`. `setup.py` and the `Makefile` both read it, and the `PWN_VERSION` env var overrides the file contents (the GitHub release workflow `sed`s the file before building).

|Task                                                                          |Command                                                                                         |
|------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
|Compile all locale `.mo` files                                                |`make langs`                                                                                    |
|Build the full Raspberry Pi image (sdist → Packer → Ansible → `.img` → `.zip`)|`sudo make image` (needs `packer`, `qemu-user-static`, `binfmt-support`, root)                  |
|Clean build artifacts                                                         |`make clean`                                                                                    |
|Build the Python sdist only                                                   |`python3 setup.py sdist`                                                                        |
|Install Python pkg + system files (requires root for the system-file copy)    |`sudo python3 setup.py install`                                                                 |
|Add / update / compile a single language                                      |`scripts/language.sh {add                                                                       |
|Render the UI offline against the layout for a given display                  |`scripts/preview.py`                                                                            |
|CLI inside the image                                                          |`pwnagotchi [--manual] [--debug] [--config ...] [-U ...] [--print-config] [--clear] [--version]`|
|CLI plugin management (also via the `pwnagotchi` binary)                      |`pwnagotchi plugins {search                                                                     |

The release is produced by `.github/workflows/CreateRelease.yml` (`workflow_dispatch`-triggered). It rewrites `_version.py`, runs `make langs` + `make image`, then `pishrink`s and `7z`-compresses the image. The legacy `.travis.yml` targets `evilsocket/pwnagotchi` and is not used by this fork.

## Important environmental constraint

The Python code is **not designed to run on a developer workstation**. It freely reads `/etc/hostname`, `/proc/uptime`, `/proc/meminfo`, `/sys/class/thermal/...` and shells out to `hostname`, `halt`, `shutdown -r now`, `service bettercap restart`, `monstart`/`monstop`, `systemctl ...`. The `setup.py` `install` step also copies into `/etc/` and `/usr/bin/` (see `builder/data/`). When editing, assume the runtime is a Raspberry Pi running the built `pwnagotchi.service` under systemd with `bettercap.service` and `pwngrid-peer.service`. Do not try to `pip install -e .` and run it locally — most code paths will fail.

## Architecture (the parts that span multiple files)

### Entry point and main loop

`bin/pwnagotchi` (installed as the `pwnagotchi` script via `setup.py`) is the only entry point.

- Parses args, loads TOML config (`-C` default + `-U` user overlay), sets up logging, mounts (`fs.setup_mounts`), fonts, plugins, and the `Display`.
- Constructs a single `Agent` (`pwnagotchi/agent.py`) with the display as its `view` and a `KeyPair` identity.
- Branches into `do_auto_mode(agent)` or `do_manual_mode(agent)` (the latter just renders the last session report and idles).
- The auto-mode loop calls `agent.recon()`, groups APs by channel, hops to each channel, `associate()`s every AP, and `deauth()`s every client; then `agent.next_epoch()` advances the RL clock. `SIGUSR1` triggers a `restart(...)` to re-exec under systemd.

### `Agent` — multi-inheritance composition

`Agent(Client, Automata, AsyncAdvertiser, AsyncTrainer)` mixes four orthogonal responsibilities; changing any of them requires understanding how they share state through `self`:

|Mixin            |File                                                                               |Responsibility                                                                                                                                                                                                                               |
|-----------------|-----------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|`Client`         |`pwnagotchi/bettercap.py`                                                          |HTTP REST + WebSocket RPC client for the local `bettercap` daemon. All wifi recon, association, deauth, channel set, handshakes file config goes through `self.run('wifi.xxx ...')`.                                                         |
|`Automata`       |`pwnagotchi/automata.py`                                                           |Mood state machine: tracks `_epoch` (`ai/epoch.py`) and fires `set_bored`/`set_sad`/`set_excited`/`set_lonely`/`set_grateful`/`set_angry`. Mood transitions also broadcast plugin events.                                                    |
|`AsyncAdvertiser`|`pwnagotchi/mesh/utils.py` (+ `mesh/peer.py`, `mesh/wifi.py`)                      |Talks to the `pwngrid-peer` daemon to advertise this unit and discover nearby pwnagotchis. The `_peers` dict it owns is read by `Automata` for the “support network” / grateful logic. **Removed in Phase 1 — see Modernisation plan below.**|
|`AsyncTrainer`   |`pwnagotchi/ai/train.py` (+ `gym.py`, `featurizer.py`, `reward.py`, `parameter.py`)|Owns the `stable-baselines` A2C model and the gym env that wraps the agent. Trains in a background thread when `ai.enabled = true`.                                                                                                          |

The web UI runs inside the same process: `Agent.__init__` instantiates `Server(self, config['ui'])` from `pwnagotchi/ui/web/server.py`. Recovery state is written to `/root/.pwnagotchi-recovery`.

### Configuration

- Defaults: `pwnagotchi/defaults.toml` (deployed to `/etc/pwnagotchi/default.toml`).
- User overrides: `/etc/pwnagotchi/config.toml`, merged on top via `utils.load_config`.
- `utils.DottedTomlEncoder` is the canonical writer — used by `save_config` (plugin enable/disable, web UI edits) so output stays in dotted-key form rather than `[section]` blocks. Use it instead of vanilla `toml.dumps` when writing configs back to disk.
- The config is also accessible globally via `pwnagotchi.config` after `bin/pwnagotchi` assigns it.

### Plugin system

- `pwnagotchi/plugins/__init__.py` is event-bus + loader. Built-ins live in `pwnagotchi/plugins/default/`; users drop `.py` files under `main.custom_plugins`.
- A plugin subclasses `plugins.Plugin`. `Plugin.__init_subclass__` auto-instantiates the subclass on import and registers it in `loaded[plugin_name]`, so importing a plugin module **is** loading it.
- Callbacks are any method named `on_<event>` (full list in `pwnagotchi/plugins/default/example.py` — this is the canonical plugin template; mirror its callback signatures rather than inventing your own).
- Dispatch is via a `ThreadPoolExecutor` (size 10) with a per-`plugin::callback` lock so callbacks of the same name on the same plugin are serialized, but different plugins run in parallel. Do **not** rely on callback ordering or completion before the next bettercap event.
- `plugins.on(event, ...)` fans out; `plugins.one(name, event, ...)` targets one plugin. Both schedule on the executor.
- `plugins.toggle_plugin(name, enable)` updates `config.toml`, calls `on_unload`/`on_loaded`/`on_ready`/`on_config_changed`/`on_ui_setup` in the right order. Use it instead of mutating `loaded` directly.
- `pwnagotchi/plugins/cmd.py` implements the `pwnagotchi plugins ...` subcommands (search/list/install/enable/disable/update/upgrade); they short-circuit `main()` in `bin/pwnagotchi` before the agent is built.
- This fork ships extra plugins that aren’t in upstream: `mastodon.py`, `ntfy.py`, `ups_lite.py` (Waveshare UPS HAT), and `handshakes-m.py` (deletes empty pcaps). Enabling them is a manual edit to `/etc/pwnagotchi/config.toml`.

### UI layer

- `pwnagotchi/ui/view.py::View` owns the canvas, state, and `Voice` (i18n). `ROOT` is the module-global view used by `pwnagotchi.shutdown()` / `reboot()` for last-second redraws.
- `pwnagotchi/ui/display.py::Display(View)` selects a hardware backend from `pwnagotchi/ui/hw/` (Waveshare 1.x/2.x/2.13/2.7/2.9/3/4/inky/papirus/oledhat/lcdhat/displayhatmini/dfrobot/spotpear). The hw module returns a `layout()` dict that drives where each `View` element is drawn.
- `pwnagotchi/ui/web/server.py` exposes the Flask-based web UI; plugins can register routes via `on_webhook(path, request)` (CSRF tokens required for POSTs — see `example.py`).
- Adding a new display means writing a hw module that exposes `name()`, `layout()`, `initialize()`, `render(canvas)`, `clear()`.

### i18n

- Voice strings live in `pwnagotchi/voice.py`. `scripts/language.sh update <lang>` regenerates the `.pot` and merges into `voice.po`. `make langs` compiles every `.po` into `.mo`.
- When adding a user-facing string, wrap it in the same `gettext` pattern used in `voice.py` and re-run `update` for the languages you can.

### AI

- A2C agent built on `stable-baselines==2.10.2` / `tensorflow==1.13.1` (pinned old versions — do not casually bump). Model is persisted at `ai.path` (default `/root/brain.nn`).
- `ai/featurizer.py` builds the observation vector from epoch stats; `ai/reward.py` computes reward; `ai/parameter.py` describes the tunable knobs the agent can learn (these become the action space in `ai/gym.py`).
- `AsyncTrainer.start_ai()` is fired by `Agent` after enough epochs have elapsed; training emits `on_ai_*` plugin events.

## Repo conventions

- Python indentation is 4 spaces; everything else is 2 spaces (`.editorconfig`). Makefile uses tabs.
- Contributions should be `git commit -s` signed-off (DCO); see `CONTRIBUTING.md`. Don’t mix refactors with fixes in the same PR.
- The default development branch in this environment is `claude/add-claude-documentation-plLHT` — push there, not to `master`.
- Avoid editing `requirements.txt` directly; it’s `pip-compile`d from `requirements.in`. The pins are intentionally old to match what builds on `armhf` via piwheels.
- Don’t add unit tests expecting CI to run them — there is no Python test job. The only CI is the release-image workflow.

-----

## Modernisation plan

This repo is undergoing a structured three-phase modernisation. Each phase has a defined scope, an ordered task list, and an acceptance checklist. **Do not make changes outside the current phase’s scope.** If you find something that needs fixing that belongs to a later phase, add a `# TODO(phase-N): <description>` comment and move on.

Commit after each numbered step, not at the end of a session. One step = one commit.

The full design document (rationale, risk register, dependency tables) is in `docs/DESIGN.md`.

-----

### Phase 1 — pwngrid & peer-advertising removal (target: v1.9.0)

**Scope:** Remove all dependency on the `pwngrid` binary, the `api.pwnagotchi.ai` cloud service, and the local dot11 peer-advertising layer (`pwnagotchi/mesh/`). No version upgrades, no new dependencies, no other changes.

**Context:** `api.pwnagotchi.ai` is defunct and `evilsocket/pwngrid` is unmaintained. Port 8666 (pwngrid-peer) is not functional in the current image. Peer advertising via dot11 custom IEs is entangled with the pwngrid-peer sidecar and cannot be cleanly retained without it.

**Breaking change:** `on_peer_detected` is removed from the plugin callback API. Document in CHANGELOG.md.

**`/etc/pwnagotchi/` — critical:** This directory is the primary application config directory (`config.toml`, `conf.d/`, log path). It is **not** a pwngrid-specific path. Keep the Ansible task that creates it. Only remove the `pwngrid -generate -keys /etc/pwnagotchi` keypair task.

#### Files to delete outright

- `pwnagotchi/grid.py`
- `pwnagotchi/identity.py`
- `pwnagotchi/mesh/` (entire directory)
- `pwnagotchi/plugins/default/grid.py`
- `builder/data/etc/systemd/system/pwngrid-peer.service`

#### Call-site cleanup (after deletions)

- `pwnagotchi/agent.py` — remove `import pwnagotchi.grid`, `import pwnagotchi.identity`, all `grid.is_connected()` calls and the conditional blocks they gate, all `grid.call()` invocations, the `self._peers` counter and its update logic, `AsyncAdvertiser` from the inheritance list
- `pwnagotchi/automata.py` — remove `on_peer_detected` dispatch and any peer-related state
- `pwnagotchi/ui/view.py` — remove `on_unread_messages()` method and the inbox counter UI element
- `pwnagotchi/defaults.toml` — remove the `[main.plugins.grid]` config block
- `requirements.in` — comment out `pycryptodome` with a note; do not re-run pip-compile yet (deferred to Phase 2)
- `builder/pwnagotchi.yml` — remove: pwngrid binary download task, `/usr/bin/` install task, `pwngrid -generate -keys /etc/pwnagotchi` keypair task, pwngrid-peer.service enable task. **Keep** the `/etc/pwnagotchi/` directory creation task.

#### Tests to write (`tests/test_phase1_removal.py`)

Write these using stdlib `unittest` only (pytest is not installed yet). All six must pass before tagging beta.

1. `test_grid_module_not_importable` — `import pwnagotchi.grid` raises `ModuleNotFoundError`
1. `test_identity_module_not_importable` — `import pwnagotchi.identity` raises `ModuleNotFoundError`
1. `test_mesh_module_not_importable` — `import pwnagotchi.mesh` raises `ModuleNotFoundError`
1. `test_pycryptodome_not_imported_by_core` — import `pwnagotchi`; assert `'Crypto'` not in `sys.modules`
1. `test_on_peer_detected_not_in_plugin_callbacks` — instantiate the plugin loader; assert `'on_peer_detected'` is not in its known callback registry
1. `test_agent_imports_cleanly` — import `pwnagotchi.agent` with `pwnagotchi.grid` absent; assert no `ImportError` or `AttributeError`

#### Acceptance checklist

- [ ] `pwnagotchi/grid.py` deleted; no `import.*grid` in any remaining `.py` file (`grep -r "import.*grid" pwnagotchi/`)
- [ ] `pwnagotchi/identity.py` deleted; no `import.*identity` in any remaining `.py` file
- [ ] `pwnagotchi/mesh/` directory deleted
- [ ] `pwnagotchi/plugins/default/grid.py` deleted
- [ ] `pwngrid-peer.service` deleted
- [ ] `agent.py`: no `grid.*` or `identity.*` references; `AsyncAdvertiser` removed from class definition
- [ ] `automata.py`: no `on_peer_detected` dispatch
- [ ] `ui/view.py`: no `on_unread_messages`; inbox counter UI element removed
- [ ] `defaults.toml`: no `main.plugins.grid` block (`grep -r "plugins.grid"` returns nothing)
- [ ] `builder/pwnagotchi.yml`: no pwngrid tasks (`grep -i "pwngrid" builder/` returns nothing); `/etc/pwnagotchi/` mkdir task still present
- [ ] `pycryptodome` commented out in `requirements.in`
- [ ] All 6 tests in `tests/test_phase1_removal.py` pass (`python -m pytest tests/test_phase1_removal.py -v`)
- [ ] Image boots; `journalctl -u pwnagotchi` shows no errors referencing pwngrid, grid, or identity
- [ ] Display renders without inbox counter; face renders normally
- [ ] bettercap starts; handshake capture works in AUTO mode

-----

### Phase 2 — 32-bit stabilisation (target: v2.0.0)

**Scope:** Upgrade base image to Raspberry Pi OS Bookworm 32-bit, Python 3.11, Flask 3.x, and pyproject.toml. Add test infrastructure. Migrate USB networking to NetworkManager. No AI stack changes.

**Entry condition:** Phase 1 acceptance checklist fully green.

#### Sub-tasks (do in order, one commit per step)

**A — Base image**

- Update builder base image URL to Raspberry Pi OS Bookworm Lite 32-bit (armhf)
- Verify ARCHFLAG=armv7l and nexmon source build still work

**B — pyproject.toml**

- Replace `setup.py` with `pyproject.toml` using `hatchling` build backend
- Preserve all entry points and data file installs (map each `install_file()` call to `[tool.hatch.build.targets.wheel.shared-data]`)
- Add `requires-python = ">=3.9"`; optional dep groups `[ai]` and `[display]`

**C — Flask 3.x upgrade**

- `flask` → `>=3.0,<4`; `werkzeug` → `>=3.0`; `jinja2` → `>=3.1`; `flask-cors` → `>=4.0`; `flask-wtf` → `>=1.2`
- Remove `MarkupSafe < 2.1.0` cap and fix the misleading `itsdangerous` comment in `requirements.txt`
- Audit `webcfg` plugin for removed Flask 3.x APIs: `flask.escape()` → `markupsafe.escape()`; `flask.Markup` → `markupsafe.Markup`
- Audit CSRF token usage in any plugin that POSTs

**D — Python 3.11 compat**

- Replace `datetime.utcnow()` → `datetime.now(timezone.utc)` throughout
- Replace `pkg_resources` path usage → `importlib.resources`
- Fix any `collections` imports that should be `collections.abc`
- Run `python -m py_compile` on every `.py` file under `pwnagotchi/` to catch syntax issues

**E — pip-compile**

- Re-run `pip-compile --resolver=backtracking --strip-extras --prefer-binary` against Python 3.11 in a Bookworm 32-bit environment (use QEMU or a Bookworm Docker image — do not run on a dev workstation)
- `pycryptodome` must be absent from the output
- Commit the new `requirements.txt`

**F — AI guard hardening**

- In `pwnagotchi/ai/__init__.py`, wrap the TF import in try/except; set module-level `AI_AVAILABLE = False` on failure; log a `WARNING` with the specific import error
- In `agent.py`, check `AI_AVAILABLE` before entering AI-driven mode; fall back to `MANU` cleanly
- Add a small UI indicator (face element or log line) so the operator can see AI is inactive

**G — Test infrastructure**

- Add `pytest`, `pytest-asyncio`, `responses` as dev dependencies in `pyproject.toml` optional group `[dev]`
- Add `ruff` config (`ruff.toml`) and `.pre-commit-config.yaml`; apply formatting as a **separate cosmetic commit**
- Write the four test modules below

**H — USB networking**

- Replace `/etc/network/interfaces.d/usb0` with a NetworkManager `.nmconnection` profile for the USB gadget interface
- Remove the `ifupdown` dependency from the Ansible playbook if no other interface uses it

#### Tests to write (Phase 2)

**`tests/test_config.py`**

1. `test_load_valid_toml` — load a minimal valid `config.toml`; assert `main.name` is present
1. `test_defaults_are_applied` — load empty user config; assert values from `defaults.toml` appear in merged result
1. `test_user_values_override_defaults` — user config value wins over default
1. `test_yaml_migration` — legacy `.yaml` config parses without error and matches equivalent `.toml` merge
1. `test_missing_required_key_raises` — accessing a key with no default raises expected exception, not silent `KeyError`
1. `test_no_grid_keys_in_defaults` — assert `main.plugins.grid` does not appear anywhere in `defaults.toml` (Phase 1 regression guard)

**`tests/test_bettercap.py`**

1. `test_session_get_success` — mock `GET /api/session` 200; assert client parses and returns session dict
1. `test_http_timeout_raises` — mock connection timeout; assert client raises within configured timeout window
1. `test_http_retry_on_failure` — mock two 500s then a 200; assert client retries and returns success
1. `test_websocket_reconnect_on_close` — mock websocket close event; assert reconnection is attempted
1. `test_websocket_reconnect_on_error` — mock websocket error event; assert reconnection is attempted
1. `test_no_grid_module_imported` — import `pwnagotchi.bettercap`; assert `'pwnagotchi.grid'` not in `sys.modules`

**`tests/test_plugins.py`**

1. `test_load_valid_plugin` — minimal in-memory plugin with `__author__`, `__version__`, `on_loaded`; loads without error
1. `test_plugin_on_loaded_called` — `on_loaded` fires exactly once after load
1. `test_bad_plugin_does_not_crash_loader` — plugin whose `__init__` raises; loader catches, logs, continues
1. `test_enable_disable_lifecycle` — load, disable, re-enable; callbacks fire in order
1. `test_unknown_callback_is_ignored` — dispatch unknown callback name; no exception
1. `test_on_peer_detected_not_registered` — `on_peer_detected` not in loader’s known callback registry (Phase 1 regression guard)

**`tests/test_ai_guard.py`**

1. `test_ai_available_false_when_tf_missing` — patch `sys.modules` so TF import raises `ImportError`; assert `pwnagotchi.ai.AI_AVAILABLE is False`
1. `test_ai_warning_logged_when_tf_missing` — same setup; assert `WARNING` with import error message is emitted
1. `test_agent_starts_in_manu_when_ai_unavailable` — construct agent with `AI_AVAILABLE = False` and mock config; assert initial mode is `MANU`
1. `test_ai_available_true_when_tf_present` — patch TF as importable stub; assert `AI_AVAILABLE is True` (auto-skip if TF not installed)

#### Acceptance checklist

- [ ] `sudo make image` completes on Bookworm 32-bit base
- [ ] `pip install -e .[dev]` works (hatchling, no setup.py)
- [ ] `requirements.txt` was generated by pip-compile on Python 3.11; `pycryptodome` absent
- [ ] Flask 3.x imports cleanly; webcfg plugin loads without error
- [ ] No `datetime.utcnow()`, `pkg_resources`, or bare `collections` (non-abc) calls remain
- [ ] `AI_AVAILABLE = False` path: daemon starts in MANU mode with no TF installed; WARNING in logs
- [ ] All 17 tests across 4 modules pass (`python -m pytest tests/ -v`)
- [ ] `ruff check pwnagotchi/` passes with zero errors
- [ ] USB gadget interface comes up via NetworkManager on Bookworm

-----

### Phase 3 — 64-bit migration (target: v3.0.0)

**Scope:** Migrate to Raspberry Pi OS Bookworm 64-bit (aarch64). Replace TF1/stable-baselines 2.x with PyTorch/stable-baselines3. Update build pipeline for aarch64. Same hardware (RPi Zero 2 W) — OS bitness changes, board does not.

**Entry condition:** Phase 2 acceptance checklist fully green.

**Breaking change:** Existing trained model files (`.pkl`, TF1 format) cannot be loaded by stable-baselines3. Accept the break; do not write migration code. Document in CHANGELOG.md.

#### Sub-tasks (do in order, one commit per step)

**A — Build pipeline**

- Update Ansible base image URL to Raspberry Pi OS Bookworm Lite 64-bit (aarch64)
- Nexmon: set `ARCH=arm64`; install 64-bit kernel headers package. Same firmware patches (BCM43436b0, BCM43430a1, BCM43455c0) — only build target changes
- bettercap: change `GOARCH=arm` → `GOARCH=arm64` in the Go build task. No source changes
- pwngrid: already removed in Phase 1 — no action needed
- Boot test image on RPi Zero 2 W 64-bit; verify bettercap, nexmon, display, and plugins before touching Python code

**B — gymnasium env adapter**

- Rewrite `pwnagotchi/ai/gym.py` (or equivalent env file) to the `gymnasium` 0.29 API:
  - `step()` returns 5-tuple `(obs, reward, terminated, truncated, info)` — not 4-tuple
  - `reset()` returns 2-tuple `(obs, info)` — not bare array
  - `terminated` and `truncated` are `bool`, not a single `done`
  - Namespace: `import gymnasium as gym`
- Observation space and action space dimensions are **unchanged**
- Grep for all `env.step(` call sites and update any that unpack a 4-tuple

**C — SB3 integration**

- Update `pwnagotchi/ai/__init__.py`: import from `stable_baselines3` instead of `stable_baselines`
- Update `requirements.in`:
  - Remove: `tensorflow`, `stable-baselines`, `keras-applications`, `keras-preprocessing`, `tensorboard`, `gym`
  - Add: `torch>=2.1`, `stable-baselines3>=2.0`, `gymnasium>=0.29`

**D — pip-compile (aarch64)**

- Run pip-compile against Python 3.11 aarch64 (in a Bookworm 64-bit QEMU or native environment)
- Commit output as `requirements-aarch64.txt`

#### Tests to write (Phase 3)

**`tests/test_gym_env.py`** — use mock bettercap state dict; no hardware required

1. `test_reset_returns_two_tuple` — `env.reset()` returns `(obs, info)`, not a bare array
1. `test_reset_obs_matches_observation_space` — `observation_space.contains(obs)` is `True` after reset
1. `test_step_returns_five_tuple` — `env.step(action)` unpacks to exactly 5 elements
1. `test_step_terminated_and_truncated_are_bools` — both `terminated` and `truncated` are `bool`, not a single `done`
1. `test_step_obs_within_bounds` — `observation_space.contains(obs)` is `True` after a step with a random valid action
1. `test_valid_actions_accepted` — all values in `action_space` accepted by `env.step()` without raising
1. `test_gymnasium_env_checker` — `gymnasium.utils.env_checker.check_env(env)` raises no warnings or errors

**`tests/test_sb3_integration.py`** — mark all with `@pytest.mark.slow`; excluded from fast CI run

1. `test_a2c_instantiates` — `stable_baselines3.A2C('MlpPolicy', env)` raises no exception
1. `test_a2c_learn_one_step` — `model.learn(total_timesteps=1)` completes without error
1. `test_model_save_load_roundtrip` — save to temp file; load back; loaded model’s policy network has same architecture

#### Acceptance checklist

- [ ] `sudo make image` completes on Bookworm 64-bit base
- [ ] `uname -m` on booted image returns `aarch64`
- [ ] nexmon monitor mode active; bettercap WiFi scanning works
- [ ] `import torch` and `import stable_baselines3` succeed on the image
- [ ] AI loads in under 60 seconds (vs 3–5 minutes with TF1)
- [ ] All 7 tests in `tests/test_gym_env.py` pass
- [ ] All 3 slow tests in `tests/test_sb3_integration.py` pass on aarch64
- [ ] All 17 Phase 2 tests still pass (no regressions)
- [ ] CHANGELOG.md documents model file incompatibility
- [ ] `requirements-aarch64.txt` committed and generated on aarch64 Python 3.11