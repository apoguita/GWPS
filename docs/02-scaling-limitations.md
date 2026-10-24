# Scaling limitations inherited from OpenTyria

This document records **where** OpenTyria's "keep it simple" design choices stop
scaling, with the exact source locations, so that PreSearing can decide
deliberately which ones to keep and which ones to pay down.

Baseline analysed: `apoguita/OpenTyria` @ `53acb8e` ("Minor fix to packet dumper").

> OpenTyria's own README states the trade-off:
> *"there is several design decisions that limit the scaling, but they are
> chosen, because it simplified the final solution."*
> Here is the concrete list.

---

## TL;DR — the seven that actually bite

| # | Limitation | Hard ceiling it creates |
|---|------------|--------------------------|
| 1 | All game servers are **threads in one process** | One machine, one crash domain, no horizontal scale-out |
| 2 | **All session state is in RAM** in the auth process | No restart without losing everyone; no second auth node |
| 3 | **Auth handshake is on the single event-loop thread** | One handshake storm stalls every login; trivial DoS |
| 4 | **One SQLite file, one writer, no WAL, no busy timeout** | All maps serialize on one write lock; `SQLITE_BUSY` under load |
| 5 | **One hardcoded district per map, linear map scan** | Map capacity is whatever one thread handles; no overflow/sharding |
| 6 | **O(N) work per frame at ~62 Hz per map server** | CPU grows linearly with players even when idle |
| 7 | **Unbuffered logging (`fflush` per line) on hot loops** | Logging alone becomes a throughput ceiling |

Each is detailed below with evidence and a remediation path.

---

## 1. One process, many threads — there is no process boundary

`AuthSrvCtrl_CreateServer` allocates a `GameSrv` on the **auth server's** heap and
starts it as a **thread of the same process**:

```c
// code/OpenTyria/AuthSrvCtrl.c:34-68
int AuthSrvCtrl_CreateServer(AuthSrv *srv, GmDistrict district, size_t *idx)
{
    ...
    GameSrv *gm;
    if ((gm = calloc(1, sizeof(*gm))) == NULL) {   // same address space
        return ERR_OUT_OF_MEMORY;
    }
    ...
    if ((err = GameSrv_Setup(gm, params)) != 0) { ... }
    if ((err = GameSrv_Start(gm)) != 0) { ... }     // -> sys_thread_create
```

```c
// code/OpenTyria/GameSrv.c:2068-2084
int GameSrv_Start(GameSrv *srv)
{
    ...
    if ((err = sys_thread_create(&srv->thread, GameSrv_ThreadEntry, srv)) != 0) {
```

The `CtrlConn` the game server opens back to the auth server
(`GameSrv_ConnectCtrlConn`, `GameSrv.c:48`) is a **loopback socket to
`127.0.0.1:1337`**, hardcoded in `main.c:58`. So the control protocol exists, but
it is only ever used over localhost inside one process — it is *not* a usable
service boundary today.

**Consequences**

- A crash or `abort()` in **any** map server takes down the auth server and every
  other map (`GameSrv.c:1919` literally calls `abort()` on a poll error).
- All maps share one address space, one allocator, one `Gw.dat` file-handle set,
  one `db/database.db`.
- Cannot place one map on another host, cannot scale out by adding machines,
  cannot restart a single map.
- No supervisor: `AuthSrvCtrl_CreateServer` never frees a `GameSrv`, and nothing
  respawns a dead one.

**Remediation path** — turn the existing `CtrlConn` protocol into a real
transport (TCP with a bind-address from config instead of `127.0.0.1:1337`), then
make `GameSrv` spawn as a **child process** (`CreateProcess` / `fork+exec`) with
its own `--server-id`/`--map`/`--ctrl` arguments. That single change unlocks
multi-host deployment without rewriting the protocol.

---

## 2. All session state lives in the auth process's RAM

```c
// code/OpenTyria/AuthSrv.h:99-109
typedef struct GlobalAccountRegistry {
    union { GmUuid key; GmUuid account_id; };
    GmUuid    char_id;
    uint32_t  current_server_id;
    uint32_t  current_player_id;
    uintptr_t auth_conn_token;
} GlobalAccountRegistry;

// code/OpenTyria/AuthSrv.h:156-158
    GlobalAccountRegistry   *accounts;   // stb_ds hashmap, in RAM
    SocketAddr               internal_address;
    GameSrvMetadata         *games;      // in RAM, incl. pending_transfers
```

`pending_transfers` (per game server, `AuthSrv.h:144`) is also purely in memory.

**Consequences**

- Restarting the server logs **everyone** out and loses in-flight map transfers.
- Two auth servers cannot share "who is online where" → you can never run more
  than one, so this is a hard **single point of failure**.
- No reconnect-after-crash, no draining, no rolling restart.
- Persistent player state is in SQLite, but **presence** is not.

**Remediation path** — move `GlobalAccountRegistry` and the transfer queue into a
small external store (Redis / a dedicated SQLite/Postgres table, or even a
dedicated "presence" service). Even a single-node Redis removes the restart
coupling and is ~a day of work.

---

## 3. The auth event loop is single-threaded, and the Diffie-Hellman runs on it

```c
// code/OpenTyria/AuthSrv.c:1493-1503
void AuthSrv_Update(AuthSrv *srv)
{
    AuthSrv_Poll(srv);
    for (size_t idx = 0; idx < srv->events.len; ++idx) { ... }
```

One thread owns: 3 listeners (6112, 6113, 1337), **all** auth connections, and
**all** ctrl connections. Poll batch is capped at 256 events
(`iocp.h:6`, `IOCP_POLL_BATCH_MAX_COUNT`).

Inside that same thread, every connection performs a **512-bit modular
exponentiation** during key exchange:

```c
// code/OpenTyria/AuthSrv.c:167-174
    mbedtls_mpi shared_secret;
    mbedtls_mpi_init(&shared_secret);
    if ((err = mbedtls_mpi_exp_mod(&shared_secret, &client_public,
                                   &server_private, &prime_modulus, NULL)) != 0) {
```

**Consequences**

- Every login blocks *all* other connections for the duration of the DH.
- An attacker opening N sockets and sending `CMSG_CLIENT_SEED` makes the login
  server unusable with no authentication required — a cheap DoS.
- Listen backlog is 256 (`AuthSrv.c:1063`), so bursts above that are dropped.

**Remediation path** — move handshakes to a worker pool (thread pool or a
staged/queued state machine), and add per-IP connection rate limiting before the
first DH. Both are contained changes that do not touch the protocol.

---

## 4. SQLite: one file, one writer, no WAL, no busy timeout

```c
// code/OpenTyria/Db.c:255-266
int Db_Open(Database *result, const char *path)
{
    const int flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOMUTEX;
    ...
    if ((err = sqlite3_open_v2(path, &result->conn, flags, NULL)) != SQLITE_OK) {
```

- The path is **hardcoded** in two places: `AuthSrv.c:306` and `GameSrv.c:98`
  (`"db/database.db"`).
- **Every** `GameSrv` opens **its own** connection to that **same file**
  (`GameSrv.h:56`, `Database database;`), and so does `AuthSrv`.
- **No** `PRAGMA journal_mode`, no `PRAGMA synchronous`, no
  `sqlite3_busy_timeout`. Default rollback journal ⇒ one writer at a time,
  globally, across all maps.
- `SQLITE_OPEN_NOMUTEX` means the connection must be used by one thread at a
  time — fine today, but it blocks introducing a shared connection pool later.
- Writes happen **inline in the map tick**, e.g. on player join:

```c
// code/OpenTyria/GameSrv.c:1197-1226
    if ((err = Db_CreateBags(&srv->database, bags, count)) != 0) {
    ...
    if ((err = Db_CreateItems(&srv->database, items.ptr, items.len)) != 0) {
    ...
    if ((err = Db_UpdateLastPlayedCharacter(&srv->database, msg->account_id, msg->char_id)) != 0) {
```

**Consequences**

- Disk latency becomes **map tick latency**: a slow fsync on one map stalls that
  map's 16 ms loop.
- With several maps active, writes contend on one lock; without a busy timeout,
  contention surfaces as `SQLITE_BUSY` errors rather than a wait.
- No read/write concurrency: readers block the writer and vice versa.

**Remediation path** (in order of effort):

1. Enable WAL + `synchronous=NORMAL` + `busy_timeout` in `Db_Open` (one-line-ish,
   large win).
2. Disable the per-`GameSrv` connection and use one DB service/connection owned
   by a single thread, with an async request queue.
3. Later: move to a real DB (Postgres) once the write pattern is understood.

---

## 5. One hardcoded district per map; map lookup is a linear scan

```c
// code/OpenTyria/AuthSrvCtrl.c:39-41
    GameSrvMetadata *metadata = AuthSrvCtrl_AddGameSrvMetadata(srv, server_id);
    metadata->district = district;
    metadata->district.district_number = 1;   // <-- always district 1
```

```c
// code/OpenTyria/AuthSrvCtrl.c:20-32
int AuthSrvCtrl_FindCompatibleGameSrv(AuthSrv *srv, GmDistrict district, size_t *result)
{
    size_t n_games = stbds_hmlen(srv->games);
    for (size_t idx = 0; idx < n_games; ++idx) {         // O(#game servers)
        GameSrvMetadata *metadata = &srv->games[idx];
        if (GmDistrict_IsCompatible(metadata->district, district)) {
            *result = idx;
            return ERR_OK;
        }
    }
    return ERR_UNSUCCESSFUL;
}
```

**Consequences**

- There is no district overflow: the second group of players for a map either
  joins the first server or nothing happens. **Map capacity = capacity of one
  thread.**
- No load-based matchmaking, no queueing, no merging, no rebalancing.
- `FindCompatibleGameSrv` returns the *first* compatible server, so if you ever
  did create several districts, population would pile onto the first one.
- O(#maps) per map change; negligible now, but it is the wrong shape.

**Remediation path** — make `district_number` a real allocator
(`AuthSrvCtrl_FindCompatibleGameSrv` → pick least-populated compatible, create a
new district when full), and return a `(server_id, district)` pair to the client
so overflow is invisible to players.

---

## 6. O(N) work per frame at ~62 Hz, per map server

```c
// code/OpenTyria/GameSrv.c:1909-1921
void GameSrv_Poll(GameSrv *srv)
{
    array_clear(&srv->events);
    while ((err = iocp_poll(&srv->iocp, &srv->events, 16)) != 0) {   // 16 ms
        ...
        abort();                                                    // whole process!
```

```c
// code/OpenTyria/GameSrv.c:1923-2009  (GameSrv_Update)
    // ping loop: iterates ALL connections
    if (GAME_SRV_TIME_BETWEEN_PING_MS <= (current_time - srv->last_ping_request)) {
        size_t n_connections = stbds_hmlen(srv->connections);
        for (size_t idx = 0; idx < n_connections; ++idx) { ... GameSrv_SendPing ... }
    }
    // flush loop: iterates ALL connections again
    size_t n_connections = stbds_hmlen(srv->connections);
    for (size_t idx = 0; idx < n_connections; ++idx) { ... }
    // reregister loop: iterates all connections with events
    for (size_t idx = 0; idx < srv->connections_with_event.len; ++idx) { ... }
```

Plus the `epoll` layer re-arms every connection per event
(`EPOLLONESHOT`, `linux/iocp_linux.c:46`, `iocp_reregister` in
`GameSrv.c:2004`).

**Consequences**

- Each map server burns CPU proportional to **total** players, at up to
  ~62 wakeups/s, regardless of activity. Idle maps still cost frames.
- Three full passes over the connection table per frame ⇒ the per-frame constant
  dominates long before the network does.
- Only ~250 connections can be *processed* per poll batch (`iocp.h:6`).

**Remediation path** — iterate only dirty/active connections (maintain an
"outgoing non-empty" set and a ping wheel instead of full scans), lower the base
tick, and stop re-arming connections that have nothing to do.

---

## 7. Logging is synchronous, unbuffered, and DEBUG-by-default

```c
// code/OpenTyria/logs.c:5
unsigned int log_minimum_level = LOG_DEBUG;
```

```c
// code/OpenTyria/logs.c:59-74
    ret = fprintf(stderr, "[%04d-%02d-%02dT%02d:%02d:%02d.%03d] %5s: %s%s\n", ...);
    ...
    fflush(stderr);          // <-- flushes on EVERY single line
```

Called from inside the hot loops (`GameSrv.c:1918`, `GameSrv.c:2005`, etc.), and
`sys_get_utc_time` syscall per line.

**Consequences**

- A burst of connections produces a burst of unbuffered writes → the event loop
  spends its time in the kernel writing logs.
- DEBUG-by-default means the release binary is the slow one.
- No structured logs, no rotation, no sampling, no per-server tagging.

**Remediation path** — compile-time `LOG_MIN_LEVEL=INFO` for release, buffered
or async log writer (append to a ring buffer, one writer thread), and include
`server_id` in every line.

---

## Secondary limitations (real, but lower priority)

### 8. Unbounded per-connection output buffer

```c
// code/OpenTyria/GameSrv.c:166
    if ((dst = array_push(&conn->outgoing, MSG_MAX_BUFFER_SIZE)) == NULL) {
```

No cap and no backpressure: a slow/stalled reader makes the server allocate
without limit (`AuthSrv.c:274` is the same). One malicious client can OOM the
process. The handshake-stage `Connection` also has a fixed
`uint8_t incoming[256]` (`AuthSrv.h:30`).

### 9. No graceful shutdown, no lifecycle management

```c
// code/OpenTyria/GameSrv.c:2061-2066
    while (!srv->quit_signaled) {
        GameSrv_Update(srv);
    }
    log_warn("Missing a lot of freeing here!!");
```

`quit_signaled` is only set from ctrl messages (`GameSrv.c:1344-1360`); the auth
`main()` loop (`main.c:69-71`) never signals game servers, never joins threads,
and `GameSrv_Free` is effectively dead code. Detached threads
(`GameSrv.c:2054`) mean nothing is joined. Result: no clean restart, and leaks on
every map creation/teardown cycle.

### 10. Single translation unit build

`code/OpenTyria/build_open_tyria.c` `#include`s ~45 `.c` files into one TU (and
those `.c` files use `#pragma once`). Consequences: no parallel or incremental
compilation, every edit rebuilds everything, no enforced module boundaries, and
symbols leak across "modules". `vc/OpenTyria.vcxproj` is also **stale** — it still
lists `..\code\OpenTyria\CtrlProto.c` (line 71), a file that no longer exists,
so the checked-in Visual Studio build is already broken.

### 11. Secrets and topology hardcoded in `main.c`

```c
// code/OpenTyria/main.c:3-6, 58
static const char *addresses[] = { "127.0.0.1:6112", "127.0.0.1:6113" };
...
const char addr[] = "127.0.0.1:1337";
```

```c
// code/OpenTyria/main.c:32-42  — DH prime and private key baked into the binary
const char *prime_modulus_ascii  = "1136903000...";
const char *server_private_ascii = "4955013838...";
```

Every instance of the binary therefore shares the same DH private key (the README
calls it "temporary"). No config file, no CLI parsing beyond logging args, no
way to run two instances with different topology.

### 12. Zero observability

No metrics, no counters, no admin/status endpoint, no per-map population
reporting. You cannot tell whether a map is full, whether frames are slow, or
how many logins are in flight.

---

## What this means for PreSearing

None of the above blocks a *private* Pre-Searing server with tens of concurrent
players. The realistic numbers on one modern machine with this codebase:

- **Fine:** ~50-150 concurrent players spread over several maps, single box.
- **Painful:** all players in one outpost, or login bursts (everyone relogs at
  once), or a 10k-line log burst.
- **Broken:** >1 process for auth, >256 simultaneous handshakes, map capacity
  beyond one thread, any restart without kicking everyone.

The intended order of attack is in `docs/03-roadmap.md`; the ones that are
*cheap now and expensive later* are #7 (logging), #4.1 (WAL pragmas), #3 (DH off
the main loop) and #1 (process boundary), in that order.
