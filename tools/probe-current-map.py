#!/usr/bin/env python3
"""Read the CURRENT map's file id from a live client, and cross-check it
against the Gw.dat map-blob list produced by gwdat-scan.

Run elevated (Stealth needs PROCESS_VM_WRITE even for read-only).
"""

from __future__ import annotations

import csv
import ctypes
import os
import sys

STEALTH = os.environ.get("PY4GW_STEALTH", r"C:\Users\Apo\Py4GW_Stealth")
if STEALTH not in sys.path:
    sys.path.insert(0, STEALTH)

import py4gw
from py4gw.context.instance_info_context import AreaInfoStruct

CSV_PATH = os.environ.get(
    "GW_MAPS_CSV",
    r"C:\Users\Apo\Documents\GitHub\GWPS\data\gwdat-maps.csv",
)

PRESEARING_IDS = [
    143, 145, 146, 147, 148, 149, 150, 151, 160, 161, 162, 163, 164, 165, 166,
    408, 409, 410, 411, 412, 779,
]


def find_gw_pid() -> int:
    for entry in py4gw.win32.list_processes():
        name = ""
        for key in ("name", "process_name", "exe", "executable"):
            if isinstance(entry.get(key), str):
                name = entry[key]
                break
        if name.lower().startswith("gw"):
            return int(entry.get("pid") or entry.get("process_id") or entry.get("id"))
    raise SystemExit("no Gw process found")


def load_blobs() -> dict[int, dict]:
    blobs = {}
    if not os.path.exists(CSV_PATH):
        return blobs
    with open(CSV_PATH, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            blobs[int(row["file_id"], 16)] = row
    return blobs


def hx(v: int) -> str:
    return f"0x{v:08X}"


def main() -> int:
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else find_gw_pid()
    blobs = load_blobs()
    print(f"pid {pid}; {len(blobs)} map blobs in {os.path.basename(CSV_PATH)}")

    client = py4gw.connect(pid, game_thread=False)
    try:
        # ---- current map, two independent ways ----
        from py4gw.map import Map

        map_id = int(Map.GetMapID())
        print(f"\ncurrent map id = {map_id}  ({Map.GetMapName(map_id)})")

        info = py4gw.context.instanceinfo.get()
        area = info.current_map_info if info is not None else None
        if area is None:
            print("InstanceInfo.current_map_info unavailable")
        else:
            print("\ncurrent AreaInfo (via InstanceInfo pointer):")
            for field in ("campaign", "continent", "region", "type", "flags",
                          "file_id", "name_id", "description_id"):
                print(f"  {field:<16} {getattr(area, field, '<missing>')}")
            file_id = int(area.file_id)
            print(f"  file_id          {file_id}  ({hx(file_id)})")
            print(f"  file_id1         {area.file_id1}  ({hx(area.file_id1)})")
            print(f"  file_id2         {area.file_id2}  ({hx(area.file_id2)})")

            for label, value in (("file_id", file_id),
                                 ("file_id1", int(area.file_id1)),
                                 ("file_id2", int(area.file_id2))):
                row = blobs.get(value)
                if row:
                    print(f"\n  MATCH: {label} {hx(value)} IS a Gw.dat map blob "
                          f"(size={row['size']}, chunks={row['chunk_count']}, "
                          f"twin={row['paired_with']})")
                else:
                    print(f"  {label} {hx(value)}: not in the map-blob list")

        # ---- array walk, for the same map id and the whole Pre-Searing set ----
        size = ctypes.sizeof(AreaInfoStruct)
        base = client._resolve("map.area_info_addr")
        print(f"\nAreaInfo array base = {hx(base)}, stride {hx(size)}")

        def read_one(mid: int):
            raw = client.reader.read(base + mid * size, size)
            return AreaInfoStruct.from_buffer_copy(raw)

        walked = read_one(map_id)
        print(f"array walk AreaInfo[{map_id}].file_id = {hx(int(walked.file_id))}"
              f"  (region={walked.region} type={walked.type})")

        populated = []
        for mid in range(1, 900):
            try:
                row = read_one(mid)
            except Exception:
                continue
            if int(row.file_id) != 0:
                populated.append((mid, int(row.file_id), int(row.region), int(row.type)))
        print(f"\npopulated AreaInfo entries now: {len(populated)}")
        for mid, fid, region, mtype in populated:
            blob = "BLOB" if fid in blobs else "    "
            print(f"  {mid:>4} file_id={hx(fid)} region={region:<3} type={mtype:<3} {blob}")

        print("\nPre-Searing ids:")
        for mid in PRESEARING_IDS:
            try:
                row = read_one(mid)
            except Exception as exc:
                print(f"  {mid:>4} read failed: {type(exc).__name__}")
                continue
            fid = int(row.file_id)
            blob = "BLOB" if fid in blobs else ""
            print(f"  {mid:>4} file_id={hx(fid)} type={row.type:<3} {blob}")
        return 0
    finally:
        py4gw.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
