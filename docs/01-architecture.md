# GWPS architecture (as inherited from OpenTyria)

This is the map of the stack we forked, so every later change has a shared
reference. It describes **what exists today**, not what we want it to become
(for that, see `03-roadmap.md`).

## The stack at a glance

```
┌──────────────────────────────────────────────────────────────────────┐
│ Guild Wars client (Gw.custom.exe, patched by tools/patch-gw.py)      │
│   + portal.dll (portal/portal.c) injected to fake the "portal" step  │
└─────────────┬──────────────────────────────┬─────────────────────────┘
              │ 1. HTTPS web-gate            │ 2. game/portal TCP
              │    (login → session UUID)    │    6112 / 6113
              ▼                              ▼
┌───────────────────────────┐   ┌──────────────────────────────────────┐
│ tools/webgate.py          │   │ OpenTyria.exe  (ONE process)         │
│ fake ArenaNet web gate,   │   │                                      │
│ hardcoded USERS, sessions │   │  AuthSrv  ── single event-loop thread│
│ in RAM, self-signed TLS   │   │    ├ listeners :6112 :6113 :1337     │
└───────────────────────────┘   │    ├ AuthConnection (login/char sel) │
                                │    └ CtrlConnection (to game servers)│
                                │                                      │
                                │  GameSrv #1 ── thread (a map/district)│
                                │  GameSrv #2 ── thread                 │
                                │  GameSrv #N ── thread                 │
                                │      └ each = own epoll + own SQLite  │
                                │        handle + own Gw.dat handle     │
                                └───────────────┬──────────────────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │ db/database.db (SQLite)│
                                    │ Gw.dat (client archive)│
                                    └───────────────────────┘
```

## Components

### `OpenTyria.exe` — `code/OpenTyria/`

Built as a **single translation unit**: `build_open_tyria.c` `#include`s every
`.c` file in the project (and those `.c` files carry `#pragma once`). Adding a
source file means adding an `#include` there.

| File | Role |
|------|------|
| `main.c` | Hardcoded bind addresses, DH prime/private key, then `while (keep_running) AuthSrv_Update(&server);` |
| `AuthSrv.c/.h` | The auth server: login, character selection, session/account registry, spawning game servers |
| `AuthSrvCtrl.c` | Ctrl-protocol handlers: create game server, find compatible server, server-ready |
| `GameSrv.c/.h` | The game server: one instance = one map "district"; handles movement, agents, chat, items, parties |
| `CtrlConn.c/.h` | The loopback control connection between a GameSrv and the AuthSrv |
| `Db.c`, `DbSchema.h` | SQLite access, all prepared statements created once in `Db_Open` |
| `FaArchive.c`, `FaCompress.c` | Reader for `Gw.dat` (the client's asset archive) |
| `iocp.c`, `iocp.h`, `win32/iocp_win32.c`, `linux/iocp_linux.c` | A tiny "I/O completion port" abstraction: IOCP on Windows, `epoll` + `EPOLLONESHOT` on Linux |
| `sys.h`, `win32/sys_win32.c`, `linux/sys_linux.c` | Platform layer: sockets, threads, mutex, monotonic time |
| `network.c` | socket address parsing/formatting helpers |
| `msgdefs.c`, `msgdefs.info`, `opcodes.h`, `GameMsg.h`, `AuthMsg.h` | The wire protocol: message tables, pack/unpack definitions |
| `msgpack.c`, `stream.c`, `endian.h`, `bitmap.h`, `slice.h`, `array.*` | Serialization and container utilities |
| `Gm*.c/.h` | Gameplay: `GmPlayer`, `GmAgent`, `GmParty`, `GmInventory`, `GmItem`, `GmChat`, `GmChar`, `GmPaths`, `GmPathHeap`, `GmMaps*`, `GmText`, `GmTitles`, `GmDefaultArmors` |
| `stb_ds.h`, `stb_sprintf.h` | Vendored single-header libraries (hashmaps/dynamic arrays, printf) |
| `sqlite3.c/.h` | Vendored SQLite amalgamation (compiled as its own TU) |
| `logs.c` | Leveled logging to `stderr` |
| `random.c`, `arc4.c` | ChaCha20-based randomness, and the ARC4 variant the protocol needs |
| `tests.c` | Small test entry (`COMPILE_TESTS` config) |

### `portal/portal.c`
A Windows DLL (`portal.dll`) that is loaded into the client and stands in for the
real ArenaNet "portal": it receives `user_id`/`session_id` and notifies the
client, so the client skips the real portal round-trip.

### `tools/` (Python)
| Script | Purpose |
|--------|---------|
| `webgate.py` | Fake web-gate HTTPS server. Hardcoded `USERS`, in-RAM `sessions`, self-signed cert. |
| `patch-gw.py` | Patches `Gw.exe` (auth server address, version checks) → `Gw.custom.exe` |
| `gen-dhm-keys.py` | Generates the DH `prime`, `server_private`, `server_public` (needs `openssl`) |
| `packet.py`, `msgs.py`, `consts.py`, `process.py`, `pygw.py` | Packet framing, message catalog, and the reference protocol implementation |
| `trace-packets.py`, `trace-pathfinding.py`, `draw-map.py` | Tooling for analysing captured traffic / map data |
| `test.py`, `utils.py` | Small helpers |

### `deps/`
| Directory | Contents |
|-----------|----------|
| `deps/mbedtls-3.6.0/` | Mbed TLS, used for big-number DH (`mbedtls_mpi`) and ChaCha20 |
| `deps/sqlite-amalgamation-3460000/` | SQLite 3.46 shell + amalgamation sources |

### `vc/`
MSVC solution/projects (`OpenTyria.sln`, `OpenTyria.vcxproj`, `mbedtls.vcxproj`,
`Portal.vcxproj`). **Note:** `OpenTyria.vcxproj` is stale — it still lists
`CtrlProto.c`, which no longer exists. GWPS replaces this with CMake
(`CMakeLists.txt`); the `vc/` files are kept only for reference.

## Connection lifecycle (happy path)

1. Client is patched (`patch-gw.py`) to point at `127.0.0.1`.
2. Client does the web login against `webgate.py` → receives a `user_id` and
   `session_id` UUID.
3. `portal.dll` hands those to the client instead of the real portal.
4. Client connects to `:6112` (auth) or `:6113` (game).
5. `AuthSrv` reads `AUTH_CMSG_VERSION` / `GAME_CMSG_VERSION` /
   `CTRL_CMSG_VERSION` to decide the connection type (`AuthSrv.c:67-138`).
6. Key exchange: `CMSG_CLIENT_SEED` → server computes
   `shared_secret = client_public ^ server_private mod prime`
   (`AuthSrv.c:140-180`), derives an ARC4 key, and from then on both directions
   are ARC4-encrypted.
7. Auth connection: login → account/character list → select character →
   the auth server picks or creates a `GameSrv` for the character's map.
8. The auth server brokers a **transfer** to that game server over the loopback
   ctrl connection (`GameSrvMetadata.pending_transfers`), handing the client a
   player token + the game server's address/port.
9. The client opens a **new** connection to the game server; the game server
   loads the character, bags, items, and map from SQLite / `Gw.dat`, and
   spawns the player as an agent.

## Data model (`db/seed.sql` → `db/database.db`)

`users` → `sessions` → `accounts` → `characters` → `bags` / `items`, plus
`friendships`. UUIDs are stored as 36-char strings; names are UTF-16 blobs.
Seed users from the upstream README: `user1@example.com`, `user2@example.com`,
`user3@example.com`.

## Runtime assets (not in git)

| File | Where | Why |
|------|-------|-----|
| `Gw.dat` | repo root | The client's asset archive; map/armor/model data is read from it |
| `db/database.db` | `db/` | Created by loading `db/seed.sql` |
| `Gw.custom.exe`, `portal.dll` | client dir | Produced by `patch-gw.py` / building `portal/` |

All three are in `.gitignore` — never commit them.
