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
