# Pwnagotchi Modernisation Design Document

**Phase 1 — pwngrid & Peer-Advertising Removal · Phase 2 — 32-bit Stabilisation · Phase 3 — 64-bit Migration**

|                  |                                        |
|------------------|----------------------------------------|
|**Status**        |DRAFT                                   |
|**Version**       |0.3                                     |
|**Date**          |May 2026                                |
|**Reference Repo**|aluminum-ice/pwnagotchi (latest: v1.8.5)|
|**Upstream Repo** |evilsocket/pwnagotchi (v1.5.3, archived)|

-----

## Table of Contents

1. [Executive Summary](#1-executive-summary)
1. [Current State Analysis](#2-current-state-analysis)
1. [Phase 1 — pwngrid & Peer-Advertising Removal](#3-phase-1--pwngrid--peer-advertising-removal)
1. [Claude Code Implementation Guidance](#4-claude-code-implementation-guidance)
1. [Phase 2 — 32-bit Stabilisation](#5-phase-2--32-bit-stabilisation)
1. [Phase 3 — 64-bit Migration](#6-phase-3--64-bit-migration)
1. [What is Explicitly Out of Scope](#7-what-is-explicitly-out-of-scope)
1. [Risk Register](#8-risk-register)
1. [Implementation Sequence](#9-implementation-sequence)
1. [Appendix](#10-appendix)

-----

## 1. Executive Summary

**Reference codebase:** This document targets the **aluminum-ice/pwnagotchi** fork (latest release v1.8.5, February 2024), not the archived evilsocket/pwnagotchi original.

This document describes a three-phase modernisation plan. A new Phase 1 has been inserted ahead of the previously described stabilisation and migration work, dedicated entirely to the removal of pwngrid. This change was motivated by two facts: the evilsocket/pwngrid project is unmaintained and the api.pwnagotchi.ai cloud service it connects to is defunct; and the pwngrid binary is the only pre-compiled external binary in the image that cannot be replaced by a source build or dropped in favour of a PyPI package. Removing it cleanly before doing anything else produces a smaller, better-defined codebase for all subsequent phases.

The three phases are:

- **Phase 1 — pwngrid & Peer-Advertising Removal:** Remove the pwngrid binary, the pwngrid-peer systemd service, the identity/grid Python modules, the grid default plugin, `pwnagotchi/mesh/` (the dot11 peer-advertising layer), the `on_peer_detected` plugin callback, and all related Ansible tasks and config.toml keys.
- **Phase 2 — 32-bit Stabilisation:** Upgrade base image to Bookworm 32-bit, Python 3.11, Flask 3.x, pyproject.toml, test infrastructure, NetworkManager networking.
- **Phase 3 — 64-bit Migration:** Migrate to Bookworm 64-bit, replace TF1/SB2 with PyTorch/SB3, aarch64 image.

> **Design Principle — Minimal footprint:** Change only what must change. The plugin callback API (except `on_peer_detected`, removed in Phase 1), the TOML configuration schema, and the bettercap REST interface are stable across all three phases.

-----

## 2. Current State Analysis

### 2.1 Fork Summary

The aluminum-ice fork diverges from evilsocket/pwnagotchi in the build pipeline and several Python source files. The Python package structure and plugin API are unchanged from the original. Key improvements already made by the fork author (**not repeated in any phase**):

|Item                             |Introduced|Description                                                     |
|---------------------------------|----------|----------------------------------------------------------------|
|Kali-Pi removal                  |v1.7.0    |Moved to Raspberry Pi OS Bullseye Lite                          |
|nexmon source build              |v1.7.0    |BCM43436b0, BCM43430a1, BCM43455c0 compiled from source         |
|bettercap source build           |v1.7.0    |Go v1.22.4; eliminates binary trust concern                     |
|WiFi power-save disabled         |v1.7.0    |Prevents BRCM firmware crashes during deauth                    |
|bettercap.py websocket resilience|v1.8.x    |try/except on all errors; reconnection logic                    |
|ARCHFLAG = armv7l                |v1.8.x    |Correct compiler target for Zero 2 W on armhf Debian            |
|pip-compile workflow             |v1.x      |requirements.in + requirements.txt; piwheels in –extra-index-url|
|main.log.debug TOML flag         |v1.8.x    |Debug mode controllable from config.toml                        |
|GitHub Action image build        |v1.x      |Automated image build + version injection                       |

### 2.2 Fork vs. Original Comparison

|Layer              |evilsocket/pwnagotchi        |aluminum-ice/pwnagotchi                                    |
|-------------------|-----------------------------|-----------------------------------------------------------|
|OS / base image    |Kali-Pi (32-bit)             |Raspberry Pi OS Bullseye Lite 32-bit (2024-03-12)          |
|Target hardware    |RPi Zero W (ARMv6)           |RPi Zero 2 W (ARMv7l), 3B+, Pi 4                           |
|Original RPi Zero W|Supported                    |**Dropped** — explicitly unsupported                       |
|bettercap          |Pre-compiled binary          |Compiled from source (Go v1.22.4)                          |
|nexmon             |Pre-compiled binary          |Compiled from source                                       |
|pwngrid            |Pre-compiled armhf binary    |Pre-compiled armhf binary (unchanged; removed in Phase 1)  |
|Dependency mgmt    |setup.py with hard pins      |pip-compile; requirements.in + requirements.txt            |
|bettercap.py       |Synchronous; no retry/timeout|try/except on websocket; reconnection logic; crash recovery|
|WiFi power save    |Default on                   |Explicitly disabled                                        |
|ARCHFLAG           |Absent (builds for ARMv6l)   |Explicit armv7l in Ansible                                 |

### 2.3 Dependency Snapshot (requirements.in)

|Package           |Pinned Version      |Notes                                                       |
|------------------|--------------------|------------------------------------------------------------|
|`tensorflow`      |`>= 1.8.0, < 1.14.0`|Capped below 1.14 (breaking API changes)                    |
|`stable-baselines`|`~= 2.7`            |Kept; comment notes SB3/PyTorch requires 64-bit             |
|`gym`             |`~= 0.14, < 0.22`   |Capped; atari extra excluded                                |
|`numpy`           |`~= 1.21.4`         |Pinned to avoid binary incompatibility with stable-baselines|
|`Pillow`          |`>= 5.4`            |Resolves to 9.2.0 in compiled output                        |
|`flask`           |`~= 1.0`            |Flask 1.x EOL; MarkupSafe conflict hack in place            |
|`MarkupSafe`      |`< 2.1.0`           |Explicit hack for Flask 1.x + Jinja2 2.x compat             |
|`requests`        |`~= 2.21`           |Resolves to 2.28.1 in compiled output                       |
|`websockets`      |`~= 8.1`            |Pinned; bettercap.py uses websockets 8.x API                |
|`toml`            |`~= 0.10`           |Config loading; separate package (not stdlib tomllib)       |
|`pycryptodome`    |`~= 3.9`            |RSA/SHA256 for pwngrid identity — **removed in Phase 1**    |

### 2.4 Known Remaining Issues

**Python Runtime**

- Python 3.7 pip-compile target (EOL June 2023). Bullseye ships Python 3.9; Bookworm ships 3.11.
- `setup.py` with `distutils` — removed in Python 3.12.
- No type annotations, no linter configuration, no formatter.

**AI / Dependency Stack**

- TF < 1.14 cap is correct but TF 1.x still has no 64-bit ARMv8 PyPI wheel — the core Phase 3 blocker.
- Flask 1.x + `MarkupSafe < 2.1.0` hack is fragile. Flask 1.x has known CVEs.
- gym < 0.22 cap locks to a pre-2022 API superseded by gymnasium.
- `itsdangerous~=1.1.0` comment in requirements.txt is misleading.

**Build Pipeline**

- No test suite. pip-compile process not automated in CI.
- GitHub Action builds the full image but runs no Python tests.
- pwngrid remains a pre-compiled armhf binary with no checksum verification.

**System Integration**

- `/etc/network/interfaces.d/usb0`: legacy networking not migrated to NetworkManager.

-----

## 3. Phase 1 — pwngrid & Peer-Advertising Removal

**Objective:** Remove all dependency on the pwngrid binary, the api.pwnagotchi.ai cloud service, and the local dot11 peer-advertising feature (`pwnagotchi/mesh/`). Nothing that does not touch pwngrid or peer-advertising should change in this phase.

**Why Phase 1 and not folded into Phase 2:** This removal is a feature removal, not a stabilisation task. Mixing it with the Python runtime upgrade and Flask upgrade in a single release makes regressions harder to isolate. Doing it first also eliminates `pycryptodome` from the dependency tree before pip-compile is re-run for Python 3.11, producing a cleaner lock file.

### 3.1 Pre-condition: Confirm api.pwnagotchi.ai Status

Before cutting any code, verify:

- `evilsocket/pwngrid`: last commit January 2024; no releases since 2021
- `api.pwnagotchi.ai`: verify DNS is unreachable; `socket.gethostbyname('api.pwnagotchi.ai')` should fail
- Port 8666: a PR comment in the aluminum-ice repo confirms port 8666 is not currently accessible
- Document the confirmation in CHANGELOG.md before writing any code

### 3.2 Complete pwngrid Surface Area

|Component                |File / Location                     |Role                                                                                 |Removal Action                             |
|-------------------------|------------------------------------|-------------------------------------------------------------------------------------|-------------------------------------------|
|`grid.py`                |`pwnagotchi/grid.py`                |REST client to pwngrid-peer on port 8666                                             |Delete file                                |
|`identity.py`            |`pwnagotchi/identity.py`            |RSA keypair generation/signing for pwngrid enrollment                                |Delete file; remove pycryptodome           |
|`mesh/`                  |`pwnagotchi/mesh/`                  |dot11 custom IE peer-advertising                                                     |Delete directory                           |
|`plugins/default/grid.py`|`pwnagotchi/plugins/default/grid.py`|Cloud enrollment; unread message count in UI                                         |Delete file                                |
|`pwngrid-peer.service`   |`builder/data/etc/systemd/system/`  |systemd service running pwngrid on 127.0.0.1:8666                                    |Delete file                                |
|`agent.py`               |`pwnagotchi/agent.py`               |Calls `grid.is_connected()`, `grid.call()`; owns `_peers`; inherits `AsyncAdvertiser`|Remove imports, call sites, `_peers`, mixin|
|`automata.py`            |`pwnagotchi/automata.py`            |Dispatches `on_peer_detected`; peer-related state                                    |Remove dispatch and state                  |
|`ui/view.py`             |`pwnagotchi/ui/view.py`             |`on_unread_messages()` display callback                                              |Remove method and UI element               |
|`defaults.toml`          |`pwnagotchi/defaults.toml`          |`main.plugins.grid.*` config keys                                                    |Remove grid plugin config block            |
|`pwnagotchi.yml`         |`builder/pwnagotchi.yml`            |Download, install, keygen, service-enable tasks                                      |Remove those four tasks only               |
|`pycryptodome`           |`requirements.in`                   |RSA/SHA256 for pwngrid identity — no other use                                       |Comment out; defer pip-compile to Phase 2  |

### 3.3 Peer-Advertising Removal (mesh/)

`pwnagotchi/mesh/` implements local dot11 peer-advertising: custom 802.11 information elements broadcast by bettercap caplets and parsed by `mesh/peer.py` to detect nearby pwnagotchi units. This drives the “met N peers” counter and the `on_peer_detected` plugin callback.

**This feature is removed in full.** Reasons:

- IE parsing in `mesh/peer.py` routes through `pwngrid-peer` at runtime; without the binary it is inert
- Cleanly separating local mesh from pwngrid-peer requires reverse-engineering undocumented wire formats
- None of the three aluminum-ice default plugins use `on_peer_detected`
- If peer-detection is wanted in future, it can be reintroduced as a standalone feature using bettercap’s native 802.11 capabilities — scoped as a feature addition, not a cleanup

> **Plugin API Breaking Change:** `on_peer_detected` is removed from the plugin callback API. Any third-party plugin implementing this callback will load without error but the callback will never fire. Document prominently in CHANGELOG.md. The peers counter is removed from the display face.

### 3.4 Files to Delete Outright

- `pwnagotchi/grid.py`
- `pwnagotchi/identity.py`
- `pwnagotchi/mesh/` (entire directory)
- `pwnagotchi/plugins/default/grid.py`
- `builder/data/etc/systemd/system/pwngrid-peer.service`

### 3.5 Ansible Playbook Changes

Remove from `builder/pwnagotchi.yml`:

- Task that downloads the pwngrid armhf binary from GitHub releases
- Task that installs it to `/usr/bin/`
- Task that runs `pwngrid -generate -keys /etc/pwnagotchi` to create the RSA keypair
- Task that copies or enables the `pwngrid-peer.service` systemd unit

> **Important — Keep the `/etc/pwnagotchi/` directory creation task:**
> 
> The `/etc/pwnagotchi/` directory is **not** a pwngrid-specific path. It is the primary application config directory, referenced independently of pwngrid:
> 
> - `defaults.toml`: `main.confd = "/etc/pwnagotchi/conf.d/"`
> - User config: `/etc/pwnagotchi/config.toml` — the standard location documented across all installation guides
> - `defaults.toml`: `main.log.path = "/etc/pwnagotchi/log/pwnagotchi.log"`
> 
> The only pwngrid-specific content inside this directory was the RSA keypair (`key.pem`, `fingerprint.pem`) written by `pwngrid -generate`. Removing that Ansible task is correct. The directory creation task itself **must stay**. New images built after Phase 1 will have the directory but no RSA key files inside it, which is the correct state.

Also remove from `defaults.toml`: the entire `[main.plugins.grid]` configuration block.

### 3.6 Dependency Change

Remove `pycryptodome` from `requirements.in`. It is used exclusively in `identity.py` for RSA-PKCS1 signing of pwngrid enrollment payloads. No other module in the codebase uses it. Do **not** re-run pip-compile in Phase 1 — that is deferred to Phase 2 when the Python version also changes. Comment it out with a note.

### 3.7 Automated Removal Verification Tests

Write `tests/test_phase1_removal.py` using stdlib `unittest` only (pytest not yet installed). These are negative-space assertions that prevent future re-introduction of the removed components.

1. `test_grid_module_not_importable` — `import pwnagotchi.grid` raises `ModuleNotFoundError`
1. `test_identity_module_not_importable` — `import pwnagotchi.identity` raises `ModuleNotFoundError`
1. `test_mesh_module_not_importable` — `import pwnagotchi.mesh` raises `ModuleNotFoundError`
1. `test_pycryptodome_not_imported_by_core` — import `pwnagotchi`; assert `'Crypto'` not in `sys.modules`
1. `test_on_peer_detected_not_in_plugin_callbacks` — instantiate plugin loader; assert `'on_peer_detected'` not in known callback registry
1. `test_agent_imports_cleanly` — import `pwnagotchi.agent` with `pwnagotchi.grid` absent; assert no `ImportError` or `AttributeError`

These six tests are fast (no I/O, no mocking framework) and run in under a second. They are written before Phase 2 pytest infrastructure exists, using stdlib `unittest`, and are later absorbed into pytest.

### 3.8 Phase 1 Deliverables

|Deliverable                |Description                                                                                               |Priority|
|---------------------------|----------------------------------------------------------------------------------------------------------|--------|
|Confirmation doc           |Written confirmation api.pwnagotchi.ai is defunct; added to CHANGELOG.md                                  |P0      |
|Delete grid.py             |Remove `pwnagotchi/grid.py`                                                                               |P0      |
|Delete identity.py         |Remove `pwnagotchi/identity.py`                                                                           |P0      |
|Delete grid plugin         |Remove `pwnagotchi/plugins/default/grid.py`; remove from defaults.toml                                    |P0      |
|Delete pwngrid-peer.service|Remove systemd unit file                                                                                  |P0      |
|Delete mesh/               |Remove `pwnagotchi/mesh/` and `on_peer_detected` callback                                                 |P0      |
|Clean agent.py             |Remove all grid.* and identity.* imports and call sites; remove peer counter; remove AsyncAdvertiser mixin|P0      |
|Clean automata.py          |Remove `on_peer_detected` dispatch; remove grid-related state                                             |P0      |
|Clean ui/view.py           |Remove `on_unread_messages`; remove inbox counter UI element                                              |P0      |
|Clean Ansible playbook     |Remove pwngrid download, install, keygen, service-enable tasks; keep `/etc/pwnagotchi/` mkdir             |P0      |
|Remove pycryptodome        |Comment out in requirements.in; defer pip-compile to Phase 2                                              |P0      |
|Removal verification tests |`tests/test_phase1_removal.py`: 6 negative-space assertions                                               |P0      |
|CHANGELOG.md entry         |Document removal rationale, what was removed, plugin API breaking changes                                 |P0      |
|Smoke test                 |Boot image; verify daemon starts, bettercap starts, display renders, no errors referencing pwngrid        |P0      |

### 3.9 Phase 1 Sequence

1. Write and commit the CHANGELOG.md entry. This forces clarity on scope before any code is touched.
1. Delete `grid.py`, `identity.py`, `plugins/default/grid.py`, `pwngrid-peer.service`.
1. Delete `pwnagotchi/mesh/`.
1. Clean `agent.py`: remove imports, `is_connected()` gating, `grid.call()` invocations, peer counter, `AsyncAdvertiser` from class definition.
1. Clean `automata.py`: remove `on_peer_detected` dispatch.
1. Clean `ui/view.py`: remove `on_unread_messages` and inbox UI element.
1. Clean Ansible playbook: remove all pwngrid tasks (keep `/etc/pwnagotchi/` mkdir).
1. Comment out `pycryptodome` in `requirements.in`.
1. Remove `[main.plugins.grid]` block from `defaults.toml`.
1. Write `tests/test_phase1_removal.py`. Run with `python -m pytest tests/test_phase1_removal.py -v`.
1. Build test image. Boot on RPi Zero 2 W. Verify clean startup. Tag **v1.9.0-beta**.
1. Community feedback period (1–2 weeks). Tag **v1.9.0-stable**.

-----

## 4. Claude Code Implementation Guidance

All three phases are intended to be executed using Claude Code. This section captures practical guidance for structuring those sessions.

### 4.1 General Principles

**One phase per Claude Code session (or sub-task).** Do not span multiple phases in one session. Each phase has a defined entry state, exit state, and verification step.

**Start every session by pointing Claude Code at this document.** Begin with: *“Read `CLAUDE.md` and `docs/DESIGN.md`. We are starting Phase [N], Section [X]. Do not make changes outside that scope.”*

**Verify before moving on.** Do not start Phase 2 until Phase 1’s smoke test passes. Do not start Phase 3 until Phase 2’s pytest baseline passes.

**Commit after each numbered step**, not at the end of a session. One step = one commit. This makes the git history reviewable and any single step reversible.

**Scope discipline.** If Claude Code finds something outside the current phase’s scope that needs fixing, it should note it but not fix it. Add a `# TODO(phase-N):` comment and move on.

### 4.2 Phase 1: Claude Code Session Plan

**Session goal:** Complete the full pwngrid and peer-advertising removal. Pure deletion and cleanup — no new code except the tests.

**Recommended prompt sequence:**

1. **Orientation:** *“Read `CLAUDE.md` and `docs/DESIGN.md` Section 3. Confirm you understand Phase 1 scope: which files are deleted outright, which files need call-site cleanup, and what the acceptance checklist in Section 3 requires.”*
1. **Deletions first:** *“Delete the following files exactly as listed in Section 3.4: `grid.py`, `identity.py`, `plugins/default/grid.py`, `pwngrid-peer.service`, and the entire `mesh/` directory. Do not edit any other files yet. Show me a summary of what you deleted.”*
1. **Import cleanup:** *“Now find and remove every import of `pwnagotchi.grid` and `pwnagotchi.identity` across the remaining codebase. Show me each removal before applying it.”*
1. **Call-site cleanup:** *“In `agent.py`, find and remove: all `grid.is_connected()` calls and the conditional blocks they gate, all `grid.call()` invocations, the `self._peers` counter and its update logic, and `AsyncAdvertiser` from the class inheritance list. Do not change anything else in `agent.py`.”*
1. **automata.py:** *“In `automata.py`, remove the `on_peer_detected` callback dispatch and any peer-related state. Show the diff before applying.”*
1. **ui/view.py:** *“Remove the `on_unread_messages` method and the UI element it controls from `ui/view.py`. Show the diff.”*
1. **Ansible cleanup:** *“In `builder/pwnagotchi.yml`, remove exactly these tasks: the pwngrid binary download, the `/usr/bin/` install, the `pwngrid -generate -keys /etc/pwnagotchi` keypair task, and the `pwngrid-peer.service` enable task. Do NOT remove the task that creates the `/etc/pwnagotchi/` directory — that directory is the primary application config directory used by `config.toml` and the log path, and must exist on the image.”*
1. **TOML cleanup:** *“Remove the `main.plugins.grid` configuration block from `defaults.toml`. Comment out the `pycryptodome` line in `requirements.in` and add a comment explaining it was removed with pwngrid.”*
1. **Removal tests:** *“Write `tests/test_phase1_removal.py` with the 6 negative-space tests specified in Section 3.7. Run them and confirm all pass.”*
1. **Checklist verification:** *“Run through the acceptance checklist in Section 3 of `CLAUDE.md`. For each item, confirm it passes or flag what still needs fixing.”*

**What to watch for:**

- Claude Code may find additional `grid` references not in the explicit list. It should surface these rather than silently deleting them — prompt: *“If you find any other references to pwngrid, grid, or identity outside the files already cleaned, list them and ask before removing.”*
- The `/etc/pwnagotchi/` directory creation task must be **preserved**. See Section 3.5.
- `on_peer_detected` may appear in documentation comments or example plugins. These are not call sites. Note them for the CHANGELOG but do not treat them as bugs.

### 4.3 Phase 2: Claude Code Session Plan

**Session goal:** Upgrade the cleaned codebase to Bookworm 32-bit, Python 3.11, Flask 3.x, and pyproject.toml. Break into sub-sessions.

**Recommended sub-sessions:**

1. **Sub-session A — Base image and pyproject.toml:** *“Update the Ansible base image URL to Raspberry Pi OS Bookworm Lite armhf. Then migrate `setup.py` to `pyproject.toml` using `hatchling`. Preserve all entry points and data file installs. Do not touch `requirements.in` yet.”*
1. **Sub-session B — Flask upgrade:** *“Upgrade Flask and its dependencies as specified in Section 5.4.1 of `DESIGN.md`. Audit `webcfg` plugin and any other plugin that uses `render_template_string` or `request.form` for Flask 3.x compatibility. Show me every change to plugin files before applying.”*
1. **Sub-session C — Python 3.11 compat:** *“Search the codebase for `datetime.utcnow()`, `pkg_resources` usage, and `collections` imports (not `collections.abc`). Fix each as specified in Section 5.2. Run `python -m py_compile` on every `.py` file under `pwnagotchi/`.”*
1. **Sub-session D — pip-compile:** *“Update `requirements.in` as specified: remove pycryptodome (already commented), update Flask stack versions. Then run `pip-compile --resolver=backtracking --strip-extras --prefer-binary` against Python 3.11 and commit the output as `requirements.txt`.”*
1. **Sub-session E — AI guard and tests:** *“Harden the AI fallback guard as described in Section 5.4.2. Then write `tests/test_config.py`, `tests/test_bettercap.py`, `tests/test_plugins.py`, and `tests/test_ai_guard.py` covering the 17 tests specified in Section 5.5.”*

**What to watch for:**

- Flask 3.x removed `flask.escape()` (use `markupsafe.escape()`) and `flask.Markup` (use `markupsafe.Markup`). Most likely impact point is the webcfg plugin.
- pyproject.toml with hatchling requires explicit declaration of data files. Map each `install_file()` call to `[tool.hatch.build.targets.wheel.shared-data]`.
- pip-compile must be run on a Bookworm 32-bit environment (QEMU or Docker). Do not run on a dev workstation.

### 4.4 Phase 3: Claude Code Session Plan

**Session goal:** Migrate to 64-bit OS, replace AI stack with SB3/PyTorch, update build pipeline for aarch64.

**Recommended sub-sessions:**

1. **Sub-session A — Build pipeline:** *“Update the Ansible base image to Bookworm 64-bit (aarch64). Change `GOARCH` to `arm64` for the bettercap build. Update nexmon to use `ARCH=arm64` and 64-bit kernel headers. Do not touch Python code yet.”*
1. **Sub-session B — gymnasium env adapter + tests:** *“Rewrite `pwnagotchi/ai/` gym.Env wrapper to the gymnasium 0.29 API. The observation space and action space dimensions are unchanged. Show me the method signature changes (step, reset) before rewriting. Then write `tests/test_gym_env.py` covering the 7 tests specified in Section 6.2.3, including the env_checker test.”*
1. **Sub-session C — SB3 integration + tests:** *“Update `ai/__init__.py` to import from `stable_baselines3` instead of `stable_baselines`. Update `requirements.in`: remove `tensorflow`, `stable-baselines`, `keras-*`, `tensorboard`, `gym`; add `torch>=2.1`, `stable-baselines3>=2.0`, `gymnasium>=0.29`. Then write `tests/test_sb3_integration.py` covering the 3 tests in Section 6.2.4.”*
1. **Sub-session D — pip-compile aarch64:** *“Run pip-compile against Python 3.11 aarch64 and commit the output as `requirements-aarch64.txt`.”*

**What to watch for:**

- stable-baselines3 uses a different model serialisation format. Do **not** attempt to write model migration code. The break is accepted; document it.
- The gymnasium `step()` method returns a 5-tuple. Grep for all `env.step(` call sites and update any that unpack a 4-tuple.
- The AI sub-session is the highest-risk session. After applying changes, run `tests/test_gym_env.py` before declaring the session complete.

### 4.5 Cross-Phase Guidance

**The checklist is the contract.** The Phase 1 acceptance checklist is in `CLAUDE.md`. For Phases 2 and 3, derive equivalent checklists from the deliverables tables before those sessions begin. Ask Claude Code to work through the checklist at the end of every session.

**The `--prefer-binary` flag is already in `requirements.in`.** Don’t remove it — it’s essential for getting piwheels binaries on armhf.

-----

## 5. Phase 2 — 32-bit Stabilisation

**Objective:** Bring the Phase 1–cleaned codebase to a clean, reproducible, well-tested state on the 32-bit armhf target (RPi Zero 2 W, Raspberry Pi OS Bookworm).

The codebase entering this phase is meaningfully smaller: no `grid.py`, no `identity.py`, no `mesh/`, no `pwngrid-peer.service`, no `pycryptodome`.

### 5.1 Base Image: Bookworm 32-bit

Update the builder base image URL to Raspberry Pi OS **Bookworm Lite 32-bit (armhf)**. Bookworm is the current stable Raspberry Pi OS release and ships Python 3.11 as the default interpreter. This also sets up a clean OS baseline for Phase 3 (which uses the 64-bit Bookworm variant).

### 5.2 Python Runtime: 3.7 → 3.11

The pip-compile header in the current `requirements.txt` says “python 3.7”. Re-running pip-compile against Bookworm Python 3.11 is required. Breaking changes to audit and fix:

|Breaking Change                          |Affected Code                           |Fix                                               |
|-----------------------------------------|----------------------------------------|--------------------------------------------------|
|distutils removed (3.12, deprecated 3.10)|`setup.py`                              |Migrate to pyproject.toml (Section 5.3)           |
|`datetime.utcnow()` deprecated           |Logging, timestamp comparisons          |Replace with `datetime.now(timezone.utc)`         |
|`importlib.resources` API (3.9+)         |Plugin loader path resolution           |Replace `pkg_resources` with `importlib.resources`|
|`collections.abc` move (3.10)            |Possible in plugins or transitive deps  |2to3 codemod + manual review                      |
|`asyncio.coroutine` removed (3.11)       |Not directly used; check transitive deps|Dep audit during pip-compile                      |

### 5.3 Migrate setup.py to pyproject.toml

Replace `setup.py` (which uses `distutils.util.strtobool`) with `pyproject.toml` using the `hatchling` build backend.

- **Keep:** all package metadata, entry points, data file installation (config files, systemd units, caplets)
- **Replace:** the `install_file()` custom install logic with `[tool.hatch.build.targets.wheel.shared-data]` declarations
- **Add:** `requires-python = ">=3.9"`; optional dep groups `[ai]` and `[display]`
- **Keep:** `requirements.in` / `requirements.txt` as the lock files for the image build. pyproject.toml dependency metadata is kept deliberately loose; the lock files control actual installed versions.

### 5.4 Dependency Cleanup

#### 5.4.1 Flask 1.x → 3.x

The Flask 1.x + `MarkupSafe < 2.1.0` conflict-prevention hack is the highest-priority dependency fix after the Python upgrade. Flask 1.x is EOL with published CVEs.

|Package       |Current                        |Phase 2 Target|Notes                                            |
|--------------|-------------------------------|--------------|-------------------------------------------------|
|`flask`       |`~= 1.0`                       |`>= 3.0, < 4` |Audit webcfg plugin for API changes              |
|`flask-cors`  |`~= 3.0`                       |`>= 4.0`      |Aligns with Flask 3.x                            |
|`flask-wtf`   |`~= 1.0`                       |`>= 1.2`      |Review CSRF token usage                          |
|`MarkupSafe`  |`< 2.1.0` (hack)               |Remove cap    |No longer needed with Flask 3.x                  |
|`itsdangerous`|`~= 1.1.0` (misleading comment)|`>= 2.1`      |Fix the requirements.txt comment inconsistency   |
|`werkzeug`    |`~= 1.0.1`                     |`>= 3.0`      |Required by Flask 3.x                            |
|`jinja2`      |`~= 2.11.3`                    |`>= 3.1`      |Required by Flask 3.x                            |
|`pycryptodome`|`~= 3.9`                       |Removed       |Dropped in Phase 1; finalised here in pip-compile|

The `webcfg` plugin and any plugin using `render_template_string`, `csrf_token()`, or `request.form` must be tested against Flask 3.x. Key API removals: `flask.escape()` → `markupsafe.escape()`; `flask.Markup` → `markupsafe.Markup`.

#### 5.4.2 AI Stack: Retain with Hardened Guard

TF1.x + stable-baselines 2.x + gym < 0.22 are retained unchanged. The `requirements.in` comment is explicit: SB3/PyTorch requires a 64-bit processor — that is Phase 3.

Harden the AI fallback guard:

1. Log a `WARNING` with the specific import error when TF is unavailable
1. Set a module-level `AI_AVAILABLE = False` flag in `pwnagotchi/ai/__init__.py`
1. In `agent.py`, check `AI_AVAILABLE` before entering AI mode; fall back to `MANU` cleanly
1. Add a small UI indicator so the operator knows AI is inactive

#### 5.4.3 Regenerate requirements.txt

Re-run pip-compile against Bookworm Python 3.11. The `--prefer-binary` flag is already in `requirements.in`. `pycryptodome` is now absent. Commit the new `requirements.txt`.

> pip-compile must be run inside a Bookworm 32-bit QEMU or Docker environment to produce correct armhf/piwheels-compatible output. Do not run on an x86 dev machine.

### 5.5 Test Suite

Add a `tests/` directory at the repo root with a `pytest` harness. All tests must be runnable without hardware (no physical display, no bettercap process, no WiFi interface). All hardware interactions are mocked.

#### 5.5.1 Config Tests (`tests/test_config.py`)

Tests for `pwnagotchi/fs/__init__.py` and the config merge logic.

1. `test_load_valid_toml` — load a minimal valid `config.toml`; assert `main.name` is present and has expected type
1. `test_defaults_are_applied` — load empty user config; assert values from `defaults.toml` appear in merged result
1. `test_user_values_override_defaults` — user config value wins over default
1. `test_yaml_migration` — legacy `.yaml` config parses without error and matches equivalent `.toml` merge
1. `test_missing_required_key_raises` — accessing a key with no default raises expected exception, not silent `KeyError`
1. `test_no_grid_keys_in_defaults` — assert `main.plugins.grid` does not appear anywhere in `defaults.toml` *(Phase 1 regression guard)*

#### 5.5.2 bettercap Client Tests (`tests/test_bettercap.py`)

Using `responses` library for HTTP mocking and `pytest-asyncio` for websocket mocking.

1. `test_session_get_success` — mock `GET /api/session` 200; assert client parses and returns session dict
1. `test_http_timeout_raises` — mock connection timeout; assert client raises within configured timeout window
1. `test_http_retry_on_failure` — mock two 500s then a 200; assert client retries and returns success
1. `test_websocket_reconnect_on_close` — mock websocket close event; assert reconnection is attempted
1. `test_websocket_reconnect_on_error` — mock websocket error event; assert reconnection is attempted
1. `test_no_grid_module_imported` — import `pwnagotchi.bettercap`; assert `'pwnagotchi.grid'` not in `sys.modules` *(Phase 1 regression guard)*

#### 5.5.3 Plugin Loader Tests (`tests/test_plugins.py`)

1. `test_load_valid_plugin` — minimal in-memory plugin with `__author__`, `__version__`, `on_loaded`; loads without error
1. `test_plugin_on_loaded_called` — `on_loaded` fires exactly once after load
1. `test_bad_plugin_does_not_crash_loader` — plugin whose `__init__` raises; loader catches, logs, continues
1. `test_enable_disable_lifecycle` — load, disable, re-enable; callbacks fire in order
1. `test_unknown_callback_is_ignored` — dispatch unknown callback name; no exception
1. `test_on_peer_detected_not_registered` — `on_peer_detected` not in loader’s known callback registry *(Phase 1 regression guard)*

#### 5.5.4 AI Guard Tests (`tests/test_ai_guard.py`)

1. `test_ai_available_false_when_tf_missing` — patch `sys.modules` so TF import raises `ImportError`; assert `pwnagotchi.ai.AI_AVAILABLE is False`
1. `test_ai_warning_logged_when_tf_missing` — same setup; assert `WARNING` with import error message is emitted
1. `test_agent_starts_in_manu_when_ai_unavailable` — construct agent with `AI_AVAILABLE = False` and mock config; assert initial mode is `MANU`
1. `test_ai_available_true_when_tf_present` — patch TF as importable stub; assert `AI_AVAILABLE is True` *(auto-skip if TF not installed)*

### 5.6 Linting and Formatting

Add `ruff` as the single linter and formatter. Commit `ruff.toml` and `.pre-commit-config.yaml`. Apply formatting as a **separate cosmetic commit** from any functional change so blame history stays readable.

### 5.7 USB Networking

Replace `/etc/network/interfaces.d/usb0` with a NetworkManager `.nmconnection` profile for the USB gadget interface. Bookworm defaults to NetworkManager; the legacy `ifupdown` approach conflicts with it.

### 5.8 Phase 2 Deliverables

|Deliverable                   |Description                                                              |Priority|
|------------------------------|-------------------------------------------------------------------------|--------|
|Base image: Bookworm 32-bit   |Update builder to Raspberry Pi OS Bookworm Lite armhf                    |P0      |
|pyproject.toml                |Replace setup.py; hatchling backend                                      |P0      |
|requirements.txt (Python 3.11)|pip-compile against Bookworm/3.11; pycryptodome absent                   |P0      |
|Flask 3.x upgrade             |Flask + Werkzeug + Jinja2 + flask-cors + flask-wtf; remove MarkupSafe cap|P0      |
|Python 3.11 compat pass       |datetime, importlib.resources, collections.abc fixes                     |P0      |
|AI fallback hardening         |AI_AVAILABLE flag; clean MANU fallback; UI indicator                     |P0      |
|ruff + pre-commit             |Linter and formatter baseline                                            |P1      |
|pytest suite (4 modules)      |test_config, test_bettercap, test_plugins, test_ai_guard — 17 tests      |P1      |
|USB: NetworkManager profile   |Replace /etc/network/interfaces.d/usb0                                   |P1      |
|CHANGELOG.md                  |Document all Phase 2 changes                                             |P1      |
|CI: pytest in GitHub Action   |Run test suite on push                                                   |P2      |

-----

## 6. Phase 3 — 64-bit Migration

**Objective:** Migrate the Phase 2–stabilised codebase to a 64-bit (aarch64) target on the same RPi Zero 2 W hardware, running Raspberry Pi OS Bookworm 64-bit. Replace TF1.x/SB2 with PyTorch/SB3.

The `requirements.in` comment is the explicit statement: *“Upgrading to stable-baselines3 is currently impossible because it depends on PyTorch which requires a 64-bit processor.”* Phase 3 resolves this.

### 6.1 Architecture Comparison

|Attribute        |Phase 2 (32-bit)                    |Phase 3 (64-bit)                       |
|-----------------|------------------------------------|---------------------------------------|
|Architecture     |armv7l / armhf                      |aarch64 / arm64                        |
|OS               |Raspberry Pi OS Bookworm Lite 32-bit|Raspberry Pi OS Bookworm Lite 64-bit   |
|Python           |3.11                                |3.11 (unchanged)                       |
|TensorFlow       |1.x (guarded)                       |Removed                                |
|stable-baselines |2.x (guarded)                       |Removed                                |
|stable-baselines3|—                                   |>= 2.0                                 |
|PyTorch          |—                                   |>= 2.1 (aarch64 PyPI wheels)           |
|gymnasium        |gym < 0.22                          |gymnasium >= 0.29                      |
|pwngrid          |Removed in Phase 1                  |Remains removed                        |
|bettercap        |Source-built (Go 1.22.4)            |Source-built (Go 1.22.4+, GOARCH=arm64)|
|nexmon           |Source-built (arm)                  |Source-built (arm64 kernel headers)    |

### 6.2 AI Stack Migration

#### 6.2.1 New Stack

Remove from `requirements.in`: `tensorflow`, `stable-baselines`, `keras-applications`, `keras-preprocessing`, `tensorboard`, `gym`.

Add: `torch >= 2.1`, `stable-baselines3 >= 2.0`, `gymnasium >= 0.29`.

#### 6.2.2 gymnasium API Differences

|Method   |gym 0.14–0.21 (current)            |gymnasium 0.29+ (Phase 3)                           |
|---------|-----------------------------------|----------------------------------------------------|
|`step()` |Returns `(obs, reward, done, info)`|Returns `(obs, reward, terminated, truncated, info)`|
|`reset()`|Returns `obs`                      |Returns `(obs, info)`                               |
|Namespace|`import gym`                       |`import gymnasium as gym`                           |

Rewrite `pwnagotchi/ai/` gym.Env wrapper to the gymnasium API. The observation space and action space dimensions are **unchanged**; only method signatures change. Grep for all `env.step(` call sites and update any that unpack a 4-tuple.

#### 6.2.3 gymnasium Env Tests (`tests/test_gym_env.py`)

Using mock bettercap state dict; no hardware required.

1. `test_reset_returns_two_tuple` — `env.reset()` returns `(obs, info)`, not a bare array
1. `test_reset_obs_matches_observation_space` — `observation_space.contains(obs)` is `True` after reset
1. `test_step_returns_five_tuple` — `env.step(action)` unpacks to exactly 5 elements
1. `test_step_terminated_and_truncated_are_bools` — both `terminated` and `truncated` are `bool`, not a single `done`
1. `test_step_obs_within_bounds` — `observation_space.contains(obs)` is `True` after step with random valid action
1. `test_valid_actions_accepted` — all values in `action_space` accepted by `env.step()` without raising
1. `test_gymnasium_env_checker` — `gymnasium.utils.env_checker.check_env(env)` raises no warnings or errors

#### 6.2.4 SB3 Integration Tests (`tests/test_sb3_integration.py`)

Mark all with `@pytest.mark.slow`. Excluded from fast CI run; run in nightly or pre-release CI.

1. `test_a2c_instantiates` — `stable_baselines3.A2C('MlpPolicy', env)` raises no exception
1. `test_a2c_learn_one_step` — `model.learn(total_timesteps=1)` completes without error
1. `test_model_save_load_roundtrip` — save to temp file; load back; loaded model’s policy network has same architecture

#### 6.2.5 Model File Incompatibility

TF1.x stable-baselines 2.x model files (`.pkl`) cannot be loaded by stable-baselines3. **Accept the break and re-train from scratch** on Phase 3 images. Do not write migration code. Document clearly in CHANGELOG.md.

### 6.3 Build Pipeline Changes

- **bettercap:** Change `GOARCH=arm` to `GOARCH=arm64` in the Ansible Go build task. No source changes.
- **nexmon:** Set `ARCH=arm64` and install 64-bit kernel headers. Same chip firmware patches (BCM43436b0, BCM43430a1, BCM43455c0); only the build target changes.
- **pwngrid:** Already removed in Phase 1. No action needed.
- **requirements:** Run pip-compile against aarch64 Python 3.11. Commit as `requirements-aarch64.txt`.

### 6.4 Phase 3 Deliverables

|Deliverable                  |Description                                                  |Priority|
|-----------------------------|-------------------------------------------------------------|--------|
|Base image: Bookworm 64-bit  |Update builder to Raspberry Pi OS Bookworm Lite aarch64      |P0      |
|gymnasium env adapter        |Rewrite gym.Env to gymnasium 0.29 API                        |P0      |
|gymnasium env tests          |tests/test_gym_env.py: 7 contract tests including env_checker|P0      |
|stable-baselines3 integration|Replace SB2/TF1 with SB3/PyTorch                             |P0      |
|SB3 integration tests        |tests/test_sb3_integration.py: 3 slow tests                  |P0      |
|requirements-aarch64.txt     |pip-compile for Python 3.11 aarch64                          |P0      |
|nexmon: arm64 build          |ARCH=arm64 + 64-bit kernel headers in Ansible                |P0      |
|bettercap: GOARCH=arm64      |Single env-var change in Ansible Go build task               |P0      |
|Model break documentation    |CHANGELOG entry + migration guide                            |P0      |
|CI: QEMU arm64 smoke test    |GitHub Action with QEMU aarch64 runner                       |P1      |
|Performance benchmarks       |AI load time and epoch time on Zero 2 W 64-bit vs 32-bit     |P1      |

-----

## 7. What is Explicitly Out of Scope

|Out of Scope Item                                          |Rationale                                                               |
|-----------------------------------------------------------|------------------------------------------------------------------------|
|Reintroducing peer-advertising without pwngrid             |Feature addition; if desired, scope and design separately post-Phase 3  |
|Support for original RPi Zero W                            |Fork author explicitly dropped it; ARMv6 only; TF1 wheel problem returns|
|Replacing bettercap                                        |External binary; changes require a separate project                     |
|Changing the config.toml schema (beyond removing grid keys)|Would break existing user config files                                  |
|New display types or display API                           |Add via plugin system post-Phase 3                                      |
|Replacing the plugin system                                |Backward compatibility is a hard constraint                             |
|Async framework migration (asyncio)                        |Large surface area; defer post-Phase 3                                  |
|Containerisation (Docker/OCI)                              |Embedded target; containers add complexity without benefit              |
|Switching RL algorithm from A2C                            |SB3 includes A2C natively; same algorithm, new framework                |
|Removing the Mastodon/UPS/aircrack plugins                 |Fork-specific additions; carry forward unchanged                        |

-----

## 8. Risk Register

|Risk                                                                               |Likelihood|Impact|Mitigation                                                                                                  |
|-----------------------------------------------------------------------------------|----------|------|------------------------------------------------------------------------------------------------------------|
|`on_peer_detected` removal breaks a widely-used third-party plugin                 |Low       |Medium|Publish Phase 1 as named beta; give community 2+ weeks to report; document in CHANGELOG prominently         |
|`api.pwnagotchi.ai` is still reachable and used by some community members          |Low       |Low   |Confirm DNS/connectivity before cutting code; removal rationale is still sound (pwngrid binary unmaintained)|
|agent.py cleanup introduces a regression in state machine behaviour                |Medium    |Medium|Phase 1 tests catch import-level issues; Phase 2 pytest baseline catches regressions going forward          |
|Flask 3.x upgrade breaks webcfg plugin or third-party plugins using Flask internals|Medium    |Medium|Audit webcfg and all default plugins against Flask 3.x before tagging Phase 2 stable                        |
|nexmon arm64 build fails on new Bookworm kernel version                            |Medium    |High  |Pin kernel version in builder; track nexmon issue tracker; fork already has nexmon source-build experience  |
|PyTorch memory pressure on 512 MB Zero 2 W                                         |Low       |High  |Community forks confirm PyTorch works on Zero 2 W; monitor swap usage; SB3 A2C is relatively lightweight    |
|pip-compile on Bookworm 3.11 produces dep set incompatible with piwheels           |Medium    |Medium|Run pip-compile inside a Bookworm 32-bit QEMU environment; `--prefer-binary` already in requirements.in     |

-----

## 9. Implementation Sequence

### Phase 1: pwngrid & Peer-Advertising Removal

1. Confirm `api.pwnagotchi.ai` is defunct. Write CHANGELOG.md entry.
1. Delete: `grid.py`, `identity.py`, `plugins/default/grid.py`, `pwngrid-peer.service`, `pwnagotchi/mesh/`.
1. Clean `agent.py`, `automata.py`, `ui/view.py`, `defaults.toml`, Ansible playbook.
1. Comment out `pycryptodome` in `requirements.in`.
1. Write `tests/test_phase1_removal.py`. Run with `python -m pytest`.
1. Build image. Boot. Verify clean startup. Tag **v1.9.0-beta**. Community test (1–2 weeks). Tag **v1.9.0-stable**.

### Phase 2: 32-bit Stabilisation

1. Update builder base image to Raspberry Pi OS Bookworm Lite 32-bit.
1. Migrate `setup.py` to `pyproject.toml`.
1. Upgrade Flask stack (3.x); remove MarkupSafe cap and fix itsdangerous comment.
1. Apply Python 3.7→3.11 compat fixes.
1. Re-run pip-compile (Python 3.11, Bookworm). Commit `requirements.txt`.
1. Harden AI fallback guard.
1. Add ruff + pre-commit. Write `tests/test_config.py`, `test_bettercap.py`, `test_plugins.py`, `test_ai_guard.py` (17 tests total). All must pass.
1. Migrate USB networking to NetworkManager profile.
1. Tag **v2.0.0-beta**. Community test (2–4 weeks). Tag **v2.0.0-stable**.

### Phase 3: 64-bit Migration

1. Update builder base image to Raspberry Pi OS Bookworm Lite 64-bit (aarch64). Update nexmon to arm64.
1. Update bettercap Go build task: `GOARCH=arm64`.
1. Boot test image on RPi Zero 2 W 64-bit. Verify bettercap, nexmon, display, plugins.
1. Rewrite gymnasium env adapter. Write `tests/test_gym_env.py` (7 tests). Run env_checker. All must pass.
1. Integrate SB3 + PyTorch. Write `tests/test_sb3_integration.py` (3 slow tests). Run on aarch64.
1. Update `requirements.in`. Run pip-compile (aarch64). Commit `requirements-aarch64.txt`.
1. Add QEMU arm64 CI job.
1. Tag **v3.0.0-beta**. Community test. Tag **v3.0.0-stable**.

-----

## 10. Appendix

### A. Phase 1 Acceptance Checklist

|# |Item                                                                   |Verification                                                                     |
|--|-----------------------------------------------------------------------|---------------------------------------------------------------------------------|
|1 |`pwnagotchi/grid.py` deleted                                           |`grep -r "import.*grid" pwnagotchi/` returns nothing                             |
|2 |`pwnagotchi/identity.py` deleted                                       |`grep -r "import.*identity" pwnagotchi/` returns nothing                         |
|3 |`pwnagotchi/mesh/` directory deleted                                   |Directory absent                                                                 |
|4 |`pwnagotchi/plugins/default/grid.py` deleted                           |git status shows deletion                                                        |
|5 |`pwngrid-peer.service` deleted                                         |git status shows deletion                                                        |
|6 |`agent.py`: no grid.* or identity.* references; AsyncAdvertiser removed|`grep -r "grid|identity" pwnagotchi/agent.py` returns nothing                    |
|7 |`automata.py`: no `on_peer_detected` dispatch                          |`grep -r "on_peer_detected" pwnagotchi/` returns nothing (or comment only)       |
|8 |`ui/view.py`: no `on_unread_messages`                                  |`grep -r "on_unread_messages" pwnagotchi/` returns nothing                       |
|9 |`defaults.toml`: no `[main.plugins.grid]` block                        |`grep -r "plugins.grid"` returns nothing                                         |
|10|`builder/pwnagotchi.yml`: no pwngrid tasks                             |`grep -i "pwngrid" builder/` returns nothing                                     |
|11|`builder/pwnagotchi.yml`: `/etc/pwnagotchi/` mkdir task still present  |`grep "pwnagotchi" builder/pwnagotchi.yml` shows mkdir task                      |
|12|`pycryptodome` commented out in `requirements.in`                      |Not present in pip-compiled output (Phase 2 verification)                        |
|13|All 6 tests in `tests/test_phase1_removal.py` pass                     |`python -m pytest tests/test_phase1_removal.py -v`                               |
|14|Image boots without error                                              |`journalctl -u pwnagotchi` shows no errors referencing pwngrid, grid, or identity|
|15|Display renders correctly                                              |No inbox counter UI element visible; face renders normally                       |
|16|bettercap starts and WiFi scanning works                               |Handshake capture functional in AUTO mode                                        |

### B. Dependency Version Summary (All Phases)

|Package          |Current Fork            |Phase 1      |Phase 2 (32-bit)     |Phase 3 (64-bit)|
|-----------------|------------------------|-------------|---------------------|----------------|
|Python           |3.7 (pip-compile target)|Unchanged    |3.11                 |3.11            |
|OS               |Bullseye 32-bit         |Unchanged    |Bookworm 32-bit      |Bookworm 64-bit |
|pycryptodome     |~= 3.9                  |Commented out|Removed (pip-compile)|Removed         |
|tensorflow       |>= 1.8, < 1.14          |Unchanged    |Guarded              |Removed         |
|stable-baselines |~= 2.7                  |Unchanged    |Guarded              |Removed         |
|stable-baselines3|—                       |—            |—                    |>= 2.0          |
|torch (PyTorch)  |—                       |—            |—                    |>= 2.1          |
|gym              |~= 0.14, < 0.22         |Unchanged    |Unchanged            |Removed         |
|gymnasium        |—                       |—            |—                    |>= 0.29         |
|flask            |~= 1.0                  |Unchanged    |>= 3.0, < 4          |>= 3.0, < 4     |
|MarkupSafe       |< 2.1.0 (hack)          |Unchanged    |Cap removed          |Cap removed     |
|pwngrid binary   |armhf binary (unused)   |Removed      |Removed              |Removed         |
|grid.py          |Present                 |Deleted      |Absent               |Absent          |
|identity.py      |Present                 |Deleted      |Absent               |Absent          |
|mesh/            |Present                 |Deleted      |Absent               |Absent          |
|bettercap        |Source (Go 1.22.4)      |Unchanged    |Unchanged            |GOARCH=arm64    |

### C. Glossary

|Term      |Definition                                                                          |
|----------|------------------------------------------------------------------------------------|
|A2C       |Advantage Actor-Critic — the reinforcement learning algorithm used by pwnagotchi    |
|aarch64   |64-bit ARM architecture (Cortex-A class); target for Phase 3                        |
|armhf     |32-bit ARM with hardware floating-point; target for Phases 1 and 2                  |
|armv7l    |Specific 32-bit ARM ISA used by BCM2710A1 (Zero 2 W); distinct from armv6l (Zero W) |
|ARCHFLAG  |Ansible variable set to armv7l in the fork to ensure correct compiler target        |
|bettercap |Open-source WiFi monitoring framework; provides the WiFi engine via REST + WebSocket|
|BCM43436b0|Broadcom WiFi chip in the RPi Zero 2 W (newer revision)                             |
|BCM43430a1|Broadcom WiFi chip in some RPi Zero 2 W units (older revision)                      |
|gymnasium |Maintained fork of OpenAI Gym; standard RL environment interface for Phase 3        |
|nexmon    |Firmware patch framework enabling monitor-mode and injection on Broadcom WiFi chips |
|PCAP      |Packet capture file format for captured WPA handshakes                              |
|PMKID     |Pairwise Master Key Identifier — a clientless handshake capture method              |
|pwngrid   |Removed Go binary; was the peer-to-peer mesh and cloud enrollment service           |
|SB2 / SB3 |stable-baselines (TF1-based) and stable-baselines3 (PyTorch-based)                  |
|port 8666 |The local HTTP port on which pwngrid-peer ran; no longer present after Phase 1      |
