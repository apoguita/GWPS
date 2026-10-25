# Client tooling: the Py4GW ecosystem

PreSearing is a **server**. It has no client. That is normally the worst place to
be when reverse-engineering a protocol — you are guessing at both ends.

It is not our situation. We already have three cooperating projects that give us
deep, *programmatic* access to the real Guild Wars client:

| Project | Path | What it is |
|---------|------|------------|
| **Py4GW Reforged** | `C:\Users\Apo\Py4GW_Reforged` | Python automation library that runs **inside** the client via an injected DLL |
| **Py4GW Reforged Native** | `C:\Users\Apo\Py4GW_Reforged_Native` | The C++ backend (`Py4GW.dll`): hooks D3D9, embeds CPython, resolves symbols from `offsets/*.json` |
| **Py4GW Stealth** | `C:\Users\Apo\Py4GW_Stealth` | External-host port: reads client state from a **separate** Python process; hooks only if you opt in |

All three are ours (same author as OpenTyria). Treat them as first-class
dependencies of this project's *development loop*, even though PreSearing ships
without them.

## Capability map

| Capability | Where | Why PreSearing cares |
|-----------|-------|---------------------|
| **StoC + CToS packet capture** | `Py4GWCoreLib/PacketSniffer.py`, `include/GW/packet_sniffer/packet_sniffer.h` | The test oracle. Lets us diff our byte stream against a real server's |
| **`AreaInfo` table (map → file id)** | `include/GW/context/map.h:87-131`, `src/GW/map/map_methods.cpp:203-213` | **Solves the `map_file_id` problem** (see below) |
| **`GWDatReader`** | `include/GW/textures/gw_dat_reader.h` | Reads any `Gw.dat` file using the game's *own* decoder |
| **Map/pathing context** | `include/GW/context/map.h:202-256`, `include/GW/context/pathing.h` | Ground truth for what the client believes the map is |
| **Agents / players / party / items / skills** | `src/GW/{agent,party,item,skill}/` | Ground truth for what the client believes *we* sent |
| **Multi-account** | `include/GW/multibox/manager.h` | Automates the two-client tests (T9) |
| **Shared memory cache** | `Py4GWCoreLib/GlobalCache/shared_memory_src/*.py` | Lets a *separate* harness read live state without being inside the DLL |
| **Read-only external attach** | `Py4GW_Stealth`: `py4gw.connect(..., game_thread=False)` | Safe, no injection, good enough for table dumps |
| **Client-side script execution** | Reforged `Widgets/`, `Py4GWCoreLib/` | Drive a client through a repeatable script instead of by hand |

## The big one: `map_file_id` is solved

`docs/05-reverse-engineering.md` used to describe hunting `map_file_id` by brute
force. That is now obsolete. The client already holds the entire table in memory,
**indexed by map id**:

```c
// Py4GW_Reforged_Native/include/GW/context/map.h:87-121
struct AreaInfo {              // total 0x7C
    /* +h0000 */ Constants::Campaign campaign;
    /* +h0008 */ Region region;
    ...
    /* +h0068 */ uint32_t file_id;      // <-- the packed map file id

    uint32_t file_id1() const { return ((file_id - 1) % 0xff00) + 0x100; }
    uint32_t file_id2() const { return ((file_id - 1) / 0xff00) + 0x100; }
};
```

and the lookup is a plain array index by map id:

```c
// Py4GW_Reforged_Native/src/GW/map/map_methods.cpp:203-213
Context::AreaInfo* GetMapInfo(GW::Constants::MapID map_id) {
    ...
    auto* area_info = Context::GetAreaInfoArray();
    return area_info && map_id > MapID::None && map_id < MapID::Count
        ? &area_info[static_cast<uint32_t>(map_id)]
        : nullptr;
}
```

So `AreaInfo[map_id].file_id` is available for **every** map — you do not have to
load a map to learn its file id. The Pre-Searing table in `03-roadmap.md` can go
from 8× `_TBD_` to complete values in one pass.

The same structure is already reimplemented in Python, so the shape is settled:

```python
# Py4GW_Reforged/Py4GWCoreLib/native_src/context/InstanceInfoContext.py:27-67
class AreaInfoStruct(Structure):
    _fields_ = [..., ("file_id", c_uint32),   # +0x0068
                ("mission_chronology", c_uint32), ...]
    @property
    def file_id1(self) -> int: return ((self.file_id - 1) % 0xff00) + 0x100
    @property
    def file_id2(self) -> int: return ((self.file_id - 1) // 0xff00) + 0x100
```

### The one open question

`AreaInfo.file_id` is a **packed** value that expands to two .dat file ids via
`file_id1()` / `file_id2()`. OpenTyria's `GmMapConfig.map_file_id` is a single
`uint32_t` fed straight into `FaGetFile` (`GameSrv.c:2030`). We do not yet know
which of the three (`file_id`, `file_id1()`, `file_id2()`) it corresponds to.

**This is a five-minute check, not a research project:** Kamadan's
`GmMapConfig.map_file_id` is `0x345CC`, so read `AreaInfo[MapId_KamadanJewelOfIstanOutpost].file_id`
in a live client and compare against `0x345CC`, `file_id1()` and `file_id2()`.
Whichever matches is the rule for all ~880 maps.

### What is still missing

`Context::GetAreaInfoArray()` exists natively (`src/GW/context/context_methods.cpp:128`)
but is **not exposed to Python** yet — `GetMapInfo` is not in
`src/GW/map/map_bindings.cpp`'s `def()` list either. Py4GW_Stealth flags the same
gap. Options, cheapest first:

1. Read the resolved base pointer `g_area_info_addr` (resolved by
   `ResolveAreaInfo()`, `src/GW/map/map_patterns.cpp:40`) and walk
   `addr + map_id * 0x7C + 0x68` from Python/ctypes. No native change needed.
2. Add `get_map_info(map_id)` to the map bindings — ~10 lines, but it means a
   `Py4GW.dll` rebuild.
3. `Py4GW_Stealth` read-only attach (`connect(game_thread=False)`), if its `Map`
   surface already carries what we need.

Option 1 is enough for a one-off table dump and does not touch any of the other
projects.

## The second big one: the packet sniffer is our test oracle

`docs/04-scope.md` currently asks a human to eyeball whether a client "looks
right". With the sniffer we can do better: **capture both sides and diff them.**

Two capture paths (`docs/game-client/research/packet-sniffers-reference.md`
in Py4GW_Reforged):

| Direction | Mechanism | Bound |
|-----------|-----------|-------|
| **StoC** (server→client) | replaces each header's handler in the client's own `StoCHandlerArray`, copies bytes | 512 B/packet, `0x1E7` headers |
| **CToS** (client→server) | detours the outbound send wrapper | 4096 B/packet |

Each entry carries `direction`, `tick`, `header`, `size`, `data`
(`include/GW/packet_sniffer/packet_sniffer.h:19-25`).

What that buys us, concretely:

1. **Golden capture.** Point a client at a real GW server (or reuse a capture),
   do a scripted sequence (login → enter outpost → walk → chat), record the
   packet log. Then run the same script against *our* server and diff by header.
   First divergence = the bug, with a byte offset.
2. **Decode what our server sends** without guessing: we already have
   `tools/packet.py`, `tools/msgs.py`, `tools/consts.py`, and now a second,
   independent decoder plus the native struct definitions in
   `Py4GW_Reforged_Native/include/GW/common/stoc.h` (~1100 lines of packet
   structs with `STATIC_HEADER` constants).
3. **Settle field-level questions immediately.** Example: OpenTyria sends
   `GAME_SMSG_AGENT_CREATE_PLAYER`; the native struct is
   `PlayerJoinInstance { player_number, agent_id, file_id1, secondary_profession,
   unk3, file_id2, player_name[32] }` (`stoc.h:241-250`). One capture answers
   whether our `file_id1`/`file_id2` are right — no Ghidra, no guessing.
4. **Automated regression.** Once a sequence is scripted, the same capture can run
   on every commit and be compared to the golden file.

## Recommended division of labour

| Task | Tool | Why |
|------|------|-----|
| Dump `map_id → file_id` for all maps | Native `AreaInfo` via read-only pointer walk | Authoritative, no loading, no guessing |
| Cross-check our `Gw.dat` reader | `GWDatReader::ReadDatFileById` (`gw_dat_reader.h:98`) | Uses the game's own decoder — an independent oracle for `FaArchive`/`FaCompress` |
| Verify our server's output | `PacketSniffer` StoC | Byte-exact |
| Verify we parse client input | `PacketSniffer` CToS | Byte-exact |
| Understand a missing feature | capture first, Ghidra last | See `05-reverse-engineering.md` |
| Two-client tests | `multibox` + scripted clients | Repeatable instead of manual |
| Automated test harness outside the client | shared memory cache (`GlobalCache/shared_memory_src/`) | Read state from any process |

## Rules of engagement

- **PreSearing must not depend on Py4GW at runtime.** These are development and
  verification tools. The server stays standalone C.
- **Prefer read-only.** `Py4GW_Stealth` is read-only unless you pass
  `game_thread=True`; the native sniffer is passive by design
  (`packet_sniffer.h:32-35` notes capture stays off until a consumer asks). Read
  paths are safe; hook installation modifies `Gw.exe` in memory. Do not make
  client modification a requirement for verifying server behaviour.
- **Never commit captures containing names or account data.** Packet logs will
  contain UTF-16 player names and UUIDs. Sanitise before adding a golden capture
  to the repo, or keep them out of git entirely.
- **Record the client build.** Offsets, patterns and packet layouts are
  build-specific. Any golden capture must state the `Gw.exe` version it came from.
