# Changelog

All notable changes to this fork (`aluminum-ice/pwnagotchi`) are documented
in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project aims to follow semantic versioning.

## [Unreleased] — targeting v1.9.0 (Phase 1: pwngrid & peer-advertising removal)

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

### Added

- `tests/test_phase1_removal.py`: six negative-space regression tests
  (design.md Section 3.7), stdlib `unittest` only — pytest is introduced in
  Phase 2. They assert `pwnagotchi.grid` / `pwnagotchi.identity` /
  `pwnagotchi.mesh` are not importable, that importing `pwnagotchi` does not
  pull in `Crypto`, that no plugin registers `on_peer_detected`, and that
  `pwnagotchi.agent` carries no reference to a removed component. In a
  developer/CI environment `test_agent_imports_cleanly` is skipped when a
  third-party dependency (e.g. `flask`, `tensorflow`) is absent — by design
  it still fails hard if the breakage names a removed component, and passes
  outright on the built Pi image.

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
  `on_new_peer`, `on_lost_peer` strings. Removing them touches the i18n
  `.po`/`.pot` catalogues and `make langs`, so it is left for a dedicated
  i18n step.
- ~30 `pwnagotchi/ui/hw/*.py` layout modules still define `friend_face` /
  `friend_name` positions. These are now dead layout-dict entries (no longer
  read by `View`); a hardware-layout sweep is deferred.
- On-Pi runtime acceptance (design.md Appendix A items #14–#16 — image
  boots with no pwngrid/grid/identity errors, display renders without the
  inbox/peer element, bettercap handshake capture works in AUTO) can only
  be verified by booting a built image on a Raspberry Pi, not in CI.
