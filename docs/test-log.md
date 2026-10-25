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
  `build/RelWithDebInfo/presearing_server.exe`.
- `presearing_tests.exe` also builds (`-Tests`).
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

- built `presearing_server.exe` and `portal.dll`
- `db/database.db` already seeded (left untouched)
- copied `Gw.dat` (3,486 MB) into the repo root -- the server opens it relative to
  its working directory (`GameSrv.c:103`)
- patched `F:\GW\GW1\Gw.exe` -> `Gw.custom.exe`: DH keys found at `0xa945a0`
  (RVA `0x6945a0`), mutex `AN-Mutex-Window` -> `AN-Futex`
- staged `portal.dll` next to `Gw.custom.exe`

Remaining Phase 0 work is T3 onward: all require launching the patched client.
