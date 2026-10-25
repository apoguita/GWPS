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

---

## Probe — navmesh fingerprint to find map 148's blob — **NO MATCH** — 2026-10-24

Goal: identify `GmMapConfig.map_file_id` for Ascalon City (pre-Searing), map 148, by
matching the client's live navmesh against the 213 map blobs in `Gw.dat`.

Tools built for it: `tools/gwdat-pathing.c` (CMake target `gwdat_pathing`) parses
each blob with the server's own `GmImportMap` and prints
`file_id,size,planes,trapezoids,min_x,min_y,max_x,max_y`; `tools/probe-pathing.py`
reads the same fingerprint from the live client via `Map.Pathing.GetPathingMaps()`.

### What worked

- **The client is confirmed in map 148** — `Map.GetMapID()` = 148,
  `Map.GetMapName` = "Ascalon City (pre-Searing)", pid 33540.
- **A spawn point, which is requirement #2:** the player stands at
  **(9541.873, 4796.456)**. That is a coordinate the map is known to accept.
- **The fingerprints are perfectly discriminating.** All 426 RIFF map blobs
  fingerprint (213 maps x 2 copies), and they collapse to exactly **213 distinct
  fingerprints, all pairs, zero collisions**. A match would have been unambiguous.

### What failed, and why it is informative

The client's fingerprint for map 148 — **58 planes, 6120 trapezoids, bounds
(-18432, -24576) .. (21504, 24576)** — matches **none** of the 213 blobs.

The reason is not the sheet: it is that **our importer extracts far fewer
trapezoids than the client holds.** Kamadan (`0x345CC`), the one map that is known
to work end to end, parses to **39 planes / 1270 trapezoids** in our own code path,
while the client's numbers for a comparable outpost are in the thousands. So
`PathImport_ReadPlanes` reads a subset — enough for the server's own movement to
function, not the same set the client builds. The fingerprint was comparing a
subset against a superset.

Finding **F11 — the pathing importer reads a subset of the navmesh.** Class: bug
(upstream data import). Action: schedule — it does not block Phase 0 (movement works
against the subset), but it does block fingerprint-based blob identification, and it
is a real risk for pathing fidelity in Pre-Searing maps with more vertical structure.

### Consequence

Route A (fingerprint matching) is closed until F11 is fixed or a comparable
extraction exists. The identification must come from **observing the open**:
hook `OpenFileByFileId` (resolver `gw_dat_reader.open_file_anchor` already exists in
Py4GW_Stealth), reload the map, and read `(map_id -> file_id, stream_id)` — the
method `06-client-tooling.md` proposed in the first place.

### Follow-up: containment matching also fails, which changes the diagnosis

The client's full trapezoid list was then dumped (`--dump-trapezoids`, 6120 rows for
map 148) and matched against every trapezoid our importer reads from all 426 blobs
(`gwdat_pathing --trapezoids`, 1.37 M rows, 213 distinct maps):

| Test | Result |
|------|--------|
| exact containment (blob set in client set) | **0 shared trapezoids, every blob** |
| order-insensitive (bag of six coordinates per trapezoid) | 0 — rules out a field-order bug |
| 48-unit tolerance, best candidates by bounding box | 0 of 6120 near-matches |

So this is **not** "our importer reads a subset", which is what F11 guessed. Even as
an unordered bag of numbers, the client's geometry has no counterpart in any RIFF map
blob. `0x000265F1` comes closest by bounding box — `(-18432, -24576, 21504, 25080)`
against the client's `(-18432, -24576, 21504, 24576)` — and still shares nothing.

**F12 — map 148's geometry is not in any of the 426 RIFF map blobs.** Class:
blocking for blob-based identification. The 213 maps in `Gw.dat` do not include
Ascalon City (pre-Searing), so either its data lives in a container that is not
`RIFF_MAP2`, or the id we need is not a map blob at all. Every "no config, falling
back to Kamadan" map may be in this category, which would make the milestone-1 plan
(map -> blob id) wrong in principle rather than merely unfinished.

Next, and it does not depend on our parser: search **every decompressed file** in
`Gw.dat` for the float32 bytes of a distinctive client trapezoid. That names the file
id regardless of container type.

### CORRECTION — F12 was my scan window, not the archive; map 148 is found

The float search above is what settled it. `gwdat_pathing --find-floats` takes float
pairs straight out of the client dump — `(yt,yb)`, `(xtl,xtr)`, `(xbl,xbr)` — and
scans all 146 901 decompressed ids for them. Result: **exactly two files match 25 of
48 patterns**, `0x0001B97D` and `0x0005E9E4` (2 925 267 bytes each — the two stored
copies of one map). Loading either through `GmImportMap` reproduces the client's
fingerprint **exactly**: 58 planes, 6120 trapezoids, bounds
`(-18432, -24576) .. (21504, 24576)`.

So F12 is withdrawn as stated: the geometry *is* in the archive, and our importer
parses it *correctly*. The containment test failed because the fingerprint sheet was
built with a `--min-size 4096` filter on the **compressed** MFT entry size — and a map
can compress below that floor. `0x0001B97D` (2.9 MB decompressed) never entered the
sheet, so the matcher had nothing to match. **The bug was in my tooling, not in
`Gw.dat` or in `GmImportMap`.** Same class as the earlier `--min-size 400000` mistake
in this session: filtering on compressed size to select maps is wrong by construction.

F11 is also withdrawn for this map: 58 planes / 6120 trapezoids is the client's own
count, so the importer read the whole navmesh. Whether it under-reads *other* maps is
untested and unproven.

### Map 148 is configured

```c
GmMapConfig s_AscalonCityPreSearing = {
    .map_id      = MapId_AscalonCityPreSearing,   // 148
    .map_file_id = 0x1B97D,
    .n_spawnpoints = 1,
    .spawnpoints = { { 9541.873f, 4796.456f, 0 } },
};
```

Spawn point = where the live client stood (`Player.GetXY()`). The plane is
**unverified** (assumed 0); the 0x3D stream corrects it on the first report.

`db/database.db` now has the existing character's `last_outpost = 148`, and
`gwps_server.exe` rebuilds and binds 6112/6113/1337. **Not yet exercised:** a client
logging into our server and standing in Ascalon City (pre). That is the next test.

---

## T7-variant — load a Pre-Searing map — **PASS** — 2026-10-25 — `13d040b`

Tester launched the patched client against the GWPS server with the character's
`last_outpost = 148` and **loaded into Ascalon City (pre-Searing)**. Milestone 1's
first map is real.

What this proves:

- `map_file_id = 0x1B97D` is correct — the server found the blob, `GmImportMap`
  parsed it, and the client accepted the instance rather than falling back to Kamadan.
- The spawn point `(9541.873, 4796.456)` is inside the map's walkable area.
- The float-search identification method works end to end, not just in the file dump.

What it does **not** yet prove:

- that the spawn **plane** (assumed 0, unverified) is right — the tester was not
  asked to check for a visible vertical displacement;
- anything about the other seven Pre-Searing maps.

### The repeatable procedure this establishes

Per map, and it is now mechanical:

1. Stand the live client in the map.
2. `py tools/probe-pathing.py --dump-trapezoids build/<map>.csv` (elevated) — prints
   the client's fingerprint and, once the sheet covers the whole archive, the matching
   blob directly.
3. Fall back to `gwdat_pathing Gw.dat --find-floats build/<map>.csv` when the sheet
   has no match: float pairs straight from the client, scanned across all 146 901 ids.
   It found map 148 in one pass after the fingerprint approach was mistuned.
4. Add the `GmMapConfig` entry with the file id and the player's own position as the
   spawn point.

**Do not filter the archive by compressed MFT size when hunting maps.** That mistake
cost two wrong findings (F11, F12) in this session: Kamadan compresses to 4 980 bytes
for 1.7 MB, and map 148 to under 4 KB of its 2.9 MB. Use `--min-size 0`.

### Note on why blob content cannot shortcut this

A blob carries no map identity: map 148's `name_id` (10478) appears once by
coincidence inside an index table of small integers, and Kamadan's `name_id` (24707)
does not appear at all. There are no map-name strings either (no `Ascalon`, in ASCII or
UTF-16). So `map_id -> file_id` is not derivable offline from the archive; it has to be
observed once per map.

---

## Probe — the fast path, against the live patched client — PASS — 2026-10-25 — `4e4198a`

Ran `tools/probe-pathing.py` against the client that was logged into the GWPS server,
and it closed three open items at once.

**Found a bug first.** The probe reported "no Gw.exe is running" while a client was
plainly connected. `Win32.find_guild_wars()` matches the executable name `Gw.exe`, and
GWPS tests run the **patched** client, `Gw.custom.exe` — invisible to that matcher.
Fixed: discovery now falls back to any process whose name starts with `gw` (excluding
`gwps_server`), and `--pid` skips discovery entirely. This is the same class of mistake
as the compressed-size filter: a tool that silently could not see its own subject.

**The fast path works.** With a fingerprint sheet that has no size floor, the probe
matched the loaded map to exactly two blobs — `0x0001B97D` and `0x0005E9E4`, the pair
already in `GmMapsConfig.c` — in one run, with no float search needed:

```
map 148 (Ascalon City (pre-Searing))
  player position  9536.206, 4709.885   (agent 1, plane 0)
  fingerprint      planes=58 trapezoids=6120 bounds=(-18432,-24576)..(21504,24576)
  2 matching blob(s): 0x0001B97D, 0x0005E9E4
```

**The spawn plane is verified.** It was the one value in the config marked as a guess.
Read back from the standing character with `Agent.GetZPlane`: **plane 0**, which is what
the config assumes. Combined with the tester's confirmation that the character lands in
exactly the right place, `s_AscalonCityPreSearing` is now fully verified rather than
partly assumed.

Per-map cost is now: one client visit, one command, and the blob id falls out.

---

## T7-variant 2 -- Lakeside County loads -- **PASS**, and the blob is shared -- 2026-10-25 -- `64c6641`

Tester logged into the GWPS server with `last_outpost = 146` and **spawned exactly where
they should in Lakeside County**, using the same `map_file_id` as Ascalon City:
`0x1B97D`, spawn `(6602, 4485, plane 0)`.

**This is a design fact, not a lucky guess.** Two maps with different types -- 148 is an
outpost (type 10), 146 an explorable (type 2) -- load from one blob, and the map id plus
the spawn coordinate select the place inside it.

It also retires the ambiguity that stalled the probe: Lakeside's navmesh fingerprint
being identical to Ascalon City's was *correct*, not stale. `Map.Pathing.GetPathingMaps()`
was telling the truth both times.

Consequences this establishes:

1. **`map_file_id` is not one-per-map.** Several map ids share a region blob. The
   fingerprint identifies the *region file*; the map id and spawn point choose the spot.
   So a fingerprint match proves "this blob holds the geometry the client is using",
   never "this blob is this map".
2. **The remaining Pre-Searing maps are likely the same blob.** Ascalon City and
   Lakeside County already share it; whether Regent Valley, Green Hills, Wizard's
   Folly, the Catacombs and the Northlands do is now a cheap question -- try
   `0x1B97D` with a spawn point read from the live client, and look at the terrain.
3. Milestone 1's exit criteria -- a character logs in, spawns at a valid point, and sees
   terrain in **Ascalon City (pre) and Lakeside County** -- are **met**.

---

## Pre-Searing census -- all eleven maps read from the live client -- 2026-10-25

The tester walked pre-Searing on the live client and ran `tools/probe-pathing.py` in
every map (plus the three outposts that were missing from the original eight). Each row
below is a read from the client's own pathing records; `exact` means the blob's
`GmImportMap` fingerprint matches it in planes, trapezoid count and bounds.

| Map | id | planes/traps | Blob (twin) | Match |
|-----|----|--------------|-------------|-------|
| Ascalon City (pre) | 148 | 58 / 6120 | 0x1B97D (0x5E9E4) | exact |
| Lakeside County | 146 | 58 / 6120 | 0x1B97D (0x5E9E4) | exact |
| Ashford Abbey | 164 | 58 / 6120 | 0x1B97D (0x5E9E4) | exact |
| The Catacombs | 145 | 51 / 5246 | 0x5CEE6 (0x1C530) | exact |
| Green Hills County | 160 | 45 / 4772 | 0x5CF29 (0x1BA26) | exact |
| The Barradin Estate | 163 | 45 / 4772 | 0x5CF29 (0x1BA26) | exact |
| Wizard's Folly | 161 | 18 / 5241 | 0x5CEE7 (0x1BACB) | exact |
| Foibles Fair | 165 | 18 / 5241 | 0x5CEE7 (0x1BACB) | exact |
| Regent Valley (pre) | 162 | 24 / 5267 | 0x5CF2A (0x1BB1D) | exact |
| Fort Ranik | 166 | 24 / 5267 | 0x5CF2A (0x1BB1D) | exact |
| The Northlands | 147 | 48 / 6889 | 0x8005EA96 (0x8001C539) | **near** (6890) |

**The structure this reveals: five region blobs, each shared by an outpost and the
explorable it opens onto.** Ashford Abbey joins Ascalon City and Lakeside County on
0x1B97D; Barradin Estate shares with Green Hills; Foibles Fair with Wizard's Folly;
Fort Ranik with Regent Valley. The Catacombs and The Northlands are alone.

That is why the earlier "identical fingerprint" alarm was a false one: two maps sharing
a blob is the design, not a stale read. It also means `map_file_id` identifies a
*region*, and the map id plus spawn point choose the place inside it.

All eleven spawn points were captured with their plane (0 in every case). Configs are in
`GmMapsConfig.c` for all of them, including the three outposts that were not in the
original eight-map list; only Ascalon City and Lakeside County have been loaded on the
GWPS server so far.
