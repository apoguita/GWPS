# Reverse-engineering tooling: which tool for which job

This document exists to prevent a very specific and expensive mistake.

## Short answer

**Ghidra does not read `Gw.dat`.** Ghidra is a decompiler: you load an
executable (`.exe`, `.dll`) and it shows you the machine code as C. `Gw.dat` is
not an executable — it is a data archive full of serialized structs, meshes and
tables. A decompiler has nothing to disassemble in it.

They are three different problems that need three different tools:

| Layer | What it is | Tool that actually works |
|-------|-----------|--------------------------|
| `Gw.exe` / `portal.dll` | Compiled x86 machine code | **Ghidra** (or IDA, Binary Ninja), plus byte-pattern scanning |
| `Gw.dat` | Archive + serialized data | **A parser you write**, or the ones already in this repo |
| The wire protocol | Bytes on a socket | Packet capture + `tools/packet.py`, `tools/trace-packets.py` |

Ghidra is still genuinely useful to us — just for the first row and the third,
not the second.

## What already exists in this repo

We are not starting from zero on any of these layers. Per layer:

### The `Gw.dat` archive container — **solved**

`code/OpenTyria/FaArchive.c`

`Gw.dat` begins with a header pointing at a *Master File Table* (`mft_offset`).
The MFT is a flat array of entries, and one special entry (`INDEX_TOC`) is a
table of `{ file_id, file_index }` pairs. `FaOpen` builds a hash table from it:

```c
// FaArchive.c:122-128
for (size_t idx = 0; idx < count; ++idx) {
    MFTFileHash value;
    value.key = le32toh(buffer[idx].file_id);
    value.file_index = le32toh(buffer[idx].file_index);
    stbds_hmputs(archive->file_hash_table, value);
}
```

So "give me the bytes for `file_id`" is a solved problem:
`FaGetFile(archive, file_id, &out)` (`FaArchive.c:161`).

### Compression — **solved**

`code/OpenTyria/FaCompress.c` (~500 lines). It is a custom Huffman variant with
two hardcoded tables (`Table1`, `Table2`) that encode "how many codes of each bit
length exist". This is exactly the kind of thing that *was* reverse-engineered
from the binary once, by someone else, years ago — and it is now just C code we
link. You will not need to redo it.

`FaGetFile` decompresses transparently when the MFT entry says `compressed != 0`.

### The map file format — **solved, but only partly consumed**

`code/OpenTyria/GmMapDataImport.c`

A map blob is RIFF-like (`GmMapDataImport.h:23-34`):

```c
typedef enum RiffType {
    RIFF_MAP1 = 1,
    RIFF_MAP2 = 3,
} RiffType;
```

with 4-byte magic `"ffna"`, a type byte, then a sequence of chunks:

```
[4 bytes chunk_id][4 bytes chunk_size][chunk_size bytes of data]  ...
```

`RiffParseChunks` (`GmMapDataImport.c:52-77`) splits them, sorts by id, and
`RiffGetChunk` binary-searches. Chunk ids are a namespace of
`(stage << 28) | ChunkId_*` where `ChunkId_Terrain = 2`, `ChunkId_Path = 8`,
`ChunkId_Collision = 14`, etc. (`GmMapDataImport.h:3-21`).

**The crucial part for our scope:** the server imports **only the pathfinding
chunk**, stage 2:

```c
// GmMapDataImport.c:563-571
uint8_t stage = 2;
uint32_t chunk_id = ((uint32_t)stage << STAGE_SHIFT) | (uint32_t) ChunkId_Path;
if ((chunk = RiffGetChunk(&chunks, chunk_id)) == NULL) { ... }
if ((err = PathDataImport(&context->path.static_data, chunk->chunk_data)) != 0) { ... }
```

Terrain, props, collision and `MapParameters` are *not* imported
(`MapParameters` is commented out at lines 575-585). This is not an oversight —
**the client renders the world from its own `Gw.dat`.** The server only needs to
know where players are allowed to walk, to validate movement and run pathfinding.
That drastically reduces what we need out of the `.dat`.

### `Gw.exe` binary patching — **solved, by pattern scanning, not Ghidra**

`tools/patch-gw.py` does not decompile anything. It hardcodes byte signatures and
searches the `.text` section:

```python
# patch-gw.py:55 — find the function that returns the DH key block
found = text_sec_data.find(b'\x8B\x45\x08\xC7\x00\x88\x00\x00\x00\xB8')
keys_addr, = struct.unpack_from('<L', text_sec_data, found + 0xA)
```

It then overwrites, in the exe's `.rdata`:
- the DH generator (4 bytes), prime modulus (64 bytes), server public key (64 bytes)
- the client's single-instance mutex name `AN-Mutex-Window` → `AN-Futex`, so you
  can run two clients on one machine

This is the "signature scanning" RE technique. It is fast and needs no Ghidra —
and it is also **fragile**: it breaks whenever ArenaNet ships a new `Gw.exe`.

### Live client memory reading — **solved, that's how `draw-map.py` works**

`tools/process.py` (~2200 lines) + `tools/pygw.py`. `pygw` finds engine globals by
byte-signature too, then walks the client's real object graph:

```python
# pygw.py:16-23
tmp = self.scanner.find(b'\x50\x6A\x0F\x6A\x00\xFF\x35', +7)
self.ctx, = proc.read(tmp)
...
def get_map_ctx(self):
    return self.proc.read(self.get_game_ctx() + 0x14)[0]
```

`tools/draw-map.py` then dumps the **pathing map** structures straight out of the
live client (`get_pathing_maps()`) and draws them. This is how upstream figured
out the pathfinding data layout in the first place: load a map in the real client,
dump the parsed structures, and compare against the raw `.dat` bytes.

**This is the single most valuable tool we have for map work**, and it needs no
Ghidra — just a running client on the map you care about.

## How to find a map's `map_file_id` without Ghidra

We need, for each Pre-Searing map, the `file_id` whose blob inside `Gw.dat` is
that map. There is a cheap, fully deterministic way to enumerate every map file in
the archive:

1. Walk every `file_id` in the MFT (`FaArchive.c` already has them all in
   `file_hash_table`).
2. `FaGetFile` each one.
3. Keep the ones where `RiffParseAndGetType` returns `RIFF_MAP1` or `RIFF_MAP2`
   (`GmMapDataImport.c:32-37`).
4. Among those, keep the ones that contain chunk `(2 << 28) | ChunkId_Path` —
   i.e. the ones `GmImportMap` can actually load.

That yields the complete set of loadable map files. What is left is only
**naming** them: matching each blob to a `MapId`. Ways to do that, cheapest first:

- **Correlate with a live client**: load map X in the real client, use
  `pygw`/`process.py` to read the loaded map's file id out of the client's map
  context. Direct, exact, and no guessing.
- **Pathing graph fingerprinting**: each map's pathfinding graph has a
  characteristic node/portal structure; match against a drawn `draw-map.py` output.
- **Community references**: the GW community has published map→file-id lists for
  `Gw.dat` over the years; cross-check candidates instead of trusting them blindly.

Note that step 3/4 also works as a **regression test**: the number of loadable map
files in a given `Gw.dat` is a stable, checkable number.

## Where Ghidra will actually be needed

Ranked by how likely we are to need it:

1. **Understanding what the client expects from the server** — this is the big
   one. For every feature OpenTyria does not implement yet (NPC behaviour, quests,
   merchants, the character-creation flow, skill activation), the source of truth
   is "what does the client do with this packet". Reading the handler in `Gw.exe`
   in Ghidra is often faster than black-box guessing from captures.
2. **Repairing `pygw.py` / `patch-gw.py` after a client update** — when a
   signature stops matching, Ghidra is how you find the new one.
3. **Finding how the client resolves "map id → archive file"** — if the
   correlation approach above stalls, the client's own lookup table settles it.
4. **`portal.dll` behaviour** — understanding what the real portal notification
   carries, if `portal/portal.c` needs to be extended.

**Not needed for:** reading `Gw.dat`. Ever. That is a parsing problem, and the
parsers exist.

## Practical recommendation

Before opening Ghidra for anything, check in this order:

1. Is it already implemented in `code/OpenTyria/`? (grep first — this codebase is
   ~30k lines and covers more than it looks like)
2. Can it be observed from a live client with `tools/process.py` + `pygw.py`?
3. Does a packet capture answer it? (`tools/trace-packets.py`)
4. Only then: Ghidra on `Gw.exe`.
