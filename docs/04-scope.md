# Project scope

Decision: **before we chase Pre-Searing, we prove that what we inherited actually
works.** This document defines that phase precisely, so "testing the existing
implementation" has a beginning, an end, and a pass/fail.

## Two phases, in order

| Phase | Goal | Maps used | Done when |
|-------|------|-----------|-----------|
| **Phase 0 — Verify** | Prove the inherited stack works end to end | Kamadan (Jewel of Istan) — the only map with a working config | A player logs in, spawns, walks, sees another player, chats, and reconnects, with a clean log |
| **Phase 1 — Pre-Searing** | Make the tutorial region real | Ascalon City (pre), Lakeside County, ... | See `03-roadmap.md` |

Phase 1 is blocked by Phase 0 in a practical sense: if we cannot get two clients
into Kamadan, adding eight more map configs will only give us eight more broken
maps to debug at once.

## Why Kamadan and not Ascalon

`GetMapConfigForMapId` (`GmMapsConfig.c:37-55`) only knows six maps:

```
Kamadan, Jewel of Istan (outpost)   <- has spawn points
Kaineng Center (outpost)
Lion's Arch (outpost)
Domain of Anguish
Sparkfly Swamp
Lornar's Pass
```

Anything else silently falls back to Kamadan (`GameSrv.c:2019-2022`). So Kamadan
is currently the only map with a real `map_file_id` **and** spawn coordinates.
Phase 0 uses it deliberately: it tests the engine, not the content.

Note also `GameSrv.c:1709` stamps every newly created character with
`last_outpost = MapId_KamadanJewelOfIstanOutpost`, so a fresh character is already
destined for Kamadan. Phase 0 works with that; Phase 1 changes it.

## What is actually implemented

This is the honest feature surface, derived from the message dispatch tables.
Anything not listed here is **not implemented** and will log
`Unhandled GameSrv packet` / `Unhandled AuthSrv packet`.

### Auth server — 13 handlers (`AuthSrv.c:1348-1390`)

`SEND_COMPUTER_INFO`, `SEND_COMPUTER_HASH`, `PORTAL_ACCOUNT_LOGIN`,
`ASK_SERVER_RESPONSE`, `SET_PLAYER_STATUS`, `CHANGE_PLAY_CHARACTER`,
`REQUEST_GAME_INSTANCE`, `HEARTBEAT`, `DISCONNECT`, `ACCEPT_EULA`,
`ADD_ACCESS_KEY`, `DELETE_CHARACTER`, `UPDATE_CHARACTER_SETTINGS`

### Game server — 18 handlers (`GameSrv.c:1847-1895`)

`DISCONNECT`, `HEARTBEAT`, `PING_REQUEST`, `PING_REPLY`,
`INSTANCE_LOAD_REQUEST_SPAWN`, `INSTANCE_LOAD_REQUEST_PLAYERS`,
`INSTANCE_LOAD_REQUEST_ITEMS`, `CHAR_CREATION_REQUEST_PLAYER`,
`CHAR_CREATION_REQUEST_ARMORS`, `CHAR_CREATION_CHANGE_PROF`,
`CHAR_CREATION_CONFIRM`, `ITEM_UPDATE_EQUIPPED_COLOR`, `SEND_CHAT_MESSAGE`,
`MOVE_TO_COORD`, `CANCEL_MOVEMENT`, `LAST_POS_BEFORE_MOVE_CANCELED`, `DROP_ITEM`

### What that means in player terms

| Works (expected) | **Not implemented — do not expect it** |
|------------------|----------------------------------------|
| Login with a seeded account | **Combat / attacking** (no skill handlers at all) |
| Character creation (appearance, profession) | **Skills, energy/health regen in combat** |
| Character list, delete character | **NPCs** (no agent AI, no dialogue, no merchants) |
| Spawning into a map | **Quests** |
| Seeing other players move | **Party invites / forming a party** (`GmParty` only has `GmParty_AddPlayer`, called once at spawn) |
| Movement with server-side pathfinding | **Trading, dropping/taking items** other than the raw drop packet |
| Chat messages | **Death / resurrection** |
| Bags and items loaded from DB | **Portals / travelling between maps** |
| Ping / heartbeat | **Titles, skills, secondary profession logic** |

Phase 0 success must be measured against the left column only. A tester who
expects to kill a Charr in Phase 0 will file bugs that are really missing features.

## Phase 0 — out of scope

Explicitly **not** part of Phase 0. If you find yourself doing these, stop:

- Adding Pre-Searing map configs, spawn points, or fixing `last_outpost`
- Implementing any missing gameplay feature (combat, NPCs, quests, party)
- Performance/scaling work from `02-scaling-limitations.md` — **except** items
  that actually block testing (e.g. if logging drowns the test, fix logging)
- Refactoring the single-translation-unit build
- A real account/registration front-end (keep `webgate.py` as the dev stub)
- Multi-machine deployment

Changes allowed in Phase 0: build fixes, crash fixes, config/path fixes, and
*minimal* bug fixes needed to get a test to pass. Anything larger is recorded as
a finding and scheduled.

## Prerequisites (must all be true before T0)

| # | Item | Check |
|---|------|-------|
| P1 | `Gw.dat` present in repo root | `Test-Path Gw.dat` |
| P2 | Guild Wars client installed, patched to `Gw.custom.exe` | `python tools/patch-gw.py <Gw.exe> keys.txt` |
| P3 | `keys.txt` matches what got patched into the client | prime/private/public consistent |
| P4 | `portal.dll` built from `portal/portal.c` and placed next to the client | CMake target `portal` |
| P5 | `db/database.db` seeded | `./scripts/seed-db.ps1` |
| P6 | Server builds | `./scripts/build.ps1` |
| P7 | Py4GW tooling available for capture/verification (optional but strongly recommended) | See `06-client-tooling.md` |

If P1 or P2 is missing, Phase 0 cannot start — that is the first thing to sort
out, and it is the only true blocker.

## Tooling available for testing

Phase 0 does not have to be eyeballed. We have programmatic access to the real
client; see `06-client-tooling.md` for the full picture. The two things that
change this test plan:

**1. The packet sniffer is the oracle.** `PyPacketSniffer` captures both
directions with header, size, tick and raw bytes
(`Py4GW_Reforged_Native/include/GW/packet_sniffer/packet_sniffer.h`). So instead
of "does it look right", a test can be: run a scripted sequence, dump the packet
log, compare header-by-header against a golden capture. The first divergent
header is the bug, with a byte offset.

**2. The client's own state is readable.** Agents, players, party, items, map and
pathing contexts are all exposed, and the shared-memory cache lets a *separate*
process read them. A test can assert on what the client actually believes,
not on a screenshot.

Practical effect on the tests below:

- **T3/T7**: record the StoC log; assert the expected header sequence appears.
- **T9**: use `multibox` instead of launching two clients by hand — repeatable.
- **T10**: read agent positions from both clients; assert convergence.
- **T15** becomes scriptable: the log audit is a diff against the golden sequence.

Anything captured must record the `Gw.exe` build it came from, and must be
sanitised of player names/UUIDs before entering the repo — see the rules in
`06-client-tooling.md`.

## The test plan

Run in this order; each step depends on the one before. Record the result of each
in `docs/test-log.md` (append-only) with date, build hash, and log excerpt.

### T0 — Build and seed
```powershell
./scripts/build.ps1 -Clean
./scripts/seed-db.ps1 -Force
```
**Pass:** `gwps_server.exe` produced; `db/database.db` exists.

### T1 — Web gate works (no client needed)
Start `python tools/webgate.py`, then request the session-create endpoint.
**Pass:** an XML `<Reply><Session>GUID</Session></Reply>` comes back with a valid
UUID. This validates the login front without involving the game client at all.

### T2 — Server starts and binds
```powershell
./scripts/run.ps1
```
**Pass:** three `AuthSrv listen to '127.0.0.1:6112/6113/1337'` lines, process stays
alive, Ctrl+C exits.

### T3 — Handshake
Launch the patched client, attempt login.
**Pass:** server logs the connection and completes key exchange without
`Unhandled` or `Invalid riff type` errors; client proceeds to the login screen
past the version check.

### T4 — Account login
Log in as `user1@example.com`.
**Pass:** account row loaded from DB (no `Failed to open database`, no
`Couldn't load the account`); client reaches EULA or character list.

### T5 — EULA + character list
**Pass:** EULA accepted (`ACCEPT_EULA` path), character list renders (empty on a
fresh DB is fine).

### T6 — Character creation
Create a character (pick appearance + profession).
**Pass:** all of `CHAR_CREATION_REQUEST_PLAYER`, `_REQUEST_ARMORS`,
`_CHANGE_PROF`, `_CONFIRM` are handled with no `Unhandled GameSrv packet`; a row
appears in `characters`, plus `bags` and `items` rows for that character.
Verify directly:
```powershell
python -c "import sqlite3;c=sqlite3.connect('db/database.db');print(c.execute('select count(*) from characters').fetchone(), c.execute('select count(*) from bags').fetchone(), c.execute('select count(*) from items').fetchone())"
```

### T7 — Character select → map transfer → spawn
Select the character and enter the world.
**Pass:** auth server creates a game server (`AuthSrvCtrl_CreateServer`), the game
server loads Kamadan (`GameSrv_LoadMap`), the client receives the spawn message
and renders the world with the player standing at the configured coordinate
`(-9067, 13218)`.

### T8 — No crash on the only configured map
**Pass:** log contains no `No config for map ... falling back to default` for
Kamadan, and `Invalid riff type` does not appear. This confirms `map_file_id
0x345CC` and the archive reader agree.

### T9 — Second client sees the first
Run a second patched client with a different account (use the mutex patch from
`patch-gw.py` so both can run at once). Log in, enter the same outpost.
**Pass:** each client sees the other player's agent; both see movement of the
other.

### T10 — Movement and pathfinding
Walk to a valid point; then try walking into a wall/prop; then walk across a
portal between pathing planes if Kamadan has one.
**Pass:** movement is accepted, the other client sees it smoothly, and invalid
destinations are rejected rather than teleporting the player.

### T11 — Chat
Send a local chat message.
**Pass:** both clients display it; no `Unhandled` for `SEND_CHAT_MESSAGE`.

### T12 — Item drop
Drop an item from a bag.
**Pass:** `DROP_ITEM` handled, item entity appears/disappears consistently for
both clients, DB state still coherent.

### T13 — Stability
Leave both clients connected for 10 minutes idle.
**Pass:** no crash, `PING_REQUEST`/`PING_REPLY` cycle continues
(`GAME_SRV_TIME_BETWEEN_PING_MS = 5000`), memory roughly flat.

### T14 — Disconnect and reconnect
Close a client, then log back in.
**Pass:** the game server notices the disconnect, removes the agent, and a fresh
login succeeds. **Known risk:** the auth server keeps `GlobalAccountRegistry` in
RAM (`AuthSrv.h:156`) and there is no graceful shutdown, so a *server* restart
(rather than a client reconnect) is expected to misbehave — record it, don't fix
it in Phase 0.

### T15 — Log audit
Grep the whole session log for gaps:
```powershell
Select-String -Path <log> -Pattern 'Unhandled \w+ packet'
```
**Pass:** every occurrence is understood and recorded as a known-missing feature
(not a bug). Anything unexpected becomes a finding.

## Findings policy

For each problem found, record in `docs/test-log.md`:

```
### F<n> — <one line>
Step:      T7
Symptom:   <what happened>
Evidence:  <log line / capture>
Class:     blocking | bug | missing-feature | by-design
Action:    fix now | schedule (phase) | document only
```

Only `blocking` gets fixed inside Phase 0.

## Exit criteria for Phase 0

All of the following, and nothing less:

1. T0–T8 pass: one client logs in, creates a character, and spawns in Kamadan.
2. T9–T12 pass: two clients see each other, walk, chat, and drop an item.
3. T13–T14 pass with documented caveats.
4. `docs/test-log.md` exists and lists every finding with a class.
5. No `Unhandled` packet in the log is unexplained.
6. The build is reproducible from a clean clone (`scripts/build.ps1 -Clean`).

Then, and only then, Phase 1 starts with the map `map_file_id` hunt described in
`05-reverse-engineering.md`.
