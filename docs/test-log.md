# Phase 0 test log

Append-only. One entry per test from `04-scope.md`. Never edit past entries —
add a new dated entry instead.

Format per test:
```
## T<n> — <name> — <PASS|FAIL|BLOCKED> — <YYYY-MM-DD> — <git short hash>
Command:  <what was run>
Observed: <what happened>
Evidence: <log excerpt / screenshot path>
Findings: <F-numbers, or "none">
```

---

## T0 — Build and seed — PASS — 2026-10-24 — `776e96b`

Command:
```powershell
./scripts/build.ps1 -Clean
./scripts/seed-db.ps1 -Force
```

Observed:
- `scripts/build.ps1 -Clean` configured with the Visual Studio 17 2022 generator
  (MSVC 19.42.34435.0) and produced
  `build/RelWithDebInfo/gwps_server.exe`.
- `gwps_tests.exe` also builds (`-Tests`).
- `portal.dll` builds via `cmake --build build --target portal`.
- `scripts/seed-db.ps1 -Force` created `db/database.db` from `db/seed.sql`.
- Smoke run: server started, logged
  `AuthSrv listen to '127.0.0.1:6112'`, `:6113`, `:1337`, and stayed alive.

Evidence: build output; stderr of the smoke run.

Findings: none.

Note: this only proves the binary builds and binds. It does **not** prove a client
can connect — that starts at T1.

---

## T1 — Web gate works — BLOCKED (no client needed, but not yet run)

Prerequisites: Python 3.9+.

---

## T2 — Server starts and binds — PASS (partial) — 2026-10-24 — `776e96b`

Covered by the T0 smoke run: all three listeners came up. Still to confirm:
clean `Ctrl+C` exit and `sys_free()` without a warning.

---

## T3 — Handshake — BLOCKED

Blocked on prerequisites P1 (`Gw.dat`) and P2 (patched client). Cannot be tested
without a real Guild Wars client installation.

---

## T4–T14 — BLOCKED

All blocked on the same two prerequisites. See `04-scope.md` → "Prerequisites".

---

## Open findings

| F# | Step | Symptom | Class | Action |
|----|------|---------|-------|--------|
| —  | —    | none yet | — | — |

---

## Tooling probe — AreaInfo / map_file_id — PARTIAL — 2026-10-24 — `90d03b2`

Command (elevated, Stealth read-only attach to `Gw.exe` pid 16012):
```powershell
python tools/dump-map-table.py --json build/map-table.json
python tools/gwdat-mft.py F:\GW\GW1\Gw.dat
```

Observed:
- `map.area_info_addr` resolves; base `0xE7CF00`, stride `0x7C`.
- Cross-check passes exactly: `base + 5*0x7C = 0xE7D16C` ==
  `InstanceInfo.current_map_info_ptr` while the client sat in map id 5.
- `region`/`type` fields are correct for every entry.
- **21 maps** have `region == Presearing` (census recorded in
  `06-client-tooling.md`); four were missing from the hand-written roadmap list
  (163 Barradin Estate, 165 Foibles Fair, 143, 779).
- `AreaInfo.file_id` is the same quantity as `GmMapConfig.map_file_id`: Kamadan's
  `0x345CC` decomposes to `file_id1=0x49CB / file_id2=0x103` under the client's
  own formula.
- **`file_id` is lazily populated.** 740/899 entries read 0; the 159 populated
  ones sit in bands `file_id2` 0x100-0x105. None of the six configured maps was
  populated while the client idled in a Guild Hall.
- `tools/gwdat-mft.py` could NOT run: `Gw.exe` holds an exclusive lock on
  `Gw.dat` (sharing violation even with `FILE_SHARE_READ|FILE_SHARE_WRITE`).

Findings:
- F1 — `MapMethods.GetMapInfo(map_id)` returns `None` for most ids on this build
  (Lion's Arch, Kamadan, all Pre-Searing) even though the underlying read of the
  same address succeeds. Class: bug (upstream tooling). Action: `dump-map-table.py`
  now reads the array directly instead; worth a note upstream.
- F2 — `Gw.dat` cannot be parsed while the client is running. Class: by-design.
  Action: close the client, then run `tools/gwdat-mft.py`.

Next: close the client and parse `Gw.dat` to get every archive file id in one
pass, or travel to each map and let the dump merge.

---

## Gw.dat archive scan — PASS — 2026-10-24 — `55f31ba`

Client was closed to release its exclusive lock on `F:\GW\GW1\Gw.dat`.

Command:
```powershell
cmake --build build --config RelWithDebInfo --target gwdat_scan
.\build\RelWithDebInfo\gwdat_scan.exe F:\GW\GW1\Gw.dat > build\maps-scan.csv
```

Observed:
- Archive parses: magic `0x1A4E4133`, `mft_offset 0xD82B9A00`, 155238 MFT
  entries, 146695 file ids, 3.66 GB.
- 75 656 entries in the 4 KB-8 MB size window were decompressed; **426 are
  RIFF map blobs = 213 maps x 2 copies** (every size appears exactly twice).
- Kamadan `0x345CC` decompresses to 1 734 079 B, `RIFF_MAP2`, 24 chunks, and
  chunk `0x20000008` (stage 2 Path) starts `4C70FEEE 0C000000` =
  `PATH_DATA_SIGNATURE` / `PATH_DATA_VERSION`. Full reader + decompressor path
  validated against the server's own code.
- Results committed as `data/gwdat-maps.csv`.

Findings:
- F3 — **Three shipped `GmMapConfig` entries are not map blobs.** Lion's Arch
  `0x56228`, Kaineng Center `0x265F7` and Lornar's Pass `0xB602` all exist in the
  MFT but are not RIFF maps, so `GameSrv_LoadMap` would fail on them. Kamadan,
  Domain of Anguish and Sparkfly Swamp are correct. Class: bug (upstream data).
  Action: replace those three values, or drop the configs.
- F4 — `AreaInfo.file_id` is not a guaranteed alias for the map geometry id: for
  guild halls it resolved to a ~31 KB stream-0 entry, not a map blob. Class:
  by-design (different identifier). Action: observe `OpenFileByFileId` instead.

Still open: assigning blob ids to map ids for Pre-Searing. See
`06-client-tooling.md` -> "Still open".

---

## Pre-Searing load probe — NEGATIVE RESULT (useful) — 2026-10-24 — `d2f0b35`

Client logged in at **map 148, Ascalon City (pre-Searing)**, region 7, type 10.

Command (elevated, read-only):
```powershell
python tools/probe-current-map.py
```

Observed:
- `Map.GetMapID()` = 148; `InstanceInfo.current_map_info` gives region 7, type 10,
  name_id 10478 — the map is genuinely loaded and correct.
- **`AreaInfo[148].file_id` is still 0**, both through the InstanceInfo pointer and
  through a direct array walk.
- Of the 159 populated entries, **zero** appear in the 426-blob map list.

Finding:
- F5 — `AreaInfo.file_id` is not the map geometry id, and `file_id1`/`file_id2` do
  not derive it. Loading the map does not populate it. Class: by-design (different
  identifier). Action: correct `06-client-tooling.md` (done) and do not use it to
  fill `GmMapConfig`.
- F6 — The AreaInfo array is shorter than 900 entries: ids 898/899 read garbage
  (`region = 1130133319`). Action: bound scans below ~898.

---

## T1 — Web gate — PASS — 2026-10-25 — `68da4a4`

`python tools/webgate.py` serves plain HTTP on port 6601 (no TLS, despite the
`import ssl`). Full flow exercised with a second process:

```
GET  /Spawned/WebGate/session/create.xml
  -> 200  <Reply><Session>D5B6A144-8908-4A30-930A-7CD58E075249</Session></Reply>
POST /Spawned/WebGate/users/login.xml   (Authorization: Arena <session>)
  -> 200  <UserId>FA520EE2-4419-4EB4-AE49-6E9ABE6EF24F</UserId>
          <LoginName>user1@example.com</LoginName>
```

The returned UserId matches the `user1@example.com` entry hardcoded in
`tools/webgate.py:6`. Session, login and user resolution all work.

Findings: none.

---

## T2 — Server binds — PASS — 2026-10-25 — `68da4a4`

```
[..] info: AuthSrv listen to '127.0.0.1:6112'
[..] info: AuthSrv listen to '127.0.0.1:6113'
[..] info: AuthSrv listen to '127.0.0.1:1337'
```
Process stays alive; still to confirm clean Ctrl+C exit and that `sys_free()`
reports no warning.

---

## Prerequisites P1–P6 — PASS — 2026-10-25

`./scripts/phase0-prepare.ps1` completed all five steps:

- built `gwps_server.exe` and `portal.dll`
- `db/database.db` already seeded (left untouched)
- copied `Gw.dat` (3,486 MB) into the repo root -- the server opens it relative to
  its working directory (`GameSrv.c:103`)
- patched `F:\GW\GW1\Gw.exe` -> `Gw.custom.exe`: DH keys found at `0xa945a0`
  (RVA `0x6945a0`), mutex `AN-Mutex-Window` -> `AN-Futex`
- staged `portal.dll` next to `Gw.custom.exe`

Remaining Phase 0 work is T3 onward: all require launching the patched client.

---

# PHASE 0 CORE — PASS — 2026-10-25 — `a1e8266`

Tester: logged in with `user1@example.com`, created a character, entered the
world, moved around, and interacted with items. **The stack works end to end.**

## Evidence from the server log

| Step | Evidence | Result |
|------|----------|--------|
| T3 handshake | `Accepted Auth connection 0009`; `User login user id: fa520ee2-... session id: d8b9bf5d-...` | PASS |
| T4 account login | session/account resolved from DB, no DB errors | PASS |
| T6 char creation | no char-creation failures logged | PASS (tester confirms) |
| T7 spawn | `Server 2072167476 started...`, `Accepted Ctrl connection`, `GAME_CMSG_INSTANCE_LOAD_REQUEST_ITEMS`, `_PLAYERS`, `Unhandled ... 10`, `11` | PASS |
| T8 no-map-fallback | **no** `No config for map ... falling back to default` line | PASS |
| T10 movement | accepted, but position corrections rejected -- see F7 | PARTIAL |
| T12 item drop | `TODO: we must still implement this` (`GmInventory.c:276`) | PARTIAL |
| T9/T11/T13/T14 | not exercised in this session | NOT TESTED |

No crash, no `abort()`, no `Invalid riff type`, no database errors.

## Triage of every unhandled header

Field layouts are from `code/OpenTyria/msgdefs.info`; names from `opcodes.h`.

| Header | Layout | Identification | Class |
|--------|--------|----------------|-------|
| Auth `0x23` (35) | `DWORD` | `AUTH_CMSG_0023`; sent once at auth connect | missing-feature (benign) |
| Game `0x0A` (10) | `BLOB(16) + 6x DWORD` | `GAME_CMSG_0010`; sent once at game connect | missing-feature |
| Game `0x0B` (11) | `BLOB(16) + 4x DWORD + STR16(16) + STR16(128)` | `GAME_CMSG_0011`; looks like player/account info at game connect | missing-feature |
| Game `0x3D` (61) | `VECT2, DWORD, VECT2, DWORD` | **position update** -- sits directly before `GAME_CMSG_MOVE_TO_COORD` (`0x003E`) and carries `pos2d, plane, dir2d`. Fires ~2 Hz | **defect, see F7** |
| Game `0x7E` (126) | `DWORD` | `GAME_CMSG_ITEM_USE` | missing-feature |
| Auth `0x20`/`0x21` | -- | `AUTH_CMSG_SETTING_UPDATE_CONTENT` / `_SIZE`; UI settings on exit | by-design |

### F7 -- position updates are ignored, which is why corrections get rejected

The client streams its actual position in `0x3D` about twice a second. `GameSrv`
does not handle it, so the server's `agent->position` only advances from
`MOVE_TO_COORD` (`0x003E`) destinations and pathing. The two views drift apart,
and every attempt to correct lands here:

```c
// GmAgent.c:481-487
if (msg->plane != agent->position.plane ||
    MAXIMUM_ALLOWED_CORRECTION < Vec2f_Dist2(agent->position.v2, msg->pos)) {
    log_warn("Player %u tried to correct the position by more than allowed", player_id);
    return ERR_OK;
}
```

Observed 8 times in a ~60 second session.

- Class: **bug caused by a missing-feature** (`0x3D` unhandled)
- Action: handle `0x3D` -- update `agent->position` (validated against plane and a
  distance bound) instead of discarding it. Small, self-contained, and it removes
  both the log spam and the drift. Recommended as the first post-Phase-0 change.

### F8 -- dropping a partial stack is unimplemented

```c
// GmInventory.c:274-278
if (msg->count < item->quantity) {
    // GmItem *new_item = GameSrv_AllocateItem(srv);
    log_warn("TODO: we must still implement this");
```

Dropping fewer than the whole stack is a no-op. Class: missing-feature.
Action: schedule (Phase 1), not a Phase 0 blocker.

## Verdict

Phase 0 exit criteria 1-3 are met: one client logs in, creates a character, spawns
in Kamadan, and moves; no unexplained crash. Criteria 4-6 remain: T9/T11/T13/T14
(two clients, chat, stability, reconnect) have not been exercised yet.

---

## Tooling — packet sniffer ported into Py4GW_Stealth — PASS — 2026-10-24

The packet sniffer, until now only available inside Reforged's injected `Py4GW.dll`,
is ported to `Py4GW_Stealth` (`py4gw/packet_sniffer.py` over
`py4gw/native_src/packets/py_packet_sniffer.py`) and live-verified in both
directions. This is the copy GWPS tests should use: it captures from a separate
process and needs no injected DLL.

Evidence — `Py4GW_Stealth/tests/live_reports/live_all.log`, `Gw.exe` pid 6616,
client build 39112:

```
--- connected to pid 6616; block at 0x0DA80000..0x0DB2A640; capture area at +0x448 (4096 bytes)
--- captured StoC 0x001E size=8 copied=8 head=1e 00 00 00 fd 01 00 00
--- outbound capture: 1 stub hit(s), 1 logged
--- captured CToS 0x0039 size=12 copied=12 head=39 00 00 00 12 00 00 00 00 00 00 00
--- disconnected from pid 6616
```

Every replaced handler entry was restored and the array verified byte-identical;
client stayed alive. Suite: 5 tests, 1 skipped (narrow capture saw no traffic),
`OK (skipped=1)`.

**Requirement: an elevated shell (one UAC prompt).** `py4gw.connect()` asserts
elevation because connecting is a write — block, dispatcher, hooks. A process
cannot raise its own token, so the shell must be started as administrator.
Documented in `06-client-tooling.md` → "Where we actually run it".

Consequence for Phase 0: T3/T7/T10/T12/T15 can assert on captured bytes instead of
on a screenshot. First target is F7 — confirm `0x3D` is 28 bytes on the wire
(4-byte header + our 24-byte payload, matching `KNOWN_CTOS_LENGTHS[0x3D]` and
`{61, 5, GAME_CMSG_0061, 26}`) and identify the second vector.

Findings: none of ours. Two hazards recorded rather than fixed here:

- an unattributed injected-code crash on the first live attempt (`c0000005` writing
  `0x096D1000` from `0x096D0FFF` while Reforged's "Travel On Character Load" ran),
  which is why the suite is staged for attribution;
- a second runtime rewriting handler entries after the restore, so **run one
  sniffer at a time** and read an entry mismatch as another runtime's, not as a
  failed restore.

---

## Live capture — packet sniffer, both directions — PASS — 2026-10-24 — `d718b2d`

Command (elevated shell, one UAC prompt approved):

```powershell
python tools/sniff-capture.py --seconds 20 --dir both --out captures/live-20261024-212230.jsonl
```

Observed:

- client `Gw.exe` pid 33540 (`F:\GW\GW1\Gw.exe`); 711 packets in **28.5 s**, both
  directions, 34 distinct headers; sanitised output; exit 0; client alive.
- heaviest: `StoC 0x001E WORLD_SIMULATION_TICK` 276, `StoC 0x009F
  AGENT_PROPERTY_UPDATE_INT` 53, `StoC 0x0029 AGENT_MOVE_TO_POINT` 45,
  `StoC 0x0020 WORLD_CREATE_AGENT` 34.
- outbound: `CToS 0x003D` x10, `CToS 0x0039 INTERACT_LIVING` x1.

**Scope note — this is a golden capture, not a pass for our stack.** The GWPS server
was not running (nothing listening on 6112/6113), so the traffic is a stock client
against a live server. That is exactly the reference capture the test plan wants;
it says nothing about our game server yet.

### F7 — RESOLVED: `0x3D` is 28 bytes of position + plane + heading

Ten packets, all `size = 28`:

```
3d 00 00 00 | 34 23 1b 46 | 24 ec df c3 | 00 00 00 00 | 5c b2 05 44 | 9c a7 09 44 | 01 00 00 00
header      | pos.x       | pos.y       | plane       | dir.x       | dir.y       | flag
```

- 28 bytes on the wire = 4-byte header + **the 24-byte payload our struct already
  has**. `GameSrv_PositionUpdate` (2-byte header + `pos`, `plane`, `unknown_vec`,
  `unknown` = 26) and the format table entry `{61, 5, GAME_CMSG_0061, 26}` both
  agree with the capture. The handler parses the right layout.
- `unknown_vec` is a **heading**: magnitude is a constant 765.02 in 9 of 10 packets,
  and normalised it equals the travel direction between consecutive reports
  (`Δ = (170.6, 175.6)` → `(0.6970, 0.7172)` vs `dir` → `(0.6967, 0.7173)`).
- It is a **position report, not a move order**: position advances at 278–302 u/s and
  each report trails the `AGENT_MOVE_TO_POINT` (`0x29`) waypoints the same agent is
  following. `0x003E MOVE_TO_COORD` never appeared.
- `plane` was 0 and 22 in the same run; the trailing dword was `1` every time.
- Rate while walking: ~0.36 Hz, not the ~2 Hz F7 assumed from our server's log.

### F9 — our name for `0x3D` differs from the client's table

The client's own table calls header 61 `MOVE_TO_COORD_WITH_DIR`; `opcodes.h` calls it
`GAME_CMSG_POSITION_UPDATE`. The captured payload is a position report, so our name
describes it better — but anyone cross-referencing client tooling will see theirs.

Class: naming. Action: rename the struct's `unknown_vec`/`unknown` to what the
capture shows (`direction`, `flag`) with a comment — a code change plus rebuild,
scheduled rather than done here.

### F10 — the capture recorded a useless build identifier

The tool read the client "build" from the executable's version resource, which reads
`1.0.0.1` on this install while the tooling documents itself against build `39112`.

Class: bug (tooling). Action: fixed — the capture header now records
`sha256` + `file_version` + `size`, and the hash is what identifies a build.
