# GWPS

**GWPS** — Guild Wars Private Server. In this deployment it also reads as *Guild
Wars Pre-Searing*, which is what it serves: a private **Pre-Searing Ascalon**
server.

GWPS is an independent project forked from
[apoguita/OpenTyria](https://github.com/apoguita/OpenTyria) (kept as the
`upstream` git remote, reference only). The goal is narrow on purpose: make the
Prophecies tutorial region — Ascalon City (pre), Ashford Abbey, Lakeside County,
Regent Valley, Green Hills County, Wizard's Folly, The Catacombs, The Northlands —
actually playable, and make the server underneath it operable and survivable.

> OpenTyria's own README is upfront that it optimises for simplicity over scale:
> *"there is several design decisions that limit the scaling, but they are chosen,
> because they simpliefied the final solution."*
> **We audited exactly what those are, with file:line evidence, in
> [`docs/02-scaling-limitations.md`](docs/02-scaling-limitations.md).** That
> document is the reason this fork exists.

## Documentation

| Document | What's in it |
|----------|--------------|
| [`docs/01-architecture.md`](docs/01-architecture.md) | Every component of the stack, the connection lifecycle, the data model |
| [`docs/02-scaling-limitations.md`](docs/02-scaling-limitations.md) | **The scaling audit** — 12 concrete limits, with source references and fixes |
| [`docs/03-roadmap.md`](docs/03-roadmap.md) | Milestones 0–5, Pre-Searing map checklist, what's out of scope |
| [`docs/04-scope.md`](docs/04-scope.md) | **Current scope** — Phase 0 verification test plan, what works vs what doesn't |
| [`docs/05-reverse-engineering.md`](docs/05-reverse-engineering.md) | Which tool for which job (Ghidra is for `Gw.exe`, not `Gw.dat`) |
| [`docs/06-client-tooling.md`](docs/06-client-tooling.md) | The Py4GW ecosystem: packet sniffer, client state, and how we read `map_file_id` |
| [`docs/07-packet-scope.md`](docs/07-packet-scope.md) | **Packet classification** — statuses, scope tiers, source precedence, and the generated catalogue |
| [`docs/08-gm-commands.md`](docs/08-gm-commands.md) | `/tp`, `/maps`, and the teleport path end to end |
| [`docs/09-client-connections.md`](docs/09-client-connections.md) | **What the client connects to** — the game connections, ArenaNet's file servers, and the open/closed network modes |
| [`docs/adr/`](docs/adr/) | Why we forked, why CMake, and later decisions |
| [`docs/upstream/README.OpenTyria.md`](docs/upstream/README.OpenTyria.md) | Upstream's original README, preserved |

## Quick start (Windows)

### Prerequisites

| Need | Why | How |
|------|-----|-----|
| CMake ≥ 3.20 | Build | `winget install Kitware.CMake` |
| Visual Studio 2022 (C++ workload) or Build Tools | MSVC compiler | `winget install Microsoft.VisualStudio.2022.BuildTools` |
| Python 3.9+ | Web gate + DB seeding | `winget install Python.Python.3.12` |
| **`Gw.dat`** | The client asset archive — maps/armors/models are read from it. **Not in git.** | Copy from your Guild Wars installation to the repo root |
| Guild Wars client + `portal.dll` | To connect | See *Client setup* below |

### Build

```powershell
./scripts/build.ps1
```

That configures CMake and produces `build/<Config>/gwps_server.exe`.
Equivalent by hand:

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config RelWithDebInfo --target gwps_server
```

### Seed the database

Upstream's README wants you to compile the SQLite shell with `clang` to load
`db/seed.sql`. You don't need a C compiler for that:

```powershell
./scripts/seed-db.ps1
```

Creates `db/database.db` from `db/seed.sql` using Python's `sqlite3`.

### Run

```powershell
./scripts/run.ps1 -WithWebGate
```

The server **must** run with the repo root as its working directory, because it
resolves `db/database.db` (`code/OpenTyria/GameSrv.c:98`) and `Gw.dat`
(`GameSrv.c:103`) relative to the cwd. The script handles that.

Ports (currently hardcoded in `code/OpenTyria/main.c`, scheduled for
config-file work in milestone 2):

| Port | Purpose |
|------|---------|
| 6112 | Auth / portal |
| 6113 | Game |
| 1337 | Internal ctrl (auth ↔ game server), loopback only |

### Client setup

1. Generate DH params (needs `openssl` on PATH):
   `python tools/gen-dhm-keys.py > keys.txt`
2. Patch the client: `python tools/patch-gw.py` → produces `Gw.custom.exe`
3. Launch: `Gw.custom.exe -authsrv 127.0.0.1 -portal 127.0.0.1`
4. Log in with a seeded account: `user1@example.com`, `user2@example.com`, or
   `user3@example.com`

### Network mode (open by default)

The client keeps up to three connections to **ArenaNet's file servers** while playing, for a
file/version check. That is normal and expected. GWPS serves all gameplay on loopback and needs
nothing from that exchange, so **the default is open** — nothing to configure, and a retail
client on the same machine is unaffected. Full detail, including what each socket carries:
[`docs/09-client-connections.md`](docs/09-client-connections.md).

If you want those connections closed as well (a machine dedicated to GWPS, or no traffic to
ArenaNet at all), build the responder once and toggle it:

```powershell
cmake --build build --config RelWithDebInfo --target gwps_dns
.\tools\dns-gwps.ps1 -Enable     # elevated: runs gwps_dns on 127.0.0.1:53 and points the adapter at it
.\tools\dns-gwps.ps1 -Status
.\tools\dns-gwps.ps1 -Disable    # restores the adapter's original DNS and stops the responder
```

This mode is **machine-wide**: while it is on, a retail client on the same machine would also be
redirected and fail to log in. Disable it before playing retail. The adapter's previous DNS
servers are saved and restored by `-Disable`.

`tools/hosts-gwps.ps1` also exists, but only redirects the lookups that honour the hosts file and
therefore gives a partial result — it is kept for diagnosis, not for installs.

## Repository layout

```
CMakeLists.txt      Portable build (replaces the stale vc/*.vcxproj)
code/OpenTyria/     The server: auth, game, ctrl, protocol, gameplay, SQLite
deps/               Vendored mbedtls-3.6.0 and sqlite amalgamation
db/seed.sql         Schema + seed data for db/database.db
portal/portal.c     portal.dll -- fakes the ArenaNet portal in the client
tools/              webgate.py, patch-gw.py, packet tracing/parsing
scripts/            build.ps1, run.ps1, seed-db.ps1
docs/               Architecture, scaling audit, roadmap, ADRs
vc/                 Upstream MSVC projects -- kept for reference, NOT supported
```

## Status

**Current phase: Phase 0 — verify the inherited stack**
(full test plan in [`docs/04-scope.md`](docs/04-scope.md)).

- [x] Forked, documented, buildable from a clean checkout (`scripts/build.ps1`)
- [x] Scaling limits audited (`docs/02-scaling-limitations.md`)
- [x] `portal.dll` builds (`cmake --build build --target portal`)
- [ ] Phase 0 tests T0–T15 (`docs/test-log.md`)
- [ ] Pre-Searing map configs (currently **every** map without a config silently
      falls back to Kamadan, a Nightfall outpost)
- [ ] Config file (ports, paths, DH keys out of `main.c`)
- [ ] Graceful shutdown, WAL, async logging

See [`docs/03-roadmap.md`](docs/03-roadmap.md) for the full plan.

## License & attribution

The OpenTyria code is used under its original license — see [`LICENSE`](LICENSE).
Upstream project: <https://github.com/apoguita/OpenTyria>.

`Gw.dat`, the Guild Wars client, and its assets are ArenaNet/NCSoft property and
are **not** distributed by this project.
