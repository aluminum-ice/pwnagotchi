# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`aluminum-ice/pwnagotchi` is a fork of [evilsocket/pwnagotchi](https://github.com/evilsocket/pwnagotchi) that targets Raspberry Pi Zero 2 W, 3B+, and 4 (the original Pi Zero W is unsupported — issues filed for it will be closed). The fork removes the Kali-Pi dependency, pins to Raspberry Pi OS Bullseye 32-bit Lite (2024-03-12), and compiles `nexmon`, `bettercap`, and Go from source during image build.

The application itself is a deep-RL agent (A2C with LSTM+MLP policy from `stable-baselines`) that drives `bettercap` over its REST/WebSocket API to capture WPA/WPA2 handshakes and PMKIDs, learning over time which channel-hop / association / deauth parameters work best in the surrounding RF environment.

## Build and dev commands

There is a small stdlib `unittest` test suite in `tests/test_phase1_removal.py` (8 regression tests: 7 pass in all environments, `test_agent_imports_cleanly` env-skips in dev without Flask/TF and passes on the Pi image). Full pytest infrastructure lands in Phase 2. The primary validation path remains building the SD-card image and booting it on a Pi.

Versioning: `pwnagotchi/_version.py` holds `__version__`. `setup.py` and the `Makefile` both read it, and the `PWN_VERSION` env var overrides the file contents (the GitHub release workflow `sed`s the file before building).

| Task | Command |
| --- | --- |
| Run Phase 1 regression tests | `python -m pytest tests/test_phase1_removal.py -v` (or `python -m unittest discover tests/`) |
| Compile all locale `.mo` files | `make langs` |
| Build the full Raspberry Pi image (sdist → Packer → Ansible → `.img` → `.zip`) | `sudo make image` (needs `packer`, `qemu-user-static`, `binfmt-support`, root) |
| Clean build artifacts | `make clean` |
| Build the Python sdist only | `python3 setup.py sdist` |
| Install Python pkg + system files (requires root for the system-file copy) | `sudo python3 setup.py install` |
| Add / update / compile a single language | `scripts/language.sh {add|update|compile} <lang>` |
| Render the UI offline against the layout for a given display | `scripts/preview.py` |
| CLI inside the image | `pwnagotchi [--manual] [--debug] [--config ...] [-U ...] [--print-config] [--clear] [--version]` |
| CLI plugin management (also via the `pwnagotchi` binary) | `pwnagotchi plugins {search|list|update|upgrade|enable|disable|install}` |

The release is produced by `.github/workflows/CreateRelease.yml` (`workflow_dispatch`-triggered). It rewrites `_version.py`, runs `make langs` + `make image`, then `pishrink`s and `7z`-compresses the image. The legacy `.travis.yml` targets `evilsocket/pwnagotchi` and is not used by this fork.

## Important environmental constraint

The Python code is **not designed to run on a developer workstation**. It freely reads `/etc/hostname`, `/proc/uptime`, `/proc/meminfo`, `/sys/class/thermal/...` and shells out to `hostname`, `halt`, `shutdown -r now`, `service bettercap restart`, `monstart`/`monstop`, `systemctl ...`. The `setup.py` `install` step also copies into `/etc/` and `/usr/bin/` (see `builder/data/`). When editing, assume the runtime is a Raspberry Pi running the built `pwnagotchi.service` under systemd with `bettercap.service`. Do not try to `pip install -e .` and run it locally — most code paths will fail.

## Architecture (the parts that span multiple files)

### Entry point and main loop
`bin/pwnagotchi` (installed as the `pwnagotchi` script via `setup.py`) is the only entry point.
- Parses args, loads TOML config (`-C` default + `-U` user overlay), sets up logging, mounts (`fs.setup_mounts`), fonts, plugins, and the `Display`.
- Constructs a single `Agent` (`pwnagotchi/agent.py`) with the display as its `view`.
- Branches into `do_auto_mode(agent)` or `do_manual_mode(agent)` (the latter just renders the last session report and idles).
- The auto-mode loop calls `agent.recon()`, groups APs by channel, hops to each channel, `associate()`s every AP, and `deauth()`s every client; then `agent.next_epoch()` advances the RL clock. `SIGUSR1` triggers a `restart(...)` to re-exec under systemd.

### `Agent` — multi-inheritance composition
`Agent(Client, Automata, AsyncTrainer)` mixes three orthogonal responsibilities; changing any of them requires understanding how they share state through `self`:

| Mixin | File | Responsibility |
| --- | --- | --- |
| `Client` | `pwnagotchi/bettercap.py` | HTTP REST + WebSocket RPC client for the local `bettercap` daemon. All wifi recon, association, deauth, channel set, handshakes file config goes through `self.run('wifi.xxx ...')`. |
| `Automata` | `pwnagotchi/automata.py` | Mood state machine: tracks `_epoch` (`ai/epoch.py`) and fires `set_bored`/`set_sad`/`set_excited`/`set_lonely`/`set_angry`. Note: `set_grateful`/`in_good_mood`/`_has_support_network_for` are dead code pending removal in Phase 1.5. `view.py:209` calls `in_good_mood()` and must be patched to `good_mood = False` before the method is deleted. |
| `AsyncTrainer` | `pwnagotchi/ai/train.py` (+ `gym.py`, `featurizer.py`, `reward.py`, `parameter.py`) | Owns the `stable-baselines` A2C model and the gym env that wraps the agent. Trains in a background thread when `ai.enabled = true`. |

The web UI runs inside the same process: `Agent.__init__` instantiates `Server(self, config['ui'])` from `pwnagotchi/ui/web/server.py`. Recovery state is written to `/root/.pwnagotchi-recovery`.

### WiFi channel utilities
`pwnagotchi/wifi.py` provides `NumChannels`, `NumChannelsExt`, and `freq_to_channel`. This module was relocated from `pwnagotchi/mesh/wifi.py` during Phase 1 when the `mesh/` package was deleted. Import from `pwnagotchi.wifi`, not `pwnagotchi.mesh.wifi`.

### Configuration
- Defaults: `pwnagotchi/defaults.toml` (deployed to `/etc/pwnagotchi/default.toml`).
- User overrides: `/etc/pwnagotchi/config.toml`, merged on top via `utils.load_config`.
- `utils.DottedTomlEncoder` is the canonical writer — used by `save_config` (plugin enable/disable, web UI edits) so output stays in dotted-key form rather than `[section]` blocks. Use it instead of vanilla `toml.dumps` when writing configs back to disk.
- The config is also accessible globally via `pwnagotchi.config` after `bin/pwnagotchi` assigns it.

### Plugin system
- `pwnagotchi/plugins/__init__.py` is event-bus + loader. Built-ins live in `pwnagotchi/plugins/default/`; users drop `.py` files under `main.custom_plugins`.
- A plugin subclasses `plugins.Plugin`. `Plugin.__init_subclass__` auto-instantiates the subclass on import and registers it in `loaded[plugin_name]`, so importing a plugin module **is** loading it.
- Callbacks are any method named `on_<event>` (full list in `pwnagotchi/plugins/default/example.py` — this is the canonical plugin template; mirror its callback signatures rather than inventing your own).
- **Removed callbacks (Phase 1):** `on_peer_detected` and `on_peer_lost` no longer exist and will never fire. `internet_available` no longer fires either (its only triggers were pwngrid connectivity checks). Do not implement these in new plugins.
- Dispatch is via a `ThreadPoolExecutor` (size 10) with a per-`plugin::callback` lock so callbacks of the same name on the same plugin are serialized, but different plugins run in parallel. Do **not** rely on callback ordering or completion before the next bettercap event.
- `plugins.on(event, ...)` fans out; `plugins.one(name, event, ...)` targets one plugin. Both schedule on the executor.
- `plugins.toggle_plugin(name, enable)` updates `config.toml`, calls `on_unload`/`on_loaded`/`on_ready`/`on_config_changed`/`on_ui_setup` in the right order. Use it instead of mutating `loaded` directly.
- `pwnagotchi/plugins/cmd.py` implements the `pwnagotchi plugins ...` subcommands (search/list/install/enable/disable/update/upgrade); they short-circuit `main()` in `bin/pwnagotchi` before the agent is built.
- This fork ships extra plugins that aren't in upstream: `mastodon.py`, `ntfy.py`, `ups_lite.py` (Waveshare UPS HAT), and `handshakes-m.py` (deletes empty pcaps). Enabling them is a manual edit to `/etc/pwnagotchi/config.toml`.

### UI layer
- `pwnagotchi/ui/view.py::View` owns the canvas, state, and `Voice` (i18n). `ROOT` is the module-global view used by `pwnagotchi.shutdown()` / `reboot()` for last-second redraws.
- `pwnagotchi/ui/display.py::Display(View)` selects a hardware backend from `pwnagotchi/ui/hw/` (Waveshare 1.x/2.x/2.13/2.7/2.9/3/4/inky/papirus/oledhat/lcdhat/displayhatmini/dfrobot/spotpear). The hw module returns a `layout()` dict that drives where each `View` element is drawn.
- **Note (Phase 1.5 pending):** `ui/hw/` layout dicts still contain dead `friend_face`/`friend_name` keys — these are not read by `View` and will be removed in Phase 1.5. Do not add new references to these keys.
- `pwnagotchi/ui/web/server.py` exposes the Flask-based web UI; plugins can register routes via `on_webhook(path, request)` (CSRF tokens required for POSTs — see `example.py`).
- Adding a new display means writing a hw module that exposes `name()`, `layout()`, `initialize()`, `render(canvas)`, `clear()`.

### i18n
- Voice strings live in `pwnagotchi/voice.py`. `scripts/language.sh update <lang>` regenerates the `.pot` and merges into `voice.po`. `make langs` compiles every `.po` into `.mo`.
- **Note (Phase 1.5 pending):** `voice.py` still contains orphaned `on_unread_messages`, `on_new_peer`, `on_lost_peer` methods — these have no callers and will be removed in Phase 1.5. Do not call them.
- When adding a user-facing string, wrap it in the same `gettext` pattern used in `voice.py` and re-run `update` for the languages you can.

### AI
- A2C agent built on `stable-baselines==2.10.2` / `tensorflow==1.13.1` (pinned old versions — do not casually bump). Model is persisted at `ai.path` (default `/root/brain.nn`).
- `ai/featurizer.py` builds the observation vector from epoch stats; `ai/reward.py` computes reward; `ai/parameter.py` describes the tunable knobs the agent can learn (these become the action space in `ai/gym.py`).
- `AsyncTrainer.start_ai()` is fired by `Agent` after enough epochs have elapsed; training emits `on_ai_*` plugin events.

## Repo conventions

- Python indentation is 4 spaces; everything else is 2 spaces (`.editorconfig`). Makefile uses tabs.
- Contributions should be `git commit -s` signed-off (DCO); see `CONTRIBUTING.md`. Don't mix refactors with fixes in the same PR.
- Avoid editing `requirements.txt` directly; it's `pip-compile`d from `requirements.in`. The pins are intentionally old to match what builds on `armhf` via piwheels.
- The test suite (`tests/test_phase1_removal.py`) uses stdlib `unittest` and can be run with `python -m pytest` or `python -m unittest discover tests/`. 7 of 8 tests pass in all environments; `test_agent_imports_cleanly` env-skips without Flask/TF and passes on the Pi image. Full pytest infrastructure (pytest, responses, pytest-asyncio) lands in Phase 2.

---

## Modernisation plan

This repo is undergoing a structured four-phase modernisation. Each phase has a defined scope, an ordered task list, and an acceptance checklist. **Do not make changes outside the current phase's scope.** If you find something that needs fixing that belongs to a later phase, add a `# TODO(phase-N): <description>` comment and move on.

Commit after each numbered step, not at the end of a session. One step = one commit.

The full design document (rationale, risk register, dependency tables, Claude Code session guidance) is in `docs/DESIGN.md`.

---

### Phase 1 — pwngrid & peer-advertising removal ✅ Complete (PR #139, v1.9.0)

All items complete. See `CHANGELOG.md` and `docs/DESIGN.md` Section 3 for the full record.

**What was removed:**
- `pwnagotchi/grid.py`, `pwnagotchi/identity.py`, `pwnagotchi/mesh/` (entire package), `pwnagotchi/plugins/default/grid.py`, `builder/data/etc/systemd/system/pwngrid-peer.service`
- Inbox web UI routes from `pwnagotchi/ui/web/handler.py`
- `AsyncAdvertiser` mixin from `Agent`; peer counter, advertising, and identity fingerprint from boot path
- `on_peer_detected`, `on_peer_lost` from default plugins and plugin loader dispatch
- pwngrid tasks from Ansible playbook; `After=pwngrid-peer.service` from `pwnagotchi.service`
- `main.plugins.grid` block from `defaults.toml`; `pycryptodome` commented out in `requirements.in`

**What was added/fixed:**
- `pwnagotchi/wifi.py` — channel math relocated from deleted `mesh/wifi.py`
- `tests/test_phase1_removal.py` — 8 regression tests (7 pass universally; `test_agent_imports_cleanly` env-skips in dev without Flask/TF, passes on Pi image)

**Breaking plugin API changes:** `on_peer_detected`, `on_peer_lost`, and `internet_available` no longer fire.

**PR housekeeping:** PR #139 was pushed directly to master rather than merged via GitHub's merge button, so it still shows as Open on GitHub. It should be closed manually ("Close pull request" without merging) to keep the PR history clean.

---

### Phase 1.5 — dead code sweep (target: v1.9.1)

**Entry condition:** Phase 1 merged to master. ✅

**Scope:** Remove dead code left behind by Phase 1 but deferred from it. No dependency changes, no new features, no test infrastructure changes beyond adding regression guards to the existing test file.

**Do not touch:** `requirements.in`, `setup.py`, the Ansible playbook, the AI stack, any file not named below.

#### Sub-task A — voice.py orphaned methods and i18n strings

**Files:** `pwnagotchi/voice.py`, `pwnagotchi/locale/**/*.po`, `pwnagotchi/locale/**/*.pot`

**Steps:**
1. Confirm no callers: `grep -r "on_unread_messages\|on_new_peer\|on_lost_peer" pwnagotchi/` (should return only voice.py definitions)
2. Delete `on_unread_messages`, `on_new_peer`, `on_lost_peer` from `voice.py`
3. Run `scripts/language.sh update <lang>` for every language under `pwnagotchi/locale/`
4. Run `make langs`
5. Commit: `Phase 1.5: remove orphaned peer/inbox voice methods and stale i18n strings`

**Prompt for Claude Code:**
> *"Read `docs/DESIGN.md` Section 4.1. Run `grep -r 'on_unread_messages\|on_new_peer\|on_lost_peer' pwnagotchi/` and show me the output. Confirm the only definitions are in `voice.py` and there are no remaining callers. Then delete those three methods from `voice.py` — show me the diff before applying. Then run `scripts/language.sh update <lang>` for every language directory under `pwnagotchi/locale/`, then `make langs`. Show me which strings were marked obsolete. Commit the voice.py deletion and updated locale files together."*

**Acceptance:** `grep -r "on_unread_messages\|on_new_peer\|on_lost_peer" pwnagotchi/voice.py` returns nothing. `make langs` exits 0.

---

#### Sub-task B — ui/hw/ dead layout entries

**Files:** `pwnagotchi/ui/hw/*.py` (~30 files)

**Steps:**
1. Get the affected file list: `grep -rl "friend_face\|friend_name" pwnagotchi/ui/hw/`
2. In each file, remove only the `friend_face` and `friend_name` keys from the dict returned by `layout()`. Touch nothing else.
3. Verify: `grep -r "friend_face\|friend_name" pwnagotchi/ui/hw/` returns nothing
4. Commit: `Phase 1.5: remove dead friend_face/friend_name layout entries from ui/hw modules`

**Prompt for Claude Code:**
> *"Read `docs/DESIGN.md` Section 4.2. Run `grep -rl 'friend_face\|friend_name' pwnagotchi/ui/hw/` and show me the full list of affected files. For each file in that list, remove the `friend_face` and `friend_name` keys from the dict returned by the `layout()` method. Touch nothing else in those files. Show me the full file list and a representative diff before applying to all of them. After applying, run `grep -r 'friend_face\|friend_name' pwnagotchi/ui/hw/` and confirm it returns nothing. Commit."*

**Acceptance:** `grep -r "friend_face\|friend_name" pwnagotchi/ui/hw/` returns nothing.

---

#### Sub-task C — automata.py grateful mood removal

**Files:** `pwnagotchi/automata.py`, `pwnagotchi/ui/view.py`

**Context:** `_has_support_network_for()` returns `False` unconditionally (peers are gone). This makes `in_good_mood()` always `False`, making every `else: self.set_grateful()` branch unreachable. However, `in_good_mood()` has a **live external caller in `view.py:209`** (`good_mood = self._agent.in_good_mood()`) — deleting it without patching `view.py` first causes a runtime `AttributeError`. The fix is behaviour-preserving: replace the call with `good_mood = False` (which is what `in_good_mood()` already always returns).

**Note on `bond_encounters_factor`:** `pwnagotchi/ai/epoch.py:87` reads this unconditionally. It must **remain** in `defaults.toml`. Do not remove it — removal belongs to Phase 3.

**Steps:**
1. Run scope grep across all affected files — review before touching anything:
   `grep -rn "set_grateful\|in_good_mood\|_has_support_network_for\|bond_encounters_factor" pwnagotchi/automata.py pwnagotchi/defaults.toml pwnagotchi/voice.py pwnagotchi/ui/view.py pwnagotchi/ai/epoch.py`
2. In `pwnagotchi/ui/view.py`, replace `good_mood = self._agent.in_good_mood()` with `good_mood = False`. Do not touch anything else in `view.py`.
3. Delete `_has_support_network_for`, `in_good_mood`, and `set_grateful` from `automata.py`
4. In `set_lonely`, `set_bored`, `set_sad`, `set_angry`, and `next_epoch`: remove the `else: self.set_grateful()` branch and the `if not self._has_support_network_for(...):` condition. Dedent the remaining mood-setting body.
5. In `set_bored` and `set_sad`, remove the now-unused local `factor` variable. Do not touch the `factor` parameter in `set_angry`.
6. Do NOT remove `bond_encounters_factor` from `defaults.toml`.
7. Run `python -m py_compile pwnagotchi/automata.py pwnagotchi/ui/view.py`
8. Commit: `Phase 1.5: remove unreachable grateful mood logic from automata.py and view.py`

**Prompt for Claude Code:**
> *"Read `docs/DESIGN.md` Section 4.3 carefully — there is a defect correction here that overrides earlier versions of this sub-task. Step 1: run `grep -rn 'set_grateful\|in_good_mood\|_has_support_network_for\|bond_encounters_factor' pwnagotchi/automata.py pwnagotchi/defaults.toml pwnagotchi/voice.py pwnagotchi/ui/view.py pwnagotchi/ai/epoch.py` and show me the full output. Step 2: in `pwnagotchi/ui/view.py`, replace `good_mood = self._agent.in_good_mood()` with `good_mood = False` — show me the diff before applying, touch nothing else in view.py. Step 3: delete `_has_support_network_for`, `in_good_mood`, and `set_grateful` from `automata.py` — show me the diff. Step 4: in `set_lonely`, `set_bored`, `set_sad`, `set_angry`, and `next_epoch`, remove the `else: self.set_grateful()` branch and the `if not self._has_support_network_for(...):` condition; dedent the remaining body — show me each diff before applying. Step 5: in `set_bored` and `set_sad`, remove the now-unused local `factor` variable; do not touch the `factor` parameter in `set_angry`. Step 6: do NOT remove `bond_encounters_factor` from `defaults.toml` — it is consumed by `pwnagotchi/ai/epoch.py:87`. Step 7: run `python -m py_compile pwnagotchi/automata.py pwnagotchi/ui/view.py`. Commit."*

**Acceptance:**
- `grep -r "set_grateful\|in_good_mood\|_has_support_network_for" pwnagotchi/` returns nothing
- `grep "in_good_mood" pwnagotchi/ui/view.py` returns nothing (replaced with `good_mood = False`)
- `grep "bond_encounters_factor" pwnagotchi/defaults.toml` returns the entry (not removed)
- `python -m py_compile pwnagotchi/automata.py pwnagotchi/ui/view.py` exits 0

---

#### Sub-task D — regression test update

**Files:** `tests/test_phase1_removal.py`

**Steps:**
1. Add three new test methods (stdlib `unittest` only):
   - `test_voice_peer_methods_removed` — assert `Voice` has no `on_unread_messages`, `on_new_peer`, `on_lost_peer` attributes
   - `test_no_friend_layout_keys_in_hw_modules` — for each hw module with a `layout()` function, assert `'friend_face'` and `'friend_name'` are not keys in the returned dict
   - `test_grateful_mood_removed` — assert `Automata` has no `set_grateful`, `in_good_mood`, `_has_support_network_for` attributes
2. Run: `python -m pytest tests/test_phase1_removal.py -v` — all 11 must pass
3. Commit: `Phase 1.5: add regression guards for dead code sweep`

**Prompt for Claude Code:**
> *"Read `docs/DESIGN.md` Section 4.4. Add three new test methods to `tests/test_phase1_removal.py` using stdlib `unittest` only: (1) `test_voice_peer_methods_removed` — import `pwnagotchi.voice`; assert that `Voice` has no attributes named `on_unread_messages`, `on_new_peer`, or `on_lost_peer`; (2) `test_no_friend_layout_keys_in_hw_modules` — import all modules under `pwnagotchi/ui/hw/` that expose a `layout()` function; for each, call `layout()` and assert neither `'friend_face'` nor `'friend_name'` is a key in the returned dict; (3) `test_grateful_mood_removed` — import `pwnagotchi.automata`; assert `Automata` has no attributes named `set_grateful`, `in_good_mood`, or `_has_support_network_for`. Run `python -m pytest tests/test_phase1_removal.py -v` and confirm all 11 tests pass. Commit."*

**Acceptance:** `python -m pytest tests/test_phase1_removal.py -v` reports 11 passed.

---

#### Phase 1.5 acceptance checklist
- [ ] `grep -r "on_unread_messages\|on_new_peer\|on_lost_peer" pwnagotchi/voice.py` returns nothing
- [ ] `make langs` exits 0
- [ ] `grep -r "friend_face\|friend_name" pwnagotchi/ui/hw/` returns nothing
- [ ] `grep -r "set_grateful\|in_good_mood\|_has_support_network_for" pwnagotchi/` returns nothing
- [ ] `grep "in_good_mood" pwnagotchi/ui/view.py` returns nothing (replaced with `good_mood = False`)
- [ ] `grep "bond_encounters_factor" pwnagotchi/defaults.toml` returns the entry (it was NOT removed — consumed by ai/epoch.py)
- [ ] `python -m py_compile pwnagotchi/automata.py pwnagotchi/ui/view.py` exits 0
- [ ] `python -m pytest tests/test_phase1_removal.py -v` reports 11 passed
- [ ] CHANGELOG.md updated

---

### Phase 2 — 32-bit stabilisation (target: v2.0.0)

**Entry condition:** Phase 1.5 acceptance checklist fully green.

**Scope:** Upgrade base image to Bookworm 32-bit, Python 3.11, Flask 3.x, and pyproject.toml. Add full test infrastructure. Migrate USB networking to NetworkManager. No AI stack changes.

**Do not touch:** `requirements.in` (until sub-task E), the AI stack internals, the Ansible image steps beyond the base image URL.

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
- Remove `MarkupSafe < 2.1.0` cap; fix misleading `itsdangerous` comment in `requirements.txt`
- Audit `webcfg` plugin: `flask.escape()` → `markupsafe.escape()`; `flask.Markup` → `markupsafe.Markup`

**D — Python 3.11 compat**
- Replace `datetime.utcnow()` → `datetime.now(timezone.utc)` throughout
- Replace `pkg_resources` → `importlib.resources`
- Fix any bare `collections` imports that should be `collections.abc`
- Run `python -m py_compile` on every `.py` file under `pwnagotchi/`

**E — pip-compile**
- Re-run `pip-compile --resolver=backtracking --strip-extras --prefer-binary` against Python 3.11 in a Bookworm 32-bit environment (QEMU or Docker — not a dev workstation)
- `pycryptodome` must be absent from the output
- Commit as `requirements.txt`

**F — AI guard hardening**
- In `pwnagotchi/ai/__init__.py`, wrap the TF import in try/except; set module-level `AI_AVAILABLE = False` on failure; log a `WARNING` with the import error
- In `agent.py`, check `AI_AVAILABLE` before entering AI-driven mode; fall back to `MANU` cleanly
- Add a small UI indicator so the operator can see AI is inactive

**G — Test infrastructure**
- Add `pytest`, `pytest-asyncio`, `responses` as dev dependencies in `pyproject.toml` `[dev]` optional group
- Add `ruff` config (`ruff.toml`) and `.pre-commit-config.yaml`; apply formatting as a **separate cosmetic commit**
- Write the four test modules below

**H — USB networking**
- Replace `/etc/network/interfaces.d/usb0` with a NetworkManager `.nmconnection` profile for the USB gadget interface

#### Tests to write (Phase 2)

**`tests/test_config.py`**
1. `test_load_valid_toml` — load a minimal valid `config.toml`; assert `main.name` is present
2. `test_defaults_are_applied` — load empty user config; assert values from `defaults.toml` appear in merged result
3. `test_user_values_override_defaults` — user config value wins over default
4. `test_yaml_migration` — legacy `.yaml` config parses without error and matches equivalent `.toml` merge
5. `test_missing_required_key_raises` — accessing a key with no default raises expected exception, not silent `KeyError`
6. `test_no_grid_keys_in_defaults` — assert `main.plugins.grid` does not appear in `defaults.toml` *(Phase 1 regression guard)*

**`tests/test_bettercap.py`**
1. `test_session_get_success` — mock `GET /api/session` 200; assert client parses and returns session dict
2. `test_http_timeout_raises` — mock connection timeout; assert client raises within configured timeout window
3. `test_http_retry_on_failure` — mock two 500s then a 200; assert client retries and returns success
4. `test_websocket_reconnect_on_close` — mock websocket close event; assert reconnection is attempted
5. `test_websocket_reconnect_on_error` — mock websocket error event; assert reconnection is attempted
6. `test_no_grid_module_imported` — import `pwnagotchi.bettercap`; assert `'pwnagotchi.grid'` not in `sys.modules`

**`tests/test_plugins.py`**
1. `test_load_valid_plugin` — minimal in-memory plugin with `__author__`, `__version__`, `on_loaded`; loads without error
2. `test_plugin_on_loaded_called` — `on_loaded` fires exactly once after load
3. `test_bad_plugin_does_not_crash_loader` — plugin whose `__init__` raises; loader catches, logs, continues
4. `test_enable_disable_lifecycle` — load, disable, re-enable; callbacks fire in order
5. `test_unknown_callback_is_ignored` — dispatch unknown callback name; no exception
6. `test_on_peer_detected_not_registered` — `on_peer_detected` not in loader's known callback registry *(Phase 1 regression guard)*

**`tests/test_ai_guard.py`**
1. `test_ai_available_false_when_tf_missing` — patch `sys.modules` so TF import raises `ImportError`; assert `pwnagotchi.ai.AI_AVAILABLE is False`
2. `test_ai_warning_logged_when_tf_missing` — same setup; assert `WARNING` with import error message is emitted
3. `test_agent_starts_in_manu_when_ai_unavailable` — construct agent with `AI_AVAILABLE = False` and mock config; assert initial mode is `MANU`
4. `test_ai_available_true_when_tf_present` — patch TF as importable stub; assert `AI_AVAILABLE is True` *(auto-skip if TF not installed)*

#### Acceptance checklist
- [ ] `sudo make image` completes on Bookworm 32-bit base
- [ ] `pip install -e .[dev]` works (hatchling, no setup.py)
- [ ] `requirements.txt` generated by pip-compile on Python 3.11; `pycryptodome` absent
- [ ] Flask 3.x imports cleanly; webcfg plugin loads without error
- [ ] No `datetime.utcnow()`, `pkg_resources`, or bare `collections` (non-abc) calls remain
- [ ] `AI_AVAILABLE = False` path: daemon starts in MANU mode with no TF installed; WARNING in logs
- [ ] All 17 tests across 4 modules pass (`python -m pytest tests/ -v`)
- [ ] `ruff check pwnagotchi/` passes with zero errors
- [ ] USB gadget interface comes up via NetworkManager on Bookworm

---

### Phase 3 — 64-bit migration (target: v3.0.0)

**Scope:** Migrate to Raspberry Pi OS Bookworm 64-bit (aarch64). Replace TF1/stable-baselines 2.x with PyTorch/stable-baselines3. Update build pipeline for aarch64. Same hardware (RPi Zero 2 W) — OS bitness changes, board does not.

**Entry condition:** Phase 2 acceptance checklist fully green.

**Breaking change:** Existing trained model files (`.pkl`, TF1 format) cannot be loaded by stable-baselines3. Accept the break; do not write migration code. Document in CHANGELOG.md.

#### Sub-tasks (do in order, one commit per step)

**A — Build pipeline**
- Update Ansible base image URL to Raspberry Pi OS Bookworm Lite 64-bit (aarch64)
- Nexmon: set `ARCH=arm64`; install 64-bit kernel headers package. Same firmware patches (BCM43436b0, BCM43430a1, BCM43455c0) — only build target changes
- bettercap: change `GOARCH=arm` → `GOARCH=arm64` in the Go build task. No source changes
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
2. `test_reset_obs_matches_observation_space` — `observation_space.contains(obs)` is `True` after reset
3. `test_step_returns_five_tuple` — `env.step(action)` unpacks to exactly 5 elements
4. `test_step_terminated_and_truncated_are_bools` — both `terminated` and `truncated` are `bool`, not a single `done`
5. `test_step_obs_within_bounds` — `observation_space.contains(obs)` is `True` after a step with a random valid action
6. `test_valid_actions_accepted` — all values in `action_space` accepted by `env.step()` without raising
7. `test_gymnasium_env_checker` — `gymnasium.utils.env_checker.check_env(env)` raises no warnings or errors

**`tests/test_sb3_integration.py`** — mark all with `@pytest.mark.slow`; excluded from fast CI run
1. `test_a2c_instantiates` — `stable_baselines3.A2C('MlpPolicy', env)` raises no exception
2. `test_a2c_learn_one_step` — `model.learn(total_timesteps=1)` completes without error
3. `test_model_save_load_roundtrip` — save to temp file; load back; loaded model's policy network has same architecture

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
