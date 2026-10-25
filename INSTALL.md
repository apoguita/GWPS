# Installing GWPS

Everything needed to go from a fresh checkout to a character walking around Pre-Searing Ascalon,
including the one decision that is genuinely yours to make: whether the client is allowed to keep
its normal connections to ArenaNet open.

`docs/09-client-connections.md` explains *why* that choice exists and what each connection
carries. This page is the how.

- [1. Requirements](#1-requirements)
- [2. Build the server](#2-build-the-server)
- [3. Seed the database](#3-seed-the-database)
- [4. Run the server](#4-run-the-server)
- [5. Prepare the client](#5-prepare-the-client)
- [6. Network mode: open or closed](#6-network-mode-open-or-closed)
- [7. Verify it works](#7-verify-it-works)
- [8. Troubleshooting](#8-troubleshooting)
- [9. Undo everything](#9-undo-everything)

## 1. Requirements

| Need | Why | How |
|------|-----|-----|
| Windows 10/11 x64 | The server and the client tooling target Windows | — |
| CMake ≥ 3.20 | Build | `winget install Kitware.CMake` |
| Visual Studio 2022 (C++ workload) or Build Tools | MSVC compiler | `winget install Microsoft.VisualStudio.2022.BuildTools` |
| Python 3.9+ | Client patching, DB seeding, some tooling | `winget install Python.Python.3.12` |
| Guild Wars client | To play; the Reforged client is what this was developed against | — |
| `Gw.dat` from that installation | Map and asset data is read from it. **Never committed** | Copy it to the repo root |
| `openssl` on `PATH` | Generates the Diffie-Hellman parameters | Ships with Git for Windows |

Ports used, all on loopback: **6112** (auth + game), **6113** (auth data), **1337** (internal
control between the auth server and the game servers).

## 2. Build the server

```powershell
git clone https://github.com/apoguita/GWPS
cd GWPS
./scripts/build.ps1
```

Output: `build\RelWithDebInfo\gwps_server.exe`. Build the optional pieces as needed:

```powershell
cmake --build build --config RelWithDebInfo --target gwps_dns    # needed only for closed network mode
cmake --build build --config RelWithDebInfo --target gwps_tests  # wire-format checks
```

`gwps_tests` runs under `NDEBUG` with explicit checks, so it is worth running after touching
message definitions:

```powershell
cd build\RelWithDebInfo; $env:GWPS_LOG="test.log"; .\gwps_tests.exe
```

## 3. Seed the database

```powershell
./scripts/seed-db.ps1
```

Creates `db\database.db` with three test accounts — `user1@example.com`, `user2@example.com`,
`user3@example.com` — and a Pre-Searing character. The password is whatever you type at the login
screen; the seeded accounts accept it.

## 4. Run the server

```powershell
./scripts/run.ps1      # or: .\build\RelWithDebInfo\gwps_server.exe
```

Run it **from the repo root**: it opens `db/database.db` and `Gw.dat` relative to the working
directory.

Everything it does is written to `server.log` in the repo root, flushed per line, so the console
is optional:

```powershell
Get-Content server.log -Tail 40 -Wait
```

Useful environment variables:

| Variable | Effect |
|---|---|
| `GWPS_LOG=<path>` | Write the log somewhere else; empty string disables the file |
| `GWPS_TRACE=1` | Log every outgoing game message with header, size and first bytes — the first thing to turn on when a client misbehaves |
| `GWPS_CHAT=1` | Send GM chat answers to the client. Off by default: the chat layouts are still unverified and sending them has crashed the client |

## 5. Prepare the client

```powershell
python tools/gen-dhm-keys.py > keys.txt
python tools/patch-gw.py "F:\GW\GW1\Gw.exe" keys.txt --output "F:\GW\GW1\Gw.custom.exe"
```

The patch replaces the Diffie-Hellman keys the client uses and disables its mutex check. It does
**not** touch the server addresses — those come from the launch flags. Keep the original `Gw.exe`
untouched; `Gw.custom.exe` is a separate file.

Launch:

```powershell
F:\GW\GW1\Gw.custom.exe -authsrv 127.0.0.1 -portal 127.0.0.1
```

`-authsrv` points the game/auth connection at GWPS. `-portal` points the portal's HTTP traffic at
loopback.

> **Note on `portal.dll`**: `scripts/phase0-prepare.ps1` stages `portal.dll` next to the client. On
> the client build tested in 2026-10 it is **not loaded at all** (checked against the process's
> full module list), so it is harmless but unused. Nothing in the install depends on it.

Log in with a seeded account, pick the character, and you should land in Pre-Searing Ascalon.

## 6. Network mode: open or closed

The client opens **one to three additional connections to ArenaNet's file servers** while playing,
for a file/version check. They carry no gameplay data — maps, agents, items, chat and travel all
run over the loopback connections to GWPS — but they do exist, and they are the one thing you may
want to decide about.

### Open — the default, and what a normal install should use

**Nothing to configure.** The client performs its file check against ArenaNet exactly as it would
without GWPS. A retail client on the same machine is completely unaffected.

Choose this unless you have a reason not to.

### Closed — no ArenaNet traffic at all

Only for a machine dedicated to GWPS. The client builds its file-server names itself and some of
those lookups ignore the hosts file, so the only reliable way to catch them is to answer the
lookup:

```powershell
# once
cmake --build build --config RelWithDebInfo --target gwps_dns

# in an Administrator PowerShell
.\tools\dns-gwps.ps1 -Enable
```

That starts `gwps_dns.exe` on `127.0.0.1:53`, answering `127.0.0.1` for anything under
`arenanetworks.com` / `ncplatform.net` and forwarding every other query to the resolver the
adapter had before, and points the active adapter's DNS at it.

```powershell
.\tools\dns-gwps.ps1 -Status     # works unelevated
.\tools\dns-gwps.ps1 -Disable    # restores the adapter's original DNS and stops the responder
```

**This is machine-wide.** While it runs, a retail client on this machine would also be redirected
and would fail to log in. Disable it before playing retail. `-Disable` restores the exact DNS
servers that were in place before.

Do not use `tools/hosts-gwps.ps1` for this: hosts entries only catch the lookups that honour the
hosts file, so a socket still escapes. It exists for diagnosis.

## 7. Verify it works

In game, from the chat box:

| Command | Expect |
|---|---|
| `/maps` | The list of 20 teleport aliases |
| `/tp lakeside` | Travel to Lakeside County; the loading screen completes and you arrive |
| `/tp ascalon` | Travel back to Ascalon City |

`server.log` shows each hop as `Asked the auth server for a game server on map N` followed by
`Sent TRANSFER_GAME_SERVER_INFO` and then `Transfer completed: client moved to server …`. A hop
that reaches the first two and never the third is a failed hop — see below.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `007` at the loading screen, no matter what | A message on the login path is the wrong size or shape. Turn on `GWPS_TRACE=1` and compare what the server sends with what a working build sends. The client reads sizes from its own table, so one wrong length stalls or kills it. |
| `005` right after a teleport | The transfer message was accepted but the client refused the destination — check the `is_explorable` value and the map id in `Sent TRANSFER_GAME_SERVER_INFO`. |
| Loading screen hangs after a teleport | The client closed its connection and never reconnected. Check `server.log` for a `New connection …` after the redirect; if there is none, the redirect was not usable. |
| "Guild Wars is unable to connect to the ArenaNet network" at login | The client's file/version check could not complete anywhere. This happens if the file-server hostnames are redirected without GWPS answering them — use `-Disable` on `dns-gwps.ps1`, or make sure closed mode is fully set up (responder running *and* adapter pointed at it). |
| Typing a map name that is not in `/maps` does nothing | By design. Unknown names are logged and ignored rather than answered, because the chat reply that used to be sent crashed the client. |
| Client crashes when you type in chat | Chat sending is disabled (`GWPS_CHAT` unset). Leave it off until the layouts are settled against a capture. |
| Server starts but the client cannot connect | Another `gwps_server.exe` may already hold 6112. Check `netstat -ano | findstr :6112` and kill the stale process. |

Everything the server knows is in `server.log`; every claim above is visible there.

## 9. Undo everything

Nothing this install changes is permanent, and each piece reverts on its own:

```powershell
.\tools\dns-gwps.ps1 -Disable        # if closed network mode was enabled
.\tools\hosts-gwps.ps1 -Disable      # if the hosts block was ever enabled
```

- **Client**: delete `Gw.custom.exe`; `Gw.exe` was never modified.
- **Server**: delete `build\`, or the whole checkout. `db\database.db` is generated by the seed
  script and `server.log` is a log file.
- **`Gw.dat`**: copied into the repo root by you; delete it to reclaim 3.6 GB.
- **Machine-wide leftovers**: none. The DNS mode restores the adapter; the hosts mode restores the
  file from `hosts.gwps-backup`.
