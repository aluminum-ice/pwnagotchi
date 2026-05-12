# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`aluminum-ice/pwnagotchi` is a fork of [evilsocket/pwnagotchi](https://github.com/evilsocket/pwnagotchi) that targets Raspberry Pi Zero 2 W, 3B+, and 4 (the original Pi Zero W is unsupported — issues filed for it will be closed). The fork removes the Kali-Pi dependency, pins to Raspberry Pi OS Bullseye 32-bit Lite (2024-03-12), and compiles `nexmon`, `bettercap`, and Go from source during image build.

The application itself is a deep-RL agent (A2C with LSTM+MLP policy from `stable-baselines`) that drives `bettercap` over its REST/WebSocket API to capture WPA/WPA2 handshakes and PMKIDs, learning over time which channel-hop / association / deauth parameters work best in the surrounding RF environment.

## Build and dev commands

There is **no Python test suite** in this repo. Validation happens by building the SD-card image and booting it on a Pi.

Versioning: `pwnagotchi/_version.py` holds `__version__`. `setup.py` and the `Makefile` both read it, and the `PWN_VERSION` env var overrides the file contents (the GitHub release workflow `sed`s the file before building).

| Task | Command |
| --- | --- |
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

| Mixin | File | Responsibility |
| --- | --- | --- |
| `Client` | `pwnagotchi/bettercap.py` | HTTP REST + WebSocket RPC client for the local `bettercap` daemon. All wifi recon, association, deauth, channel set, handshakes file config goes through `self.run('wifi.xxx ...')`. |
| `Automata` | `pwnagotchi/automata.py` | Mood state machine: tracks `_epoch` (`ai/epoch.py`) and fires `set_bored`/`set_sad`/`set_excited`/`set_lonely`/`set_grateful`/`set_angry`. Mood transitions also broadcast plugin events. |
| `AsyncAdvertiser` | `pwnagotchi/mesh/utils.py` (+ `mesh/peer.py`, `mesh/wifi.py`) | Talks to the `pwngrid-peer` daemon to advertise this unit and discover nearby pwnagotchis. The `_peers` dict it owns is read by `Automata` for the "support network" / grateful logic. |
| `AsyncTrainer` | `pwnagotchi/ai/train.py` (+ `gym.py`, `featurizer.py`, `reward.py`, `parameter.py`) | Owns the `stable-baselines` A2C model and the gym env that wraps the agent. Trains in a background thread when `ai.enabled = true`. |

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
- This fork ships extra plugins that aren't in upstream: `mastodon.py`, `ntfy.py`, `ups_lite.py` (Waveshare UPS HAT), and `handshakes-m.py` (deletes empty pcaps). Enabling them is a manual edit to `/etc/pwnagotchi/config.toml`.

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
- Contributions should be `git commit -s` signed-off (DCO); see `CONTRIBUTING.md`. Don't mix refactors with fixes in the same PR.
- The default development branch in this environment is `claude/add-claude-documentation-plLHT` — push there, not to `master`.
- Avoid editing `requirements.txt` directly; it's `pip-compile`d from `requirements.in`. The pins are intentionally old to match what builds on `armhf` via piwheels.
- Don't add unit tests expecting CI to run them — there is no Python test job. The only CI is the release-image workflow.
