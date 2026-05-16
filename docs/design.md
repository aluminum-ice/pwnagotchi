# Pwnagotchi Modernisation Design Document

**Phase 1 — pwngrid & Peer-Advertising Removal · Phase 1.5 — Dead Code Sweep · Phase 2 — 32-bit Stabilisation · Phase 3 — 64-bit Migration**

|                  |                                        |
|------------------|----------------------------------------|
|**Status**        |DRAFT                                   |
|**Version**       |0.4                                     |
|**Date**          |May 2026                                |
|**Reference Repo**|aluminum-ice/pwnagotchi (latest: v1.8.5)|
|**Upstream Repo** |evilsocket/pwnagotchi (v1.5.3, archived)|

-----

## Table of Contents

1. [Executive Summary](#1-executive-summary)
1. [Current State Analysis](#2-current-state-analysis)
1. [Phase 1 — pwngrid & Peer-Advertising Removal](#3-phase-1--pwngrid--peer-advertising-removal)
1. [Phase 1.5 — Dead Code Sweep](#4-phase-15--dead-code-sweep)
1. [Claude Code Implementation Guidance](#5-claude-code-implementation-guidance)
1. [Phase 2 — 32-bit Stabilisation](#6-phase-2--32-bit-stabilisation)
1. [Phase 3 — 64-bit Migration](#7-phase-3--64-bit-migration)
1. [What is Explicitly Out of Scope](#8-what-is-explicitly-out-of-scope)
1. [Risk Register](#9-risk-register)
1. [Implementation Sequence](#10-implementation-sequence)
1. [Appendix](#11-appendix)

-----

## 1. Executive Summary

**Reference codebase:** This document targets the **aluminum-ice/pwnagotchi** fork (latest release v1.8.5, February 2024), not the archived evilsocket/pwnagotchi original.

This document describes a three-phase modernisation plan. A new Phase 1 has been inserted ahead of the previously described stabilisation and migration work, dedicated entirely to the removal of pwngrid. This change was motivated by two facts: the evilsocket/pwngrid project is unmaintained and the api.pwnagotchi.ai cloud service it connects to is defunct; and the pwngrid binary is the only pre-compiled external binary in the image that cannot be replaced by a source build or dropped in favour of a PyPI package. Removing it cleanly before doing anything else produces a smaller, better-defined codebase for all subsequent phases.

The four phases are:

- **Phase 1 — pwngrid & Peer-Advertising Removal:** Remove the pwngrid binary, the pwngrid-peer systemd service, the identity/grid Python modules, the grid default plugin, `pwnagotchi/mesh/` (the dot11 peer-advertising layer), the `on_peer_detected` plugin callback, and all related Ansible tasks and config.toml keys. *(Complete — merged as PR #139.)*
- **Phase 1.5 — Dead Code Sweep:** Remove dead code left behind by Phase 1 but intentionally deferred from it: orphaned `voice.py` methods and i18n strings, dead `friend_face`/`friend_name` layout entries in ~30 `ui/hw/` modules, and the now-unreachable `set_grateful`/`_has_support_network_for` mood logic in `automata.py`.
- **Phase 2 — 32-bit Stabilisation:** Upgrade base image to Bookworm 32-bit, Python 3.11, Flask 3.x, pyproject.toml, test infrastructure, NetworkManager networking.
- **Phase 3 — 64-bit Migration:** Migrate to Bookworm 64-bit, replace TF1/SB2 with PyTorch/SB3, aarch64 image.

> **Design Principle — Minimal footprint:** Change only what must change. The plugin callback API (except `on_peer_detected` and `on_peer_lost`, both removed in Phase 1), the TOML configuration schema, and the bettercap REST interface are stable across all phases.

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

### 3.1 Pre-condition: Confirm Removal Rationale

The following was confirmed before cutting any code (documented in CHANGELOG.md):

- **`evilsocket/pwngrid`**: unmaintained — last commit January 2024; no releases since 2021.
- **Port 8666** (`pwngrid-peer`): not functional in the current image; a prior PR comment in the fork confirms it is not accessible.
- **`api.pwnagotchi.ai` DNS**: resolves to `172.67.162.248` (a Cloudflare proxy address) — **contrary to the original design doc assumption that DNS would fail**. A parked/proxied domain resolving does not make the cloud API functional. The removal rationale rests on the unmaintained upstream and the non-functional `pwngrid-peer` port, not on a DNS failure. The design doc pre-condition requiring DNS to be unreachable was incorrect; the actual confirmation basis is the two points above.
- **`on_peer_lost`**: discovered during Phase 1 implementation to be an equally-dead parallel callback to `on_peer_detected` — its dispatch also lived in the deleted `mesh/utils.py`. It was removed alongside `on_peer_detected` and is documented as a breaking change in CHANGELOG.md.

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

> **Plugin API Breaking Changes:** `on_peer_detected` and `on_peer_lost` are both removed from the plugin callback API. Any third-party plugin implementing either callback will load without error but the callbacks will never fire — peer detection no longer exists. Document prominently in CHANGELOG.md. The peers counter and friend face are removed from the display face.

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

*Phase 1 is complete — merged as PR #139.*

|Deliverable                                                          |Description                                                                                             |Status                                   |
|---------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|-----------------------------------------|
|Delete grid.py, identity.py, mesh/, grid plugin, pwngrid-peer.service|Files deleted outright                                                                                  |✅ Done                                   |
|Clean agent.py                                                       |AsyncAdvertiser removed; peer counter, start_advertising, _update_advertisement removed                 |✅ Done                                   |
|Clean bin/pwnagotchi                                                 |KeyPair and grid imports removed; both internet_available blocks removed                                |✅ Done                                   |
|Clean handler.py                                                     |7 inbox routes and pwnagotchi.grid import removed                                                       |✅ Done                                   |
|Clean automata.py                                                    |_peers state removed; _has_support_network_for returns False                                            |✅ Done                                   |
|Clean ui/view.py                                                     |on_unread_messages, on_new_peer, on_lost_peer, set_closest_peer, friend_face/friend_name removed        |✅ Done                                   |
|Clean log.py + voice.py                                              |LastSession Peer import and peer summary removed; “Met N peers” voice string removed                    |✅ Done                                   |
|Clean default plugins                                                |on_peer_detected and on_peer_lost removed from example.py, led.py, ntfy.py, switcher.py                 |✅ Done                                   |
|Clean Ansible playbook                                               |pwngrid download/install task and pwngrid-peer.service enable entry removed; /etc/pwnagotchi/ mkdir kept|✅ Done                                   |
|pwnagotchi.service                                                   |After=pwngrid-peer.service ordering directive removed                                                   |✅ Done                                   |
|defaults.toml                                                        |main.plugins.grid block removed                                                                         |✅ Done                                   |
|requirements.in                                                      |pycryptodome commented out                                                                              |✅ Done                                   |
|wifi.py relocated                                                    |mesh/wifi.py (channel math) moved to pwnagotchi/wifi.py; 4 import sites updated                         |✅ Done (fix for wholesale mesh/ deletion)|
|tests/test_phase1_removal.py                                         |8 negative-space tests (6 specified + 2 mesh-relocation guards)                                         |✅ Done                                   |
|CHANGELOG.md                                                         |Full removal documentation including DNS finding and on_peer_lost                                       |✅ Done                                   |

### 3.9 Known Follow-ups from Phase 1

The following items were discovered during Phase 1 implementation and intentionally deferred. They are addressed in Phase 1.5:

- `pwnagotchi/voice.py` retains now-orphaned `on_unread_messages`, `on_new_peer`, `on_lost_peer` methods and the “Met N peers” / “Met 1 peer” `.po`/`.pot` i18n catalogue entries
- ~30 `pwnagotchi/ui/hw/*.py` layout modules still define `friend_face`/`friend_name` position keys — dead entries no longer read by `View`
- `automata.py`: `_has_support_network_for()` now returns `False` unconditionally, and all `set_grateful()` call sites in `set_lonely`, `set_bored`, `set_sad`, `set_angry`, and `next_epoch()` are therefore unreachable — the entire `grateful` mood concept is dead code

-----

## 4. Phase 1.5 — Dead Code Sweep

**Objective:** Remove the dead code left behind by Phase 1 but explicitly deferred from it: orphaned `voice.py` methods and i18n strings, dead layout dict entries in `ui/hw/` modules, and the unreachable `grateful` mood logic in `automata.py`. No functional behaviour changes; no dependency changes; no test infrastructure changes.

**Entry condition:** Phase 1 (PR #139) merged to master.

**Why a separate phase and not part of Phase 1:** Phase 1 was a feature removal. These items are dead-code cleanup — lower risk, entirely cosmetic in effect, and touching different files. Keeping them separate preserves the Phase 1 git history as a clean, reviewable feature removal, and isolates any unexpected breakage to this phase.

**Why before Phase 2:** The `voice.py` i18n methods and `ui/hw/` layout keys will otherwise be carried into the Python 3.11 compat pass, adding noise to a much larger diff. The `automata.py` grateful logic is unreachable dead code — carrying it into Phase 2 increases the surface area Claude Code must reason about when auditing the state machine.

**Scope boundary:** Do not touch `requirements.in`, `setup.py`, the Ansible playbook, the AI stack, or any test file other than updating `tests/test_phase1_removal.py` with new regression guards. One concern per commit.

-----

### 4.1 Sub-task A — voice.py orphaned methods and i18n strings

**What:** `pwnagotchi/voice.py` contains three methods whose only callers were removed in Phase 1:

- `on_unread_messages(n)` — called by the removed `View.on_unread_messages()`
- `on_new_peer(peer)` — called by the removed `View.on_new_peer()`
- `on_lost_peer(peer)` — called by the removed `View.on_lost_peer()`

The `.po`/`.pot` locale catalogues contain now-unused strings for these methods and for the removed “Met N peers” / “Met 1 peer” last-session summary. These entries are harmless but cause `make langs` to compile dead strings into every `.mo` file.

**What to do:**

1. Delete the three methods from `voice.py`. Verify no other caller exists first: `grep -r "voice.*on_unread\|voice.*on_new_peer\|voice.*on_lost_peer" pwnagotchi/`
1. Run `scripts/language.sh update <lang>` for each language directory to regenerate `.pot` and merge into each `.po`, which will mark the removed strings as obsolete
1. Run `make langs` to recompile all `.mo` files
1. Commit voice.py change and i18n update as a single commit

**Claude Code prompt:**

> *“Read `docs/DESIGN.md` Section 4.1. In `pwnagotchi/voice.py`, first run `grep -r "on_unread_messages\|on_new_peer\|on_lost_peer" pwnagotchi/` to confirm the only definitions are in voice.py and there are no remaining callers. Then delete those three methods. Do not touch any other method in voice.py. Show me the diff before applying it.”*
> 
> *“Now run `scripts/language.sh update <lang>` for every language subdirectory under `pwnagotchi/locale/`, then run `make langs`. Show me which strings were marked obsolete. Commit the voice.py deletion and the updated locale files together in a single commit with message: `Phase 1.5: remove orphaned peer/inbox voice methods and stale i18n strings`.”*

**Acceptance:** `grep -r "on_unread_messages\|on_new_peer\|on_lost_peer" pwnagotchi/voice.py` returns nothing. `make langs` exits 0 with no errors.

-----

### 4.2 Sub-task B — ui/hw/ dead layout entries

**What:** Approximately 30 hardware layout modules under `pwnagotchi/ui/hw/` define `friend_face` and `friend_name` position keys in their `layout()` dict. `View` no longer reads these keys — `set_closest_peer()` and the `friend_face`/`friend_name` state elements were removed in Phase 1. The entries are dead but will appear in every layout dict when contributors add new display support, causing confusion.

**What to do:**

1. Find all affected files: `grep -rl "friend_face\|friend_name" pwnagotchi/ui/hw/`
1. In each file, remove the `friend_face` and `friend_name` keys from the layout dict returned by `layout()`. Remove only those two keys; do not touch any other layout entry.
1. Do not change the method signature, the class structure, or any other key.
1. Commit as a single commit covering all `ui/hw/` files.

**Claude Code prompt:**

> *“Read `docs/DESIGN.md` Section 4.2. Run `grep -rl 'friend_face\|friend_name' pwnagotchi/ui/hw/` to get the list of affected hardware layout files. For each file in that list, remove the `friend_face` and `friend_name` keys from the dict returned by the `layout()` method. Touch nothing else in those files — not the class, not other layout keys, not imports. Show me the full list of files you will change and a representative diff before applying to all of them.”*
> 
> *“After applying, run `grep -r 'friend_face\|friend_name' pwnagotchi/ui/hw/` and confirm it returns nothing. Then commit with message: `Phase 1.5: remove dead friend_face/friend_name layout entries from ui/hw modules`.”*

**Acceptance:** `grep -r "friend_face\|friend_name" pwnagotchi/ui/hw/` returns nothing. `grep -r "friend_face\|friend_name" pwnagotchi/ui/view.py` already returns nothing (confirmed in Phase 1).

-----

### 4.3 Sub-task C — automata.py grateful mood removal

**What:** After Phase 1, `_has_support_network_for()` returns `False` unconditionally because `self._peers` no longer exists. This makes `in_good_mood()` always return `False`. As a result, every call site that branches on `in_good_mood()` or calls `set_grateful()` is unreachable dead code. The affected call sites are the `else: self.set_grateful()` branches in:

- `set_lonely()`
- `set_bored()`
- `set_sad()`
- `set_angry()`
- `next_epoch()`

The methods `_has_support_network_for()`, `in_good_mood()`, and `set_grateful()` itself are also dead.

**What to do:**

1. Delete `_has_support_network_for()` and `in_good_mood()` entirely from `automata.py`
1. Delete `set_grateful()` entirely from `automata.py`
1. In each of `set_lonely()`, `set_bored()`, `set_sad()`, `set_angry()`, and `next_epoch()`, remove the `else: self.set_grateful()` branch (and its surrounding `if in_good_mood():` condition if present). The remaining logic — setting the mood state itself — is unchanged.
1. Remove the `personality.bond_encounters_factor` default from `defaults.toml` if it is only referenced by the now-deleted `_has_support_network_for()`. Verify first: `grep -r "bond_encounters_factor" pwnagotchi/`
1. Verify no `voice.py` method for `set_grateful` is called elsewhere: `grep -r "grateful" pwnagotchi/`

**Claude Code prompt:**

> *“Read `docs/DESIGN.md` Section 4.3. In `pwnagotchi/automata.py`, the `_has_support_network_for()` method now returns `False` unconditionally, making `in_good_mood()` always `False` and all `set_grateful()` call sites unreachable.*
> 
> *Step 1: Run `grep -n 'set_grateful\|in_good_mood\|_has_support_network_for\|bond_encounters_factor' pwnagotchi/automata.py pwnagotchi/defaults.toml pwnagotchi/voice.py` and show me the output so we can confirm the full scope before touching anything.*
> 
> *Step 2: Delete the methods `_has_support_network_for`, `in_good_mood`, and `set_grateful` from `automata.py`. Show me the diff.*
> 
> *Step 3: In `set_lonely`, `set_bored`, `set_sad`, `set_angry`, and `next_epoch`, remove the `else: self.set_grateful()` branch and any `if self.in_good_mood():` condition wrapping it. The mood-setting logic in those methods (e.g., `self.set_lonely()` calling `self._view.on_lonely()`) is unchanged. Show me each diff before applying.*
> 
> *Step 4: If `bond_encounters_factor` has no remaining references after the above, remove it from `defaults.toml`. Run `grep -r 'bond_encounters_factor' pwnagotchi/` to confirm before removing.*
> 
> *Step 5: Commit with message: `Phase 1.5: remove unreachable grateful mood logic from automata.py`.”*

**Acceptance:** `grep -r "set_grateful\|in_good_mood\|_has_support_network_for" pwnagotchi/` returns nothing. The remaining mood methods (`set_lonely`, `set_bored`, `set_sad`, `set_angry`) still exist and are callable. `python -m py_compile pwnagotchi/automata.py` exits 0.

-----

### 4.4 Sub-task D — Regression test update

Add guards to `tests/test_phase1_removal.py` for the three items above, so they cannot be silently reintroduced:

**Claude Code prompt:**

> *“Read `docs/DESIGN.md` Section 4.4. Add three new test methods to `tests/test_phase1_removal.py` using stdlib `unittest` only:*
> 
> *1. `test_voice_peer_methods_removed` — import `pwnagotchi.voice`; assert that `Voice` has no attributes named `on_unread_messages`, `on_new_peer`, or `on_lost_peer`.*
> 
> *2. `test_no_friend_layout_keys_in_hw_modules` — import all modules under `pwnagotchi/ui/hw/` that expose a `layout()` function; for each, call `layout()` and assert that neither `'friend_face'` nor `'friend_name'` is a key in the returned dict.*
> 
> *3. `test_grateful_mood_removed` — import `pwnagotchi.automata`; assert that `Automata` has no attributes named `set_grateful`, `in_good_mood`, or `_has_support_network_for`.*
> 
> *Run the full test file and confirm all tests pass. Commit with message: `Phase 1.5: add regression guards for dead code sweep`.”*

**Acceptance:** `python -m pytest tests/test_phase1_removal.py -v` passes all 11 tests (8 from Phase 1 + 3 new).

-----

### 4.5 Phase 1.5 Deliverables

|Deliverable                  |File(s)                                     |Acceptance                                                                 |
|-----------------------------|--------------------------------------------|---------------------------------------------------------------------------|
|Remove orphaned voice methods|`pwnagotchi/voice.py`                       |grep for on_unread_messages/on_new_peer/on_lost_peer returns nothing       |
|Update i18n catalogues       |`pwnagotchi/locale/**/*.po`, `.pot`         |`make langs` exits 0; obsolete strings marked                              |
|Remove dead layout keys      |`pwnagotchi/ui/hw/*.py` (~30 files)         |grep for friend_face/friend_name in ui/hw/ returns nothing                 |
|Remove grateful mood logic   |`pwnagotchi/automata.py`                    |grep for set_grateful/in_good_mood/_has_support_network_for returns nothing|
|Remove bond_encounters_factor|`pwnagotchi/defaults.toml` (if unreferenced)|grep for bond_encounters_factor returns nothing                            |
|Regression tests             |`tests/test_phase1_removal.py`              |11 tests pass                                                              |
|CHANGELOG.md entry           |`CHANGELOG.md`                              |Phase 1.5 section documents all removals                                   |

### 4.6 Phase 1.5 Sequence

1. **Sub-task A:** Remove orphaned `voice.py` methods → update i18n → commit
1. **Sub-task B:** Remove dead `friend_face`/`friend_name` layout keys from all `ui/hw/` modules → commit
1. **Sub-task C:** Remove `set_grateful`, `in_good_mood`, `_has_support_network_for` from `automata.py`; remove unreachable branches from mood setters; remove `bond_encounters_factor` from defaults.toml if unreferenced → commit
1. **Sub-task D:** Add 3 regression tests to `tests/test_phase1_removal.py` → confirm 11 tests pass → commit
1. Update `CHANGELOG.md` → commit
1. Tag **v1.9.1**

-----

## 5. Claude Code Implementation Guidance

All phases are intended to be executed using Claude Code. This section captures practical guidance for structuring those sessions.

### 5.1 General Principles

**One phase per Claude Code session (or sub-task).** Do not span multiple phases in one session. Each phase has a defined entry state, exit state, and verification step.

**Start every session by pointing Claude Code at this document.** Begin with: *“Read `CLAUDE.md` and `docs/DESIGN.md`. We are starting Phase [N], Section [X]. Do not make changes outside that scope.”*

**Verify before moving on.** Do not start Phase 1.5 until Phase 1 is merged. Do not start Phase 2 until Phase 1.5 is tagged. Do not start Phase 3 until Phase 2’s pytest baseline passes.

**Commit after each numbered step**, not at the end of a session. One step = one commit. This makes the git history reviewable and any single step reversible.

**Scope discipline.** If Claude Code finds something outside the current phase’s scope that needs fixing, it should note it but not fix it. Add a `# TODO(phase-N):` comment and move on.

### 5.2 Phase 1: Claude Code Session Plan

*Phase 1 is complete. See PR #139 and Section 3 for the full record.*

### 5.3 Phase 1.5: Claude Code Session Plan

**Session goal:** Remove the three categories of dead code left by Phase 1. Four tightly-scoped sub-tasks, each its own commit. The prompts are specified verbatim in Sections 4.1–4.4 — use them exactly as written.

**Orientation prompt to open the session:**

> *“Read `CLAUDE.md` and `docs/DESIGN.md` Section 4 (Phase 1.5). Phase 1 is complete and merged. We are now doing Phase 1.5: a dead code sweep of three specific items left behind by Phase 1. The scope is strictly: (A) orphaned voice.py methods and i18n strings, (B) dead friend_face/friend_name keys in ui/hw/ layout modules, and (C) unreachable grateful mood logic in automata.py. Do not touch requirements.in, setup.py, the Ansible playbook, the AI stack, or any other file not named in Section 4. Confirm you understand the scope before we begin.”*

**Then run sub-tasks A through D using the verbatim prompts in Sections 4.1–4.4.**

**What to watch for:**

- Sub-task A: `make langs` requires the Makefile’s locale toolchain. If it fails in a dev environment, confirm the `.po` files were correctly updated by `language.sh update` and document that `make langs` must be run on the Pi or in the builder environment.
- Sub-task B: Some `ui/hw/` modules may define `friend_face`/`friend_name` inside a conditional block or a sub-dict. Claude Code must show the grep output and the diff for at least one representative file before applying to all ~30. Verify the full list matches the grep output.
- Sub-task C: The `personality.bond_encounters_factor` config key in `defaults.toml` must be checked before removal — if any plugin reads it, removing it is out of scope. The grep in Step 1 of the Section 4.3 prompt will surface this.
- Sub-task C: `set_grateful` may have a corresponding `voice.py` method (`Voice.on_grateful` or similar). The grep in Step 5 will surface this. If it exists, it is a follow-up for Phase 2’s cleanup pass, not Phase 1.5.

### 5.4 Phase 2: Claude Code Session Plan

**Session goal:** Upgrade the cleaned codebase to Bookworm 32-bit, Python 3.11, Flask 3.x, and pyproject.toml. Break into sub-sessions.

**Recommended sub-sessions:**

1. **Sub-session A — Base image and pyproject.toml:** *“Update the Ansible base image URL to Raspberry Pi OS Bookworm Lite armhf. Then migrate `setup.py` to `pyproject.toml` using `hatchling`. Preserve all entry points and data file installs. Do not touch `requirements.in` yet.”*
1. **Sub-session B — Flask upgrade:** *“Upgrade Flask and its dependencies as specified in Section 6.4.1 of `DESIGN.md`. Audit `webcfg` plugin and any other plugin that uses `render_template_string` or `request.form` for Flask 3.x compatibility. Show me every change to plugin files before applying.”*
1. **Sub-session C — Python 3.11 compat:** *“Search the codebase for `datetime.utcnow()`, `pkg_resources` usage, and `collections` imports (not `collections.abc`). Fix each as specified in Section 6.2. Run `python -m py_compile` on every `.py` file under `pwnagotchi/`.”*
1. **Sub-session D — pip-compile:** *“Update `requirements.in` as specified: remove pycryptodome (already commented), update Flask stack versions. Then run `pip-compile --resolver=backtracking --strip-extras --prefer-binary` against Python 3.11 and commit the output as `requirements.txt`.”*
1. **Sub-session E — AI guard and tests:** *“Harden the AI fallback guard as described in Section 6.4.2. Then write `tests/test_config.py`, `tests/test_bettercap.py`, `tests/test_plugins.py`, and `tests/test_ai_guard.py` covering the 17 tests specified in Section 6.5.”*

**What to watch for:**

- Flask 3.x removed `flask.escape()` (use `markupsafe.escape()`) and `flask.Markup` (use `markupsafe.Markup`). Most likely impact point is the webcfg plugin.
- pyproject.toml with hatchling requires explicit declaration of data files. Map each `install_file()` call to `[tool.hatch.build.targets.wheel.shared-data]`.
- pip-compile must be run on a Bookworm 32-bit environment (QEMU or Docker). Do not run on a dev workstation.

### 5.5 Phase 3: Claude Code Session Plan

**Session goal:** Migrate to 64-bit OS, replace AI stack with SB3/PyTorch, update build pipeline for aarch64.

**Recommended sub-sessions:**

1. **Sub-session A — Build pipeline:** *“Update the Ansible base image to Bookworm 64-bit (aarch64). Change `GOARCH` to `arm64` for the bettercap build. Update nexmon to use `ARCH=arm64` and 64-bit kernel headers. Do not touch Python code yet.”*
1. **Sub-session B — gymnasium env adapter + tests:** *“Rewrite `pwnagotchi/ai/` gym.Env wrapper to the gymnasium 0.29 API. The observation space and action space dimensions are unchanged. Show me the method signature changes (step, reset) before rewriting. Then write `tests/test_gym_env.py` covering the 7 tests specified in Section 7.2.3, including the env_checker test.”*
1. **Sub-session C — SB3 integration + tests:** *“Update `ai/__init__.py` to import from `stable_baselines3` instead of `stable_baselines`. Update `requirements.in`: remove `tensorflow`, `stable-baselines`, `keras-*`, `tensorboard`, `gym`; add `torch>=2.1`, `stable-baselines3>=2.0`, `gymnasium>=0.29`. Then write `tests/test_sb3_integration.py` covering the 3 tests in Section 7.2.4.”*
1. **Sub-session D — pip-compile aarch64:** *“Run pip-compile against Python 3.11 aarch64 and commit the output as `requirements-aarch64.txt`.”*

**What to watch for:**

- stable-baselines3 uses a different model serialisation format. Do **not** attempt to write model migration code. The break is accepted; document it.
- The gymnasium `step()` method returns a 5-tuple. Grep for all `env.step(` call sites and update any that unpack a 4-tuple.
- The AI sub-session is the highest-risk session. After applying changes, run `tests/test_gym_env.py` before declaring the session complete.

### 5.6 Cross-Phase Guidance

**The checklist is the contract.** The Phase 1 acceptance checklist is in `CLAUDE.md`. For Phases 1.5, 2, and 3, derive equivalent checklists from the deliverables tables before those sessions begin. Ask Claude Code to work through the checklist at the end of every session.

**The `--prefer-binary` flag is already in `requirements.in`.** Don’t remove it — it’s essential for getting piwheels binaries on armhf.

-----

## 6. Phase 2 — 32-bit Stabilisation

**Objective:** Bring the Phase 1–cleaned codebase to a clean, reproducible, well-tested state on the 32-bit armhf target (RPi Zero 2 W, Raspberry Pi OS Bookworm).

The codebase entering this phase is meaningfully smaller: no `grid.py`, no `identity.py`, no `mesh/`, no `pwngrid-peer.service`, no `pycryptodome`.

### 6.1 Base Image: Bookworm 32-bit

Update the builder base image URL to Raspberry Pi OS **Bookworm Lite 32-bit (armhf)**. Bookworm is the current stable Raspberry Pi OS release and ships Python 3.11 as the default interpreter. This also sets up a clean OS baseline for Phase 3 (which uses the 64-bit Bookworm variant).

### 6.2 Python Runtime: 3.7 → 3.11

The pip-compile header in the current `requirements.txt` says “python 3.7”. Re-running pip-compile against Bookworm Python 3.11 is required. Breaking changes to audit and fix:

|Breaking Change                          |Affected Code                           |Fix                                               |
|-----------------------------------------|----------------------------------------|--------------------------------------------------|
|distutils removed (3.12, deprecated 3.10)|`setup.py`                              |Migrate to pyproject.toml (Section 5.3)           |
|`datetime.utcnow()` deprecated           |Logging, timestamp comparisons          |Replace with `datetime.now(timezone.utc)`         |
|`importlib.resources` API (3.9+)         |Plugin loader path resolution           |Replace `pkg_resources` with `importlib.resources`|
|`collections.abc` move (3.10)            |Possible in plugins or transitive deps  |2to3 codemod + manual review                      |
|`asyncio.coroutine` removed (3.11)       |Not directly used; check transitive deps|Dep audit during pip-compile                      |

### 6.3 Migrate setup.py to pyproject.toml

Replace `setup.py` (which uses `distutils.util.strtobool`) with `pyproject.toml` using the `hatchling` build backend.

- **Keep:** all package metadata, entry points, data file installation (config files, systemd units, caplets)
- **Replace:** the `install_file()` custom install logic with `[tool.hatch.build.targets.wheel.shared-data]` declarations
- **Add:** `requires-python = ">=3.9"`; optional dep groups `[ai]` and `[display]`
- **Keep:** `requirements.in` / `requirements.txt` as the lock files for the image build. pyproject.toml dependency metadata is kept deliberately loose; the lock files control actual installed versions.

### 6.4 Dependency Cleanup

#### 7.4.1 Flask 1.x → 3.x

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

#### 7.4.2 AI Stack: Retain with Hardened Guard

TF1.x + stable-baselines 2.x + gym < 0.22 are retained unchanged. The `requirements.in` comment is explicit: SB3/PyTorch requires a 64-bit processor — that is Phase 3.

Harden the AI fallback guard:

1. Log a `WARNING` with the specific import error when TF is unavailable
1. Set a module-level `AI_AVAILABLE = False` flag in `pwnagotchi/ai/__init__.py`
1. In `agent.py`, check `AI_AVAILABLE` before entering AI mode; fall back to `MANU` cleanly
1. Add a small UI indicator so the operator knows AI is inactive

#### 7.4.3 Regenerate requirements.txt

Re-run pip-compile against Bookworm Python 3.11. The `--prefer-binary` flag is already in `requirements.in`. `pycryptodome` is now absent. Commit the new `requirements.txt`.

> pip-compile must be run inside a Bookworm 32-bit QEMU or Docker environment to produce correct armhf/piwheels-compatible output. Do not run on an x86 dev machine.

### 6.5 Test Suite

Add a `tests/` directory at the repo root with a `pytest` harness. All tests must be runnable without hardware (no physical display, no bettercap process, no WiFi interface). All hardware interactions are mocked.

#### 6.5.1 Config Tests (`tests/test_config.py`)

Tests for `pwnagotchi/fs/__init__.py` and the config merge logic.

1. `test_load_valid_toml` — load a minimal valid `config.toml`; assert `main.name` is present and has expected type
1. `test_defaults_are_applied` — load empty user config; assert values from `defaults.toml` appear in merged result
1. `test_user_values_override_defaults` — user config value wins over default
1. `test_yaml_migration` — legacy `.yaml` config parses without error and matches equivalent `.toml` merge
1. `test_missing_required_key_raises` — accessing a key with no default raises expected exception, not silent `KeyError`
1. `test_no_grid_keys_in_defaults` — assert `main.plugins.grid` does not appear anywhere in `defaults.toml` *(Phase 1 regression guard)*

#### 6.5.2 bettercap Client Tests (`tests/test_bettercap.py`)

Using `responses` library for HTTP mocking and `pytest-asyncio` for websocket mocking.

1. `test_session_get_success` — mock `GET /api/session` 200; assert client parses and returns session dict
1. `test_http_timeout_raises` — mock connection timeout; assert client raises within configured timeout window
1. `test_http_retry_on_failure` — mock two 500s then a 200; assert client retries and returns success
1. `test_websocket_reconnect_on_close` — mock websocket close event; assert reconnection is attempted
1. `test_websocket_reconnect_on_error` — mock websocket error event; assert reconnection is attempted
1. `test_no_grid_module_imported` — import `pwnagotchi.bettercap`; assert `'pwnagotchi.grid'` not in `sys.modules` *(Phase 1 regression guard)*

#### 6.5.3 Plugin Loader Tests (`tests/test_plugins.py`)

1. `test_load_valid_plugin` — minimal in-memory plugin with `__author__`, `__version__`, `on_loaded`; loads without error
1. `test_plugin_on_loaded_called` — `on_loaded` fires exactly once after load
1. `test_bad_plugin_does_not_crash_loader` — plugin whose `__init__` raises; loader catches, logs, continues
1. `test_enable_disable_lifecycle` — load, disable, re-enable; callbacks fire in order
1. `test_unknown_callback_is_ignored` — dispatch unknown callback name; no exception
1. `test_on_peer_detected_not_registered` — `on_peer_detected` not in loader’s known callback registry *(Phase 1 regression guard)*

#### 6.5.4 AI Guard Tests (`tests/test_ai_guard.py`)

1. `test_ai_available_false_when_tf_missing` — patch `sys.modules` so TF import raises `ImportError`; assert `pwnagotchi.ai.AI_AVAILABLE is False`
1. `test_ai_warning_logged_when_tf_missing` — same setup; assert `WARNING` with import error message is emitted
1. `test_agent_starts_in_manu_when_ai_unavailable` — construct agent with `AI_AVAILABLE = False` and mock config; assert initial mode is `MANU`
1. `test_ai_available_true_when_tf_present` — patch TF as importable stub; assert `AI_AVAILABLE is True` *(auto-skip if TF not installed)*

### 6.6 Linting and Formatting

Add `ruff` as the single linter and formatter. Commit `ruff.toml` and `.pre-commit-config.yaml`. Apply formatting as a **separate cosmetic commit** from any functional change so blame history stays readable.

### 6.7 USB Networking

Replace `/etc/network/interfaces.d/usb0` with a NetworkManager `.nmconnection` profile for the USB gadget interface. Bookworm defaults to NetworkManager; the legacy `ifupdown` approach conflicts with it.

### 6.8 Phase 2 Deliverables

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

## 7. Phase 3 — 64-bit Migration

**Objective:** Migrate the Phase 2–stabilised codebase to a 64-bit (aarch64) target on the same RPi Zero 2 W hardware, running Raspberry Pi OS Bookworm 64-bit. Replace TF1.x/SB2 with PyTorch/SB3.

The `requirements.in` comment is the explicit statement: *“Upgrading to stable-baselines3 is currently impossible because it depends on PyTorch which requires a 64-bit processor.”* Phase 3 resolves this.

### 7.1 Architecture Comparison

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

### 7.2 AI Stack Migration

#### 7.2.1 New Stack

Remove from `requirements.in`: `tensorflow`, `stable-baselines`, `keras-applications`, `keras-preprocessing`, `tensorboard`, `gym`.

Add: `torch >= 2.1`, `stable-baselines3 >= 2.0`, `gymnasium >= 0.29`.

#### 7.2.2 gymnasium API Differences

|Method   |gym 0.14–0.21 (current)            |gymnasium 0.29+ (Phase 3)                           |
|---------|-----------------------------------|----------------------------------------------------|
|`step()` |Returns `(obs, reward, done, info)`|Returns `(obs, reward, terminated, truncated, info)`|
|`reset()`|Returns `obs`                      |Returns `(obs, info)`                               |
|Namespace|`import gym`                       |`import gymnasium as gym`                           |

Rewrite `pwnagotchi/ai/` gym.Env wrapper to the gymnasium API. The observation space and action space dimensions are **unchanged**; only method signatures change. Grep for all `env.step(` call sites and update any that unpack a 4-tuple.

#### 7.2.3 gymnasium Env Tests (`tests/test_gym_env.py`)

Using mock bettercap state dict; no hardware required.

1. `test_reset_returns_two_tuple` — `env.reset()` returns `(obs, info)`, not a bare array
1. `test_reset_obs_matches_observation_space` — `observation_space.contains(obs)` is `True` after reset
1. `test_step_returns_five_tuple` — `env.step(action)` unpacks to exactly 5 elements
1. `test_step_terminated_and_truncated_are_bools` — both `terminated` and `truncated` are `bool`, not a single `done`
1. `test_step_obs_within_bounds` — `observation_space.contains(obs)` is `True` after step with random valid action
1. `test_valid_actions_accepted` — all values in `action_space` accepted by `env.step()` without raising
1. `test_gymnasium_env_checker` — `gymnasium.utils.env_checker.check_env(env)` raises no warnings or errors

#### 7.2.4 SB3 Integration Tests (`tests/test_sb3_integration.py`)

Mark all with `@pytest.mark.slow`. Excluded from fast CI run; run in nightly or pre-release CI.

1. `test_a2c_instantiates` — `stable_baselines3.A2C('MlpPolicy', env)` raises no exception
1. `test_a2c_learn_one_step` — `model.learn(total_timesteps=1)` completes without error
1. `test_model_save_load_roundtrip` — save to temp file; load back; loaded model’s policy network has same architecture

#### 7.2.5 Model File Incompatibility

TF1.x stable-baselines 2.x model files (`.pkl`) cannot be loaded by stable-baselines3. **Accept the break and re-train from scratch** on Phase 3 images. Do not write migration code. Document clearly in CHANGELOG.md.

### 7.3 Build Pipeline Changes

- **bettercap:** Change `GOARCH=arm` to `GOARCH=arm64` in the Ansible Go build task. No source changes.
- **nexmon:** Set `ARCH=arm64` and install 64-bit kernel headers. Same chip firmware patches (BCM43436b0, BCM43430a1, BCM43455c0); only the build target changes.
- **pwngrid:** Already removed in Phase 1. No action needed.
- **requirements:** Run pip-compile against aarch64 Python 3.11. Commit as `requirements-aarch64.txt`.

### 7.4 Phase 3 Deliverables

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

## 8. What is Explicitly Out of Scope

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

## 9. Risk Register

|Risk                                                                                                                              |Likelihood|Impact|Mitigation                                                                                                                                                                 |
|----------------------------------------------------------------------------------------------------------------------------------|----------|------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|`on_peer_detected` / `on_peer_lost` removal breaks a widely-used third-party plugin                                               |Low       |Medium|Publish Phase 1 as named beta; give community 2+ weeks to report; document in CHANGELOG prominently                                                                        |
|`api.pwnagotchi.ai` DNS resolves (confirmed: Cloudflare proxy at 172.67.162.248) but some community members attempt to use the API|Low       |Low   |Removal rationale rests on unmaintained upstream and non-functional port 8666, not on DNS failure; this is documented in CHANGELOG.md                                      |
|Phase 1.5 `automata.py` grateful removal breaks an unexpected caller                                                              |Low       |Low   |The grep in Section 4.3 Step 1 must be run and reviewed before any deletion; `python -m py_compile` on automata.py is the acceptance gate                                  |
|Phase 1.5 `make langs` fails in dev/CI environment                                                                                |Medium    |Low   |`language.sh update` can be run without make; the `.po` file edits are the meaningful output; `make langs` compiles to `.mo` and can be deferred to the builder environment|
|agent.py cleanup introduces a regression in state machine behaviour                                                               |Medium    |Medium|Phase 1 tests catch import-level issues; Phase 2 pytest baseline catches regressions going forward                                                                         |
|Flask 3.x upgrade breaks webcfg plugin or third-party plugins using Flask internals                                               |Medium    |Medium|Audit webcfg and all default plugins against Flask 3.x before tagging Phase 2 stable                                                                                       |
|nexmon arm64 build fails on new Bookworm kernel version                                                                           |Medium    |High  |Pin kernel version in builder; track nexmon issue tracker; fork already has nexmon source-build experience                                                                 |
|PyTorch memory pressure on 512 MB Zero 2 W                                                                                        |Low       |High  |Community forks confirm PyTorch works on Zero 2 W; monitor swap usage; SB3 A2C is relatively lightweight                                                                   |
|pip-compile on Bookworm 3.11 produces dep set incompatible with piwheels                                                          |Medium    |Medium|Run pip-compile inside a Bookworm 32-bit QEMU environment; `--prefer-binary` already in requirements.in                                                                    |

-----

## 10. Implementation Sequence

### Phase 1: pwngrid & Peer-Advertising Removal ✅ Complete (PR #139)

1. Confirmed removal rationale: pwngrid unmaintained; port 8666 non-functional; api.pwnagotchi.ai DNS resolves but API non-functional.
1. Deleted: `grid.py`, `identity.py`, `plugins/default/grid.py`, `pwngrid-peer.service`, `pwnagotchi/mesh/`.
1. Cleaned `agent.py`, `bin/pwnagotchi`, `handler.py`, `automata.py`, `ui/view.py`, `log.py`, `voice.py` (peer summary), `defaults.toml`, Ansible playbook, default plugins.
1. Relocated `mesh/wifi.py` → `pwnagotchi/wifi.py`; commented out `pycryptodome`.
1. Wrote `tests/test_phase1_removal.py` (8 tests). All pass.
1. CHANGELOG.md written. Tag **v1.9.0-beta** pending Pi smoke test.

### Phase 1.5: Dead Code Sweep (target: v1.9.1)

1. Sub-task A: Remove orphaned `voice.py` methods → update i18n → `make langs` → commit
1. Sub-task B: Remove dead `friend_face`/`friend_name` layout keys from all `ui/hw/` modules → commit
1. Sub-task C: Remove `set_grateful`, `in_good_mood`, `_has_support_network_for` from `automata.py`; remove unreachable branches; remove `bond_encounters_factor` from defaults.toml if unreferenced → commit
1. Sub-task D: Add 3 regression tests; confirm 11 tests pass → commit
1. Update CHANGELOG.md → commit. Tag **v1.9.1**.

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

## 11. Appendix

### A. Phase 1 & 1.5 Acceptance Checklists

**Phase 1 (PR #139 — complete)**

|# |Item                                                                                              |Verification                                                                     |
|--|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
|1 |`pwnagotchi/grid.py` deleted                                                                      |`grep -r "import.*grid" pwnagotchi/` returns nothing                             |
|2 |`pwnagotchi/identity.py` deleted                                                                  |`grep -r "import.*identity" pwnagotchi/` returns nothing                         |
|3 |`pwnagotchi/mesh/` directory deleted                                                              |Directory absent; `pwnagotchi/wifi.py` present as replacement for channel math   |
|4 |`pwnagotchi/plugins/default/grid.py` deleted                                                      |git status shows deletion                                                        |
|5 |`pwngrid-peer.service` deleted                                                                    |git status shows deletion                                                        |
|6 |`agent.py`: AsyncAdvertiser removed; no grid/identity references                                  |`grep -r "grid|identity|AsyncAdvertiser" pwnagotchi/agent.py` returns nothing    |
|7 |`automata.py`: no `on_peer_detected` dispatch; `_has_support_network_for` returns False           |Confirmed in PR #139                                                             |
|8 |`ui/view.py`: no `on_unread_messages`, `on_new_peer`, `on_lost_peer`, `friend_face`, `friend_name`|`grep -r "on_unread_messages|friend_face" pwnagotchi/ui/view.py` returns nothing |
|9 |`defaults.toml`: no `[main.plugins.grid]` block                                                   |`grep -r "plugins.grid"` returns nothing                                         |
|10|`builder/pwnagotchi.yml`: no pwngrid tasks                                                        |`grep -i "pwngrid" builder/` returns nothing                                     |
|11|`builder/pwnagotchi.yml`: `/etc/pwnagotchi/` mkdir task still present                             |`grep "pwnagotchi" builder/pwnagotchi.yml` shows mkdir task                      |
|12|`pycryptodome` commented out in `requirements.in`                                                 |Not present in pip-compiled output (Phase 2 verification)                        |
|13|All 8 tests in `tests/test_phase1_removal.py` pass                                                |`python -m pytest tests/test_phase1_removal.py -v`                               |
|14|Image boots without error                                                                         |`journalctl -u pwnagotchi` shows no errors referencing pwngrid, grid, or identity|
|15|Display renders correctly                                                                         |No inbox/peer counter UI element; face renders normally                          |
|16|bettercap starts and WiFi scanning works                                                          |Handshake capture functional in AUTO mode                                        |

**Phase 1.5 (target: v1.9.1)**

|#|Item                                                                 |Verification                                                                               |
|-|---------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
|1|`voice.py` peer/inbox methods removed                                |`grep -r "on_unread_messages|on_new_peer|on_lost_peer" pwnagotchi/voice.py` returns nothing|
|2|i18n catalogues updated                                              |`make langs` exits 0; obsolete peer/inbox strings marked in `.po` files                    |
|3|Dead layout keys removed from `ui/hw/`                               |`grep -r "friend_face|friend_name" pwnagotchi/ui/hw/` returns nothing                      |
|4|`set_grateful`, `in_good_mood`, `_has_support_network_for` removed   |`grep -r "set_grateful|in_good_mood|_has_support_network_for" pwnagotchi/` returns nothing |
|5|Unreachable `else: set_grateful()` branches removed from mood setters|`grep -r "set_grateful" pwnagotchi/automata.py` returns nothing                            |
|6|`bond_encounters_factor` removed from defaults.toml (if unreferenced)|`grep -r "bond_encounters_factor" pwnagotchi/` returns nothing                             |
|7|All 11 tests pass                                                    |`python -m pytest tests/test_phase1_removal.py -v` (8 original + 3 new guards)             |
|8|`python -m py_compile pwnagotchi/automata.py` exits 0                |No syntax errors                                                                           |

### B. Dependency Version Summary (All Phases)

|Package          |Current Fork             |Phase 1                        |Phase 1.5|Phase 2 (32-bit)     |Phase 3 (64-bit)|
|-----------------|-------------------------|-------------------------------|---------|---------------------|----------------|
|Python           |3.7 (pip-compile target) |Unchanged                      |Unchanged|3.11                 |3.11            |
|OS               |Bullseye 32-bit          |Unchanged                      |Unchanged|Bookworm 32-bit      |Bookworm 64-bit |
|pycryptodome     |~= 3.9                   |Commented out                  |Unchanged|Removed (pip-compile)|Removed         |
|tensorflow       |>= 1.8, < 1.14           |Unchanged                      |Unchanged|Guarded              |Removed         |
|stable-baselines |~= 2.7                   |Unchanged                      |Unchanged|Guarded              |Removed         |
|stable-baselines3|—                        |—                              |—        |—                    |>= 2.0          |
|torch (PyTorch)  |—                        |—                              |—        |—                    |>= 2.1          |
|gym              |~= 0.14, < 0.22          |Unchanged                      |Unchanged|Unchanged            |Removed         |
|gymnasium        |—                        |—                              |—        |—                    |>= 0.29         |
|flask            |~= 1.0                   |Unchanged                      |Unchanged|>= 3.0, < 4          |>= 3.0, < 4     |
|MarkupSafe       |< 2.1.0 (hack)           |Unchanged                      |Unchanged|Cap removed          |Cap removed     |
|pwngrid binary   |armhf binary (unused)    |Removed                        |Removed  |Removed              |Removed         |
|grid.py          |Present                  |Deleted                        |Absent   |Absent               |Absent          |
|identity.py      |Present                  |Deleted                        |Absent   |Absent               |Absent          |
|mesh/            |Present                  |Deleted                        |Absent   |Absent               |Absent          |
|wifi.py          |Absent (was mesh/wifi.py)|Relocated to pwnagotchi/wifi.py|Present  |Present              |Present         |
|bettercap        |Source (Go 1.22.4)       |Unchanged                      |Unchanged|Unchanged            |GOARCH=arm64    |

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