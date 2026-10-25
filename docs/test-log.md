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
