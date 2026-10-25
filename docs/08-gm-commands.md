# GM commands

Testing "does this map load?" used to mean editing `characters.last_outpost` in the
database and logging in again. Now it is a line of chat.

These commands exist on the **GWPS game server only**. ArenaNet's servers do not have
them, and a map that GWPS has no config for cannot be reached at all — see the note at
the end about which client to use for what.

## Commands

| Command | What it does |
|---------|--------------|
| `/tp <name>` | Move to another map. Also spelled `/teleport`. |
| `/maps` | List the maps you can teleport to (server log; chat output is disabled). |

Aliases match case-insensitively with runs of spaces collapsed, so `/tp lakeside county`
and `/tp LakesideCounty` are the same command. Available targets — every one has a
`GmMapConfig`:

```
ascalon, lakeside, ashford, catacombs, northlands, green hills,
barradin, wizards folly, foibles, regent, fort ranik, kamadan
```

## What a teleport actually does

It is not a position change; it is a **server transfer**, which is what the game itself
does when you walk through a portal:

1. The game server asks the auth server for a game server on the target district
   (`GameSrvCtrl_StartPlayerTransferTo`).
2. The auth server finds a compatible server — **one per map, reused** — or creates one
   (`AuthSrvCtrl_FindCompatibleGameSrv` / `CreateServer`). It mints a player token and
   records the identity the client's *next* connection will be validated against.
3. When that server reports ready, the pending transfer is completed: the old server is
   told the new address and token, and sends the client
   `GAME_SMSG_TRANSFER_GAME_SERVER_INFO`.
4. The client drops the old connection and reconnects; the auth server validates its
   handshake against the recorded identity and hands the socket to the new game server.

Every one of those steps failed at least once while this was built, and each failure
looked identical from the client — a kick (007) or a frozen loading screen. What made them
diagnosable was logging at each hop, not reading the code:

- a registry that was never updated, so the reconnect was always rejected
- a duplicate request that minted a **second** token, overwriting the first
- a completion that arrived after the client had already left the map
- `TRANSFER_GAME_SERVER_INFO` whose fields were the wrong width, so the client read the
  map id out of the player-token slot and echoed `player_token = 148`
- a msgdefs table entry whose field *count* disagreed with its array, so the packer
  refused the message and nothing was sent at all

## Known limitation: a race under latency

Teleports work in normal play. If the client is slowed down — screen recording is enough —
a hop can fail:

- the client disconnects from the old map **before** the auth server completes the
  transfer, and the redirect has nowhere left to go; or
- the target server is still loading its map (2-3 MB) when the client starts waiting, and
  the redirect arrives after the client has given up.

The server has a partial mitigation: the connection, player id and character id are
recorded when a transfer starts, so a completion that arrives after the player is gone can
still reach the client. It helps in some orderings, not all.

Fixing it properly means the redirect must not depend on which event lands first — either
a completion that does not need the source server at all, or a client-side wait that
tolerates a slow target. That is unfinished.

## Which client to use

| Situation | Client | Why |
|-----------|--------|-----|
| Verifying a map GWPS has a config for | **Patched** (`Gw.custom.exe`, `portal.dll`, `-authsrv 127.0.0.1`) | `/tp` only exists on our server |
| Reading a map's navmesh to find its blob id | **Live** (`Gw.exe`, ArenaNet) | GWPS cannot host a map it has no config for; it falls back to Kamadan (map 449 in the probe output means you are on the wrong side) |
