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

### Verified against a live client (2026-10-24)

Read from `Gw.exe` (pid 16012, `F:\GW\GW1\Gw.exe`) via Py4GW_Stealth read-only
attach. Tools: `tools/dump-map-table.py`, `tools/gwdat-mft.py`.

**Confirmed — the array and its layout:**

- `map.area_info_addr` resolves to a stable base (`0xE7CF00` on this build) and
  the stride is `0x7C`, exactly as `sizeof(AreaInfo)` says.
- Independent cross-check: `base + 5 * 0x7C = 0xE7D16C`, and
  `InstanceInfo.current_map_info_ptr` was `0xE7D16C` while the client sat in map
  id 5. Byte-exact. The array *is* indexed by map id.
- `region`, `type`, `campaign` are valid for every entry, and they are correct:
  map 148 (Ascalon City pre) reads `type=10` (`RegionType_Outpost`), maps 145/146
  (Catacombs, Lakeside) read `type=2` (`RegionType_Explorable`).

**Confirmed — `AreaInfo.file_id` is the same quantity as `GmMapConfig.map_file_id`:**

Kamadan's `0x345CC` decomposes under the client's own formula into
`file_id1 = 0x49CB`, `file_id2 = 0x103` — the same packing the live client uses.
Same field, same units.

**Not confirmed — `file_id` is populated lazily, not stored statically.**
This is the important gotcha. 740 of 899 entries read `file_id == 0`. The 159 that
are populated cluster into bands:

| `file_id2` | count | examples |
|-----------|-------|----------|
| 0x100 | 9 | Hall of Heroes, Battle Isles arenas |
| 0x101 | 30 | Guild Halls, Warrior's/Hunter's/Wizard's Isle |
| 0x102 | 73 | D'Alessio Arena, Fort Koga, Amnoon Arena |
| 0x103 | 25 | Churranu Island Arena, Guild Halls, Fetid River |
| 0x104 | 15 | Dwayna Vs Grenth, Rollerbeetle Racing |
| 0x105 | 5 | Costume Brawl, Whitefury Rapids |

None of the six `GmMapConfig` maps was populated (the client was idling in a Guild
Hall, not in Lion's Arch / Kamadan / etc.). **So you cannot dump the whole
map→file-id table in one shot from an idle client** — the values appear once the
client has actually loaded the map.

Two ways forward, and they are complementary:

1. **Parse `Gw.dat` directly** (`tools/gwdat-mft.py`) — no client needed, gives
   every archive file id at once, and validates against the six known configs.
   *Blocked while the client runs:* `Gw.exe` holds an exclusive lock on `Gw.dat`
   (`ERROR_SHARING_VIOLATION` even with `FILE_SHARE_READ|WRITE`). Close the client
   first.
2. **Travel to the map and re-read.** Works today, needs one visit per map. Make
   `dump-map-table.py` merge into a JSON DB across runs so repeated visits
   accumulate instead of overwriting.

### The Pre-Searing map census (verified)

Filtering all 899 entries for `region == Presearing` yields **21 maps**, including
four that were missing from the hand-written list in `03-roadmap.md`:

| id | type | name |
|----|------|------|
| 143 | outpost | *(no name id resolved — name_id 10454)* |
| 145 | explorable | The Catacombs |
| 146 | explorable | Lakeside County |
| 147 | explorable | The Northlands |
| 148 | outpost | Ascalon City (pre-Searing) |
| 149 | town | Ascalon Academy |
| 150 | town | Ascalon Academy PvP battle |
| 151 | explorable | Ascalon Academy |
| 160 | explorable | Green Hills County |
| 161 | explorable | Wizard's Folly |
| 162 | explorable | Regent Valley (pre-Searing) |
| **163** | outpost | **Pre-Searing: The Barradin Estate** |
| 164 | outpost | Pre-Searing: Ashford Abbey |
| **165** | outpost | **Pre-Searing: Foibles Fair** |
| 166 | outpost | Pre-Searing: Fort Ranik |
| 408–412 | explorable | *(5 entries, name ids 31414–31422)* |
| 779 | outpost | *(no name id resolved — name_id 79766)* |

149/150/151 are the Ascalon Academy mission chain, which `03-roadmap.md` lists as
out of scope. 408–412 and 779 need identifying before they join the target set.

### What the archive scan proved (2026-10-24)

`tools/gwdat-scan.c` (CMake target `gwdat_scan`) reuses the server's own
`FaOpen`/`FaGetFile`/`FaCompress`/`RiffParseChunks` code, so it exercises exactly
the path `GameSrv_LoadMap` uses. Results, committed as `data/gwdat-maps.csv`:

- `F:\GW\GW1\Gw.dat` parses: magic `0x1A4E4133` (`FILE_ARCHIVE_MAGIC`),
  `mft_offset 0xD82B9A00`, 155 238 MFT entries, **146 695 file ids**, 3.66 GB.
- **426 blobs are maps — that is 213 distinct maps, each stored twice**
  (every size occurs exactly twice; `paired_with` in the CSV records the twin).
  All are `RIFF_MAP2`, between 427 KB and 4.4 MB decompressed.
- Kamadan's blob validates end to end: 24 chunks, and chunk `0x20000008`
  (stage 2, `ChunkId_Path`) begins `4C 70 FE EE 0C 00 00 00` — that is
  `PATH_DATA_SIGNATURE` `0xEEFE704C` and `PATH_DATA_VERSION` 12, the exact
  constants `GmMapDataImport.c:5-6` asserts. The archive reader and decompressor
  are correct.

**Three of the six shipped `GmMapConfig` entries are wrong.** They exist in the
MFT but are *not* map blobs:

| map | shipped `map_file_id` | in MFT | RIFF map blob? |
|-----|----------------------|--------|----------------|
| Kamadan, Jewel of Istan | `0x345CC` | yes | **yes** (1 734 079 B, 24 chunks) |
| Domain of Anguish | `0x3584F` | yes | **yes** (3 104 279 B, 23 chunks) |
| Sparkfly Swamp | `0x46305` | yes | **yes** (3 465 034 B, 25 chunks) |
| Lion's Arch | `0x56228` | yes | **no** |
| Kaineng Center | `0x265F7` | yes | **no** |
| Lornar's Pass | `0xB602` | yes | **no** |

That is a real upstream bug, and it independently justifies the Phase 0 decision
to verify on **Kamadan** — it is the only outpost whose config actually loads.

### Still open: assigning blob ids to map ids

Do not assume `AreaInfo.file_id` is always the map geometry id. For the guild
halls (map ids 4–9) it resolved to entries like `0x1F4B7` with `stream = 0` and a
size of ~31 KB — far too small to be a map blob. So `AreaInfo.file_id` is a
*related* identifier, not a guaranteed alias, and it is lazily populated anyway.

The clean way to close this is direct observation: `Gw.exe` opens each map with
`OpenFileByFileId(archive, file_id, stream_id, flags, &error)` — already resolved
in Py4GW_Reforged_Native as `g_open_file_by_file_id_func`
(`include/GW/textures/gw_dat_reader.h:42,65`). Hook that, load a map, and the
exact `map_id -> file_id -> stream` triple falls out. That needs no guessing and
no Ghidra.

The cheap approximation, if a hook is more than we want right now: travel to a
map and read `AreaInfo[map_id].file_id`, then check the value against
`data/gwdat-maps.csv` — an id absent from that file is not a map blob.

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

### CORRECTION (2026-10-24, later the same day): `AreaInfo.file_id` is NOT the map id

The section above said `AreaInfo.file_id` is the same quantity as
`GmMapConfig.map_file_id`. **That is wrong, and it is worth leaving the correction
here so nobody repeats it.**

With a character standing **inside** map 148 (Ascalon City, pre-Searing) — region
7, type 10, fully loaded — the field still reads **0**:

```
current map id = 148  (Ascalon City (pre-Searing))
current AreaInfo (via InstanceInfo pointer):
  region 7   type 10   name_id 10478
  file_id 0   file_id1 0xFFFF   file_id2 0xFF
array walk AreaInfo[148].file_id = 0x00000000
```

The 159 entries that *are* populated are legacy PvP/guild-hall infrastructure, and
**none of them appears in the 426-blob map list** from `data/gwdat-maps.csv`. So
`file_id` is a different concept, not the map geometry key. It also means the
`file_id1()`/`file_id2()` decomposition does not lead to map geometry ids.

Also note: reading past the end of the array yields garbage (`map_id` 898/899 read
`region = 1130133319`), so the array is shorter than 900 entries — bound any scan
below ~898.

**Consequence:** `GmMapConfig.map_file_id` must come from observing which blob the
client actually opens, not from `AreaInfo`.
