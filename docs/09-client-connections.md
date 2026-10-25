# Client network connections

What the Guild Wars client connects to while playing on GWPS, what each connection is for, and
the three supported ways to run it. Written after measuring every claim below on 2026-10-25;
`docs/test-log.md` has the raw runs.

## Summary

While in game the client holds **two connections to GWPS and up to three to ArenaNet**:

| peer | what it is | can we replace it? |
|---|---|---|
| `127.0.0.1:6112` | GWPS auth handshake, then the game connection | it *is* ours |
| `127.0.0.1:6112` | GWPS file/version check (when redirected to us) | answered by `AuthSrv_TryHandleFileCheck` |
| `<ArenaNet IP>:6112` ×1–3 | ArenaNet **file servers**, used for the file/version check | only by intercepting name resolution — see modes below |

**Nothing gameplay-related leaves the machine.** Map data, agents, items, chat and travel all
run over the two loopback connections. The ArenaNet sockets carry a small fixed file check and
nothing else.

The default and recommended mode is **open**: the client reaches ArenaNet's file servers exactly
as it would normally, GWPS answers everything else, and a retail client on the same machine is
completely unaffected.

## What the client does on those sockets

Captured with `tools/capture-filesrv.ps1` (pktmon, filtered to port 6112) and decoded with
`tools/parse-pcapng.py`. One request, one reply:

```
client -> server   21 bytes
  01 00 00 00 00 f1 00 10 00 01 00 00 00 00 00 00 00 00 00 00 00

server -> client   32 bytes
  f1 02 20 00 | 391339 391348 344988 391350 391351 0 391349
```

Six tight-consecutive ids and a zero, in the same range as `Gw.dat` file ids: a check of which
files the client should have, **not** a transfer. The client treats a failure here as fatal —
when the addresses were made unreachable it refused to log in with "Guild Wars is unable to
connect to the ArenaNet network".

The client also sends a follow-up the server does not handle, `F1 0F 04 00` (header `0x40FF1`),
which it tolerates being ignored.

The address list is **built and resolved by the client itself** (the file client lives at
`P:\Code\Net\FileCli\FcSrv.cpp`), which is why it cannot be redirected by editing strings in the
executable. See the evidence in the next section.

## Why this is not a matter of patching

Four approaches were tried and each one failed in a way that identifies the mechanism:

| attempt | result | what it proves |
|---|---|---|
| Redirect all hostname literals in the exe (`Auth1`, `File1`, `Diag`, `icmp`, `bug`, `account`) | login works, **connections unchanged** | the client does not dial those literals |
| Redirect the `ArenaNetworks.com` domain suffix | **login breaks** | the client builds names from that domain, so it cannot be moved |
| Hosts entries for `File1`–`File6`, `Auth1`, `Diag`, `icmp`, `account` | one file check reached us and was answered, one socket still left | some lookups honour the hosts file, some do not |
| Hosts entry for a constructed name, e.g. `File1.localhost` | **does not resolve** | a name we invent cannot be made to resolve by patching |

The decisive detail: after flushing the DNS cache, entries for `file2` and `file6` **reappeared
even though both were in the hosts file**. The client resolves those names through a path that
ignores the hosts file (`DnsQuery` rather than `getaddrinfo`). It also uses more than one file
server — a single hosts entry for `File1` was not enough; the surviving socket was `File2`.

An in-process hook was prototyped (`portal/portal.c`) but is **not shipped working**:
`portal.dll` is not loaded by this client at all — the full 32-bit module list contains only
`Gw.custom.exe`, `steam_api.dll`, `OpenAL32.dll` and `d3d9.dll` from the game folder. Getting code
into the process would need an injecting launcher or a proxy DLL, which is why it is not the
default.

## Modes

### Open (default, recommended)

Nothing to install. The client resolves ArenaNet's file servers normally and checks its files
against them. GWPS is not involved in that exchange and does not care about the answer.

- retail play on the same machine: unaffected
- what leaks: that this client is active, and nothing else
- our server: `AuthSrv_TryHandleFileCheck` simply never fires

This is what a normal installation should do.

### Local DNS (`tools/dns-gwps.ps1`) — closes the connections

Runs a small DNS responder on `127.0.0.1:53` that answers `127.0.0.1` for anything under
`ArenaNetworks.com` or `NCPlatform.net`, and forwards every other query to the machine's normal
upstream. The active adapter's DNS is pointed at `127.0.0.1` while it runs.

This is the only option that catches the lookups that bypass the hosts file, because those go
through the system resolver — which is now us.

```powershell
.\tools\dns-gwps.ps1 -Enable     # start the responder and point the adapter at it (elevated)
.\tools\dns-gwps.ps1 -Status
.\tools\dns-gwps.ps1 -Disable    # restore the adapter's DNS and stop the responder
```

Trade-offs:

- **machine-wide**: while enabled, every lookup on the machine goes through our responder, so a
  retail client would also be redirected and would fail to log in. Disable before playing retail.
- needs elevation for the adapter setting (the responder itself does not need admin).
- the adapter's original DNS settings are saved and restored by `-Disable`.

Use this when the machine exists to run GWPS and you want no ArenaNet traffic at all.

### Hosts entries (`tools/hosts-gwps.ps1`) — partial, not recommended

Redirects the known hostnames to loopback. It works for the lookups that honour the hosts file
and **does not** stop the ones that do not, so it gives a partial result with the same
machine-wide caveat as the DNS mode. Kept for diagnosis, not for installs.

## What GWPS does in every mode

- The game and auth protocols are only ever served on loopback (`127.0.0.1:6112`), and the client
  is pointed there with `-authsrv 127.0.0.1`.
- `AuthSrv_TryHandleFileCheck` recognises the 21-byte file check (an auth handshake starts with
  `0x000C0400`, the check with `0x00000001`) and replays the captured reply. It stays in the
  build because it is the receiving half of the DNS mode, and it is harmless when nothing sends
  it there.
- No gameplay message is sent to or accepted from a non-loopback peer.
