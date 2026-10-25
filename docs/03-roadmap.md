# GWPS roadmap

## The goal

Run a private server that lets a stock Guild Wars client log into **Pre-Searing
Ascalon** — the Prophecies tutorial region (level cap 10) — and play it, on top
of the OpenTyria stack.

"Pre-Searing" means, concretely:

- **Outposts:** Ascalon City (pre-Searing), Ashford Abbey, Fort Ranik (pre-Searing)
- **Explorables:** Lakeside County, Regent Valley (pre-Searing), Green Hills
  County, Wizard's Folly, The Catacombs, The Northlands
- **Gameplay:** level cap 10, no secondary profession quests beyond the tutorial,
  pre-Searing skills only, the Ascalon Academy / charr-chase is out of scope for
  the first milestone.

## Where we actually stand

The fork compiles the whole GW1 world (all ~900 map ids are enumerated in
`code/OpenTyria/GmMaps.h`), but **only six maps have a `GmMapConfig` and none of
them are Pre-Searing**:

```
code/OpenTyria/GmMapsConfig.c:  Kamadan (Jewel of Istan), Kaineng Center,
                                Lion's Arch, Domain of Anguish, Sparkfly Swamp,
                                Lornar's Pass
```

`GameSrv_LoadMap` (`GameSrv.c:2019-2022`) silently falls back to **Kamadan** for
any map without a config. So today, logging into a Pre-Searing character puts you
in a Nightfall outpost.

That is milestone 0: **make Pre-Searing maps real.**

## Milestone 0 — Foundation ✅ (this commit)

- [x] Fork OpenTyria into `GWPS`, keep `upstream` remote for future pulls
- [x] Document architecture (`docs/01-architecture.md`)
- [x] Document inherited scaling limits (`docs/02-scaling-limitations.md`)
- [x] Replace the stale MSVC-only build with a portable CMake build
- [x] Build/run scripts (`scripts/build.ps1`, `scripts/run.ps1`, `scripts/seed-db.ps1`)
- [x] Repo hygiene: `.gitignore`, `.gitattributes`, no `Gw.dat`/`*.db` committed
- [x] Verified the result actually compiles and runs (MSVC 19.42, listens on
      6112/6113/1337)
- [ ] **Still open:** config external — ports, paths and DH keys are still
      hardcoded in `main.c`. Tracked as milestone 2, item 1.

## Milestone 1 — Pre-Searing maps load

> **Sequencing note:** the current working scope is **Phase 0 (verify the
> inherited stack)** — see `04-scope.md`. Milestone 1 does not start until Phase 0
> exit criteria are met. Phase 0 deliberately uses Kamadan, the only map with a
> working config.

Blocked on one value per map: **the `map_file_id`**, the key used to fetch the map
blob from `Gw.dat`.

**Status 2026-10-25: the first map is done and the blocker is understood.** Ascalon
City (pre-Searing) loads — `map_file_id = 0x1B97D`, spawn `(9541.873, 4796.456)`,
confirmed by a client logging into the GWPS server (see `docs/test-log.md`).

The earlier hope that `AreaInfo.file_id` would supply every map at once is **dead**
(F5): the field reads 0 for Pre-Searing maps even while standing in one. A blob
carries no map identity either — no name string, and its `name_id` does not appear
(checked against map 148 and Kamadan). So `map_id → file_id` is **observed once per
map**, not derived offline.

Procedure per map, proven end to end on map 148:

1. Stand the live client in the map.
2. `py tools/probe-pathing.py --dump-trapezoids build/<map>.csv` (elevated) — the
   client's navmesh fingerprint: planes, trapezoid count, bounds.
3. Match it against `gwdat_pathing Gw.dat --min-size 0` (never filter by compressed
   size). If the sheet has no match, `gwdat_pathing Gw.dat --find-floats
   build/<map>.csv` scans all 146 901 ids for the client's own float pairs.
4. Add a `GmMapConfig` in `code/OpenTyria/GmMapsConfig.c` with `map_id`,
   `map_file_id`, and the player's own position as a spawn point.
5. Add the `case` to `GetMapConfigForMapId`.
6. Verify: `GameSrv_LoadMap` no longer warns "No config for map … falling back to
   default", and the client lands in the right place.

Target set for milestone 1, in dependency order:

| Map | id | Type | File id |
|-----|----|------|---------|
| **Ascalon City (pre-Searing)** | 148 | outpost | **0x1B97D ✅ loads** |
| Ashford Abbey | 164 | outpost | _one client visit_ |
| Lakeside County | 146 | explorable | _one client visit_ |
| Regent Valley (pre-Searing) | 162 | explorable | _one client visit_ |
| Green Hills County | 160 | explorable | _one client visit_ |
| Wizard's Folly | 161 | explorable | _one client visit_ |
| The Catacombs | 145 | explorable | _one client visit_ |
| The Northlands | 147 | explorable | _one client visit_ |

**Exit criteria:** a character can log in, be spawned at a valid spawn point, and
see terrain/other players in Ascalon City (pre) and in Lakeside County.

## Milestone 2 — Make it operable

The scaling work that is *cheap now and painful later*, in priority order (see
`02-scaling-limitations.md` for evidence):

1. **Config file + CLI.** Ports, DB path, `Gw.dat` path, DH key path, log level,
   data dir. Kills the hardcoded `127.0.0.1:6112/6113/1337` and the baked-in DH
   private key (`main.c:3-42`). → also lets one binary serve multiple maps
   properly.
2. **Fix logging.** `LOG_MIN_LEVEL` at compile time, buffered/async writer,
   `server_id` in every line. Removes an unbuffered `fflush` per log line from
   the hot loops (`logs.c:74`).
3. **SQLite pragmas.** `journal_mode=WAL`, `synchronous=NORMAL`,
   `busy_timeout`, sane `cache_size` in `Db_Open` (`Db.c:255`). Removes
   `SQLITE_BUSY` and reader/writer starvation across maps.
4. **Backpressure.** Cap `conn->outgoing`; drop or throttle slow readers
   (`GameSrv.c:166`). Removes a trivial OOM vector.
5. **Graceful shutdown.** Signal game servers, join threads, call
   `GameSrv_Free`, exit the `main()` loop cleanly (`GameSrv.c:2048-2066`).

**Exit criteria:** start → play → `Ctrl+C` → clean exit, no leaks, no
`Missing a lot of freeing here!!`.

## Milestone 3 — Make it survive

1. **DH off the event-loop thread.** Worker pool for key exchange, plus
   per-IP rate limiting before the first DH (`AuthSrv.c:169`).
2. **Presence out of RAM.** Move `GlobalAccountRegistry` + `pending_transfers`
   to a shared store so a restart does not log everyone out
   (`AuthSrv.h:99-109,144`).
3. **Real game-server lifecycle.** Supervise, respawn on crash, stop calling
   `abort()` on a poll error (`GameSrv.c:1919`).
4. **Per-frame work proportional to activity**, not population: replace the
   three full scans in `GameSrv_Update` with dirty sets and a ping wheel
   (`GameSrv.c:1923-2009`).

## Milestone 4 — Make it scale out

1. **True process boundary.** Spawn `GameSrv` as a child process with a real
   (configurable, non-loopback) ctrl transport, instead of
   `calloc`+`thread` in `AuthSrvCtrl_CreateServer` (`AuthSrvCtrl.c:34-68`).
2. **District allocation.** Stop hardcoding `district_number = 1`
   (`AuthSrvCtrl.c:41`); allocate least-populated compatible districts, create
   new ones on overflow, and send `(server_id, district)` back to the client.
3. **Observability.** Counters: connections, logins in flight, per-map
   population, frame time, DB wait time. A small status endpoint.

## Milestone 5 — Pre-Searing content

Only after the platform is boring:

- Spawn points and portals between Pre-Searing outposts and explorables
- NPCs (there is no NPC/agent AI in OpenTyria yet — `GmAgent` handles players and
  agents but no scripted behaviour)
- Quests, the pre-Searing skill trainers, collectors, merchants
- Level cap 10 enforcement and pre-Searing-only skill/item tables

## Explicitly out of scope (for now)

- Post-Searing Ascalon, other campaigns, PvP, guild halls
- The Ascalon Academy mission and the Searing transition
- Account/registration web front-end (we keep `webgate.py` as a dev stub; a real
  one comes later)

## Working agreements

- `upstream` (`apoguita/OpenTyria`) is **reference only**. We rebase/cherry-pick
  deliberately; we never merge wholesale.
- Every behavioural change gets a note in `docs/` — the docs are the spec.
- Anything that touches the wire protocol gets a capture in `tools/trace-packets.py`
  form before and after.
- No secrets, no `Gw.dat`, no `*.db` in git.
