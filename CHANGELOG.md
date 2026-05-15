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

- **`on_peer_detected` is removed from the plugin callback API.** Any
  third-party plugin implementing `on_peer_detected` will still load without
  error, but the callback will **never fire** — peer detection no longer
  exists. In this fork the dispatch lived in the deleted
  `pwnagotchi/mesh/utils.py` (`AsyncAdvertiser`), not in `automata.py`.

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
- Ansible playbook (`builder/pwnagotchi.yml`): removed the combined pwngrid
  binary download + `/usr/bin/` install task, the `pwngrid-peer.service`
  entry from `services.enable`, and the orphaned `packages.pwngrid` variable.
  The design document's `pwngrid -generate -keys` keypair task does not
  exist in this fork's playbook.

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

### Known follow-ups (still within Phase 1, not yet done)

- `pwnagotchi/_version.py` is still `1.8.4`; the release workflow rewrites
  it to the tagged version.
- `requirements.in`: `pycryptodome` (used only by the deleted `identity.py`)
  not yet commented out; pip-compile is deferred to Phase 2.
- `pwnagotchi/defaults.toml`: the `[main.plugins.grid]` block not yet removed.
- `builder/data/etc/systemd/system/pwnagotchi.service` still has
  `After=pwngrid-peer.service`, referencing the deleted unit.
- `pwnagotchi/voice.py` retains now-orphaned `on_unread_messages`,
  `on_new_peer`, `on_lost_peer` strings (removal touches i18n `.po`/`.pot`
  and `make langs` — to be handled as a dedicated step).
- ~30 `pwnagotchi/ui/hw/*.py` layout modules still define `friend_face` /
  `friend_name` positions; these are now dead layout-dict entries (no longer
  read by `View`).
- `tests/test_phase1_removal.py` (six negative-space assertions) not yet
  written.
