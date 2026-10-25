#!/usr/bin/env python3
"""Parse Gw.dat's MFT directly, mirroring code/OpenTyria/FaArchive.c.

Purpose: settle whether OpenTyria's `GmMapConfig.map_file_id` (a uint32 fed to
FaGetFile) is the same identifier as the client's `AreaInfo.file_id`, and
characterise which archive file ids exist.

Layout is taken verbatim from code/OpenTyria/FaArchive.h:

    FaHeader   { magic, header_size, block_size, checksum, mft_offset(u64),
                 mft_size, flags }                                   = 32 bytes
    MFTHeader  { file_id, h0004, h0008, entry_count, h0010, h0014 }  = 24 bytes
    MFTEntry   { offset(u64), size, compressed(u16), flags, stream,
                 next_stream, checksum }                             = 24 bytes
    MFTFileName{ file_id, file_index }                               =  8 bytes

FaOpen reads the MFT entries (entry_count of them), then takes entry INDEX_TOC
(=1) and reads toc.size / 8 MFTFileName records; each gives file_id -> file_index
(1-based into the entries array -- FaGetFile does `--file_idx`).

Usage:
    python tools/gwdat-mft.py <Gw.dat>                # summary + known-id probe
    python tools/gwdat-mft.py <Gw.dat> --list         # every file id
    python tools/gwdat-mft.py <Gw.dat> --probe ID,ID  # specific ids (hex or dec)
"""

from __future__ import annotations

import argparse
import struct
import sys

INDEX_TOC = 1
HEADER = struct.Struct("<III I Q I I")   # FaHeader, 32 bytes packed
MFT_HEADER = struct.Struct("<IIIIII")    # MFTHeader, 24 bytes
MFT_ENTRY = struct.Struct("<QIHBBII")    # MFTEntry, 24 bytes
MFT_NAME = struct.Struct("<II")          # MFTFileName, 8 bytes

# The six file ids OpenTyria already ships in code/OpenTyria/GmMapsConfig.c.
KNOWN_CONFIGS = {
    449: ("Kamadan, Jewel of Istan", 0x345CC),
    194: ("Kaineng Center", 0x265F7),
    55:  ("Lion's Arch", 352808),
    474: ("Domain of Anguish", 219215),
    558: ("Sparkfly Swamp", 287493),
    90:  ("Lornar's Pass", 46594),
}

# AreaInfo.file_id values observed live for the maps the client had populated.
OBSERVED_AREA_INFO = {
    4: 128183, 5: 128185, 6: 128187, 7: 128183, 8: 128185, 9: 128187,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dat")
    parser.add_argument("--list", action="store_true", help="list every file id")
    parser.add_argument("--probe", help="comma separated ids (0x prefix ok)")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    with open(args.dat, "rb") as handle:
        raw = handle.read(HEADER.size)
        if len(raw) < HEADER.size:
            print("file too small for a FaHeader", file=sys.stderr)
            return 1
        magic, header_size, block_size, checksum, mft_offset, mft_size, flags = HEADER.unpack(raw)
        print(f"magic       0x{magic:08X}  (bytes {raw[:4]!r})")
        print(f"header_size {header_size}")
        print(f"block_size  {block_size}")
        print(f"mft_offset 0x{mft_offset:X} ({mft_offset})")
        print(f"mft_size   {mft_size}")
        print(f"flags      {flags:#x}")
        print()

        handle.seek(mft_offset)
        raw = handle.read(MFT_HEADER.size)
        h_file_id, h0004, h0008, entry_count, h0010, h0014 = MFT_HEADER.unpack(raw)
        print(f"MFTHeader file_id={h_file_id} h0004={h0004} h0008={h0008} "
              f"entry_count={entry_count} h0010={h0010} h0014={h0014}")
        print()

        entries = []
        for _ in range(entry_count):
            raw = handle.read(MFT_ENTRY.size)
            if len(raw) < MFT_ENTRY.size:
                break
            entries.append(MFT_ENTRY.unpack(raw))
        print(f"read {len(entries)} MFT entries")
        print()

        # TOC entry -> file_id / file_index pairs
        if INDEX_TOC >= len(entries):
            print("TOC entry out of range", file=sys.stderr)
            return 1
        toc_offset, toc_size, *_ = entries[INDEX_TOC]
        count = toc_size // MFT_NAME.size
        handle.seek(toc_offset)
        names = []
        for _ in range(count):
            raw = handle.read(MFT_NAME.size)
            if len(raw) < MFT_NAME.size:
                break
            names.append(MFT_NAME.unpack(raw))
        print(f"TOC at 0x{toc_offset:X}: {len(names)} file ids")
        print()

        file_ids = {file_id for file_id, _ in names}
        print(f"distinct file ids: {len(file_ids)}")
        print(f"min file id 0x{min(file_ids):X}  max 0x{max(file_ids):X}")
        print()

        # ---- probe: do the known GmMapConfig ids exist as MFT keys? ----
        print("KNOWN GmMapConfig.map_file_id probes:")
        print(f"  {'map':<24} {'config id':>10}  in-MFT  entry(offset,size,compressed,flags,stream)")
        for map_id, (label, value) in sorted(KNOWN_CONFIGS.items()):
            print(f"  {label:<24} 0x{value:>8X}  {describe(value, names, entries):<8}")
        print()

        print("OBSERVED AreaInfo.file_id probes:")
        print(f"  {'map':>4} {'area file_id':>13}  in-MFT  entry(offset,size,compressed,flags,stream)")
        for map_id, value in sorted(OBSERVED_AREA_INFO.items()):
            print(f"  {map_id:>4} 0x{value:>11X}  {describe(value, names, entries):<8}")
        print()

        # ---- packed decomposition of every file id, to compare with AreaInfo ----
        print("How AreaInfo packs file_id1/file_id2 explains the archive key:")
        for map_id, value in sorted(OBSERVED_AREA_INFO.items())[:3]:
            f1 = ((value - 1) % 0xFF00) + 0x100
            f2 = ((value - 1) // 0xFF00) + 0x100
            print(f"  AreaInfo[{map_id}] = {value} -> file_id1=0x{f1:X} file_id2=0x{f2:X}")
        value = KNOWN_CONFIGS[449][1]
        f1 = ((value - 1) % 0xFF00) + 0x100
        f2 = ((value - 1) // 0xFF00) + 0x100
        print(f"  Kamadan config   = {value} -> file_id1=0x{f1:X} file_id2=0x{f2:X}")
        print()

        if args.probe:
            print("explicit probes:")
            for token in args.probe.split(","):
                token = token.strip()
                if not token:
                    continue
                value = int(token, 0)
                print(f"  0x{value:X}: {describe(value, names, entries)}")
            print()

        if args.list:
            print("all file ids (id, entries, offset, size, compressed, flags, stream):")
            for file_id, file_index in sorted(names):
                info = lookup(entries, file_index)
                if info is None:
                    print(f"  0x{file_id:08X}  (index {file_index} out of range)")
                    continue
                offset, size, compressed, eflags, stream, _next, _cks = info
                print(f"  0x{file_id:08X}  idx={file_index:<6} off=0x{offset:010X} "
                      f"size={size:<9} comp={compressed} flags={eflags} stream={stream}")
    return 0


def lookup(entries, file_index):
    index = file_index - 1
    if index < 0 or index >= len(entries):
        return None
    return entries[index]


def describe(value: int, names, entries) -> str:
    for file_id, file_index in names:
        if file_id == value:
            info = lookup(entries, file_index)
            if info is None:
                return "in-MFT (bad index)"
            offset, size, compressed, eflags, stream, _next, _cks = info
            return f"yes  off=0x{offset:X} size={size} comp={compressed} flags={eflags} stream={stream}"
    return "NO"


if __name__ == "__main__":
    raise SystemExit(main())
