# Changelog

All notable changes to this fork (`aluminum-ice/pwnagotchi`) are documented
in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project aims to follow semantic versioning.

## [Unreleased] — targeting v1.9.1 (Phase 1.5: dead code sweep)

Removal of dead code left behind by Phase 1. No dependency, feature, or
test-infrastructure changes beyond regression guards. This phase closes the
"Known follow-ups" the Phase 1 entry deferred (orphaned `voice.py` methods,
`friend_face` / `friend_name` layout entries, the unreachable grateful
mood). It is **not yet complete**: the i18n catalogue regeneration
(sub-task A) requires the builder/Pi environment and has not been run — see
**Known follow-ups** below.

### Removed

- `pwnagotchi/voice.py`: the orphaned `on_new_peer`, `on_lost_peer`, and
  `on_unread_messages` methods (sub-task A). Their `View` callers were
  deleted in Phase 1; nothing referenced them. The matching `.po` / `.pot`
  catalogue entries are **not yet pruned** — see **Known follow-ups**.
- `pwnagotchi/ui/hw/*.py` (23 modules): the dead `friend_face` /
  `friend_name` keys from every display's `layout()` dict (sub-task B).
  `View` stopped reading them in Phase 1. Only those two keys were removed;
  no other layout entry, class, or import was touched. The modules with two
  colour-branch layouts (`waveshare1`, `waveshare2`, `waveshare213inb_v4`)
  had both occurrences removed.
- `pwnagotchi/automata.py`: the unreachable grateful-mood logic
  (sub-task C) — `_has_support_network_for()` (a constant `False` since
  Phase 1 removed peers), `in_good_mood()`, and `set_grateful()`, plus the
  always-true `if not self._has_support_network_for(...)` guard and the
  dead `else: self.set_grateful()` branch in `set_lonely` / `set_bored` /
  `set_sad` / `set_angry`, and the dead `elif` in `next_epoch()`. The
  mood-setting behaviour itself is unchanged. The now-unused local `factor`
  in `set_bored` / `set_sad` was removed; `set_angry`'s `factor` parameter
  is retained (callers pass it positionally).

### Changed

- `pwnagotchi/ui/view.py`: the one live external caller of the deleted
  `in_good_mood()` (the wait / look-around face selection) was changed to
  `good_mood = False`. This is behaviour-preserving — `in_good_mood()`
  already always returned `False`, so the non-"happy" face variants were
  already always selected. The original sub-task C scope listed only
  `automata.py` / `defaults.toml`; the live `view.py` caller was a defect
  in the sub-task definition, corrected before implementation.

### Added

- `tests/test_phase1_removal.py`: three stdlib-`unittest` regression
  guards (sub-task D) so the swept surface cannot silently return —
  `test_voice_peer_methods_removed`,
  `test_no_friend_layout_keys_in_hw_modules` (instantiates every hw module
  and asserts its `layout()` dict lacks the friend keys on both colour
  branches; installs a minimal in-process PIL stub when PIL is absent
  off-Pi, then strips it so it cannot leak into other tests), and
  `test_grateful_mood_removed`. The file now holds 11 tests.

### Kept (explicitly)

- `personality.bond_encounters_factor` in `defaults.toml` is **retained**.
  The original sub-task C step said to remove it "if only referenced by the
  deleted `_has_support_network_for()`" — but `pwnagotchi/ai/epoch.py`
  still consumes it (`Epoch.observe()`), and the AI stack is out of Phase
  1.5 scope. Removing it would `KeyError` the AI stack. The corresponding
  acceptance-checklist line ("returns nothing (if removed)") is therefore
  N/A, not an unmet gate.

### Known follow-ups

- **i18n catalogues not yet regenerated (sub-task A — blocks the
  `make langs` acceptance item).** Deleting the three `voice.py` methods
  leaves their `msgid`s — and the pre-Phase-1 `"Met 1 peer"` /
  `"Met {num} peers"` strings — stale in `pwnagotchi/locale/**/voice.po`
  and `voice.pot`. Regenerating them needs the GNU gettext toolchain
  (`xgettext` / `msgmerge` / `msgfmt`), which is unavailable in the
  web/CI container (apt mirrors network-blocked) and must be run in the
  builder or on-Pi environment: `scripts/language.sh update <lang>` for
  every locale, then `make langs`. Until then the catalogues compile dead
  strings, but the daemon is unaffected.
- **pytest run.** `python -m pytest` is unavailable until Phase 2 (pytest
  is intentionally not yet a dependency). `python -m unittest
  tests.test_phase1_removal` runs all 11 tests with no failures; the lone
  skip is the pre-existing, environmental `test_agent_imports_cleanly`
  (no `flask` on a dev host). On the builder/Pi image (flask + TF present)
  it is literally "11 passed".
- On-Pi runtime acceptance (image boots, display renders without the
  friend element, moods still set correctly) is verifiable only by booting
  a built image, not in CI.

## [1.9.0] — Phase 1: pwngrid & peer-advertising removal

This release removes all dependency on the `pwngrid` binary, the
`api.pwnagotchi.ai` cloud service, and the local dot11 peer-advertising
layer. It is a feature removal, deliberately isolated from the Phase 2
runtime/Flask modernisation so regressions are easy to bisect.

### Pre-condition confirmation

- **`evilsocket/pwngrid`**: unmaintained — last commit January 2024, no
  releases since 2021.
- **Port 8666** (`pwngrid-peer`): not functional in the current image; a
  prior PR comment in this fork confirms it is not accessible.
- **`api.pwnagotchi.ai`**: a `socket.gethostbyname()` lookup *does* resolve
  (to a Cloudflare address, `172.67.162.248`), contrary to the design
  document's expectation that DNS would fail. Resolution of a parked/proxied
  domain does not make the cloud API functional; the removal rationale rests
  on the unmaintained upstream and the non-functional `pwngrid-peer` port,
  not on a DNS failure.

### BREAKING — Plugin callback API

- **`on_peer_detected` is removed from the plugin callback API.** This is
  the breaking change specified by the design document. Any third-party
  plugin implementing `on_peer_detected` will still load without error, but
  the callback will **never fire** — peer detection no longer exists. In
  this fork the dispatch lived in the deleted `pwnagotchi/mesh/utils.py`
  (`AsyncAdvertiser`), not in `automata.py`.
- **`on_peer_lost` is also removed.** The design document names only
  `on_peer_detected`, but `on_peer_lost` was the equally-dead parallel
  callback: its `peer_lost` dispatch lived in the same deleted
  `mesh/utils.py`. It is removed for the same reason and has the same
  effect — third-party plugins implementing it load fine but it never fires.

### Removed

- Modules deleted outright: `pwnagotchi/grid.py`, `pwnagotchi/identity.py`,
  the entire `pwnagotchi/mesh/` package, `pwnagotchi/plugins/default/grid.py`,
  and `builder/data/etc/systemd/system/pwngrid-peer.service`.
- Web UI: the pwngrid inbox/messaging routes and handlers
  (`/inbox`, `/inbox/profile`, `/inbox/peers`, `/inbox/<id>`,
  `/inbox/<id>/<mark>`, `/inbox/new`, `/inbox/send`) and their now-orphaned
  imports were removed from `pwnagotchi/ui/web/handler.py`.
- `Agent`: `AsyncAdvertiser` dropped from the class bases; the `keypair`
  constructor parameter, the identity `fingerprint()` banner token, and the
  `start_advertising()` / `_update_advertisement()` call sites removed.
- Boot path (`bin/pwnagotchi`): removed the `pwnagotchi.identity.KeyPair`
  and `pwnagotchi.grid` imports and the `keypair=` argument to `Agent(...)`.
- `Automata`: the peer-encounter "support network" state (`self._peers`)
  was removed; `_has_support_network_for()` now returns `False`.
- Display (`ui/view.py`): removed `on_unread_messages`, `on_new_peer`,
  `on_lost_peer`, `set_closest_peer`, and the `friend_face` / `friend_name`
  state elements (the peer/inbox face and counter no longer render).
- Default plugins: the now-dead `on_peer_detected` and `on_peer_lost`
  callback methods were removed from `example.py` (the canonical template),
  `led.py`, and `ntfy.py`, and the `'peer_detected'` / `'peer_lost'` entries
  from `switcher.py`. Their dispatch was deleted with `mesh/utils.py`, so
  these never fired. No module under `pwnagotchi/` now defines
  `on_peer_detected` (design.md Appendix A item #7).
- Ansible playbook (`builder/pwnagotchi.yml`): removed the combined pwngrid
  binary download + `/usr/bin/` install task, the `pwngrid-peer.service`
  entry from `services.enable`, and the orphaned `packages.pwngrid` variable.
  The design document's `pwngrid -generate -keys` keypair task does not
  exist in this fork's playbook.
- `builder/data/etc/systemd/system/pwnagotchi.service`: removed the
  `After=pwngrid-peer.service` ordering directive that referenced the
  deleted unit. `builder/` is now free of any `pwngrid` reference
  (design.md Appendix A item #10).
- `pwnagotchi/defaults.toml`: removed the `main.plugins.grid` block
  (`enabled`, `report`, `exclude`).
- `requirements.in`: `pycryptodome` (used only by the deleted `identity.py`
  for pwngrid RSA/SHA256 identity signing) is commented out with an
  explanatory note. It is not deleted because the pip-compile re-run is
  deferred to Phase 2.
- `LastSession` (`pwnagotchi/log.py`): the dead peer summary — the `Peer`
  import (from the deleted `mesh/peer.py`), `PEER_TOKEN`, the `_peer_parser`
  regex, the `self.peers` / `self.last_peer` state, and the `PEER_TOKEN`
  log-line parsing branch. `last_peer` had no remaining consumer and `peers`
  fed only the manual-mode "Met N peers" status line, removed from
  `pwnagotchi/voice.py` (`on_last_session_data`).

### Added

- `pwnagotchi/wifi.py`: the WiFi channel math (`NumChannels`,
  `NumChannelsExt`, `freq_to_channel`) relocated verbatim out of the
  wholesale-deleted `pwnagotchi/mesh/` package. This code was never
  peer-advertising; it merely lived in `mesh/`. See **Fixed** below.
- `tests/test_phase1_removal.py`: eight stdlib-`unittest` negative-space
  regression tests (pytest is introduced in Phase 2). Six are the
  assertions from design.md Section 3.7 — `pwnagotchi.grid` /
  `pwnagotchi.identity` / `pwnagotchi.mesh` not importable, `import
  pwnagotchi` does not pull in `Crypto`, no plugin registers
  `on_peer_detected`, and `pwnagotchi.agent` carries no reference to a
  removed component. Two additional guards cover the mesh-relocation fix:
  `pwnagotchi.wifi` imports and keeps its constants/behaviour, and nothing
  under `pwnagotchi/` or `bin/` still references `pwnagotchi.mesh`. In a
  developer/CI environment `test_agent_imports_cleanly` is skipped when a
  third-party dependency (e.g. `flask`, `tensorflow`) is absent — by design
  it still fails hard if the breakage names a removed component, and passes
  outright on the built Pi image.

### Fixed

- **Boot-blocking regression from the wholesale `pwnagotchi/mesh/`
  deletion.** `mesh/` contained more than peer-advertising: `mesh/wifi.py`
  (channel math) and `mesh/peer.py` (`Peer`) had non-peer-advertising
  consumers the design document's call-site list did not enumerate. Five
  core modules (`utils.py`, `log.py`, `ai/epoch.py`, `ai/reward.py`,
  `ai/featurizer.py`) still imported `pwnagotchi.mesh.*`, so the daemon
  would have crashed on boot (`ModuleNotFoundError: pwnagotchi.mesh` via
  `agent.py` → `log.py`). Fixed by relocating the channel math to
  `pwnagotchi/wifi.py` (no logic change) and removing the genuinely-dead
  `Peer`/`last_peer`/`peers` LastSession path. No `pwnagotchi.mesh`
  reference remains anywhere except the negative test asserting it is
  unimportable; `test_mesh_module_not_importable` still passes.

### Kept (explicitly)

- The Ansible task that creates `/etc/pwnagotchi/`. That directory is the
  primary application config directory (`config.toml`, `conf.d/`, the log
  path) and is **not** pwngrid-specific. New images will have the directory
  with no RSA key files inside it, which is the correct state.

### Other behavioral consequences

- The **`internet_available`** plugin event no longer fires. Its only
  triggers were the two `grid.is_connected()` checks in `bin/pwnagotchi`,
  which were pwngrid connectivity probes.
- The **`grateful`** mood is now unreachable. `in_good_mood()` always
  returns `False` and the `else: self.set_grateful()` branches in
  `set_lonely`/`set_bored`/`set_sad`/`set_angry` and `next_epoch()` can no
  longer trigger, because the "support network" was entirely peer-based. A
  full removal of the grateful concept was intentionally deferred (out of
  Phase 1 scope).

### Known follow-ups

- `pwnagotchi/_version.py` is still `1.8.4`; the GitHub release workflow
  rewrites it to the tagged version (`PWN_VERSION` / `sed`), so it is not
  bumped by hand here.
- `pwnagotchi/voice.py` retains now-orphaned `on_unread_messages`,
  `on_new_peer`, `on_lost_peer` methods, and the `.po`/`.pot` catalogue
  entries for the removed "Met 1 peer" / "Met {num} peers" strings are now
  unused-but-harmless. Pruning these touches the i18n catalogues and
  `make langs`, so it is left for a dedicated i18n step.
- ~30 `pwnagotchi/ui/hw/*.py` layout modules still define `friend_face` /
  `friend_name` positions. These are now dead layout-dict entries (no longer
  read by `View`); a hardware-layout sweep is deferred.
- On-Pi runtime acceptance (design.md Appendix A items #14–#16 — image
  boots with no pwngrid/grid/identity errors, display renders without the
  inbox/peer element, bettercap handshake capture works in AUTO) can only
  be verified by booting a built image on a Raspberry Pi, not in CI.
