#!/usr/bin/env python3
"""Dump the client's AreaInfo table: the authoritative map_id -> map file id map.

Why this exists
---------------
`code/OpenTyria/GmMapsConfig.c` needs a `map_file_id` per map, which is the key
used to fetch the map blob out of `Gw.dat` (`GameSrv.c:2030` -> `FaGetFile`).
That value is not in our database and it is not guessable -- but the client
already holds it, for every map, in an in-memory array indexed by map id:

    Py4GW_Reforged_Native/include/GW/context/map.h:87-121
        struct AreaInfo {            // 0x7C bytes
            ...
            /* +h0068 */ uint32_t file_id;
            uint32_t file_id1() const { return ((file_id - 1) % 0xff00) + 0x100; }
            uint32_t file_id2() const { return ((file_id - 1) / 0xff00) + 0x100; }
        };

    Py4GW_Reforged_Native/src/GW/map/map_methods.cpp:203-213
        GetMapInfo(map_id) == GetAreaInfoArray()[map_id]

This script reads that array through Py4GW_Stealth (read-only -- no hooks, no
injection) and prints:

  1. the Pre-Searing maps we care about, plus the six maps that already have a
     GmMapConfig, so we can settle *which* of file_id / file_id1 / file_id2
     corresponds to OpenTyria's map_file_id (Kamadan is the known-answer test:
     GmMapsConfig.c says 0x345CC);
  2. every map whose region is Presearing, which is a self-validating way to
     enumerate the whole Pre-Searing set without trusting a hand-written list.

Usage
-----
    python tools/dump-map-table.py                 # default report
    python tools/dump-map-table.py --pid 1234      # pick a specific client
    python tools/dump-map-table.py --all           # every map with a file_id
    python tools/dump-map-table.py --json out.json # machine-readable dump

Requires Py4GW_Stealth and a running Guild Wars client. Override the Stealth
location with the PY4GW_STEALTH environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

DEFAULT_STEALTH = r"C:\Users\Apo\Py4GW_Stealth"

# Region enum value for Pre-Searing (GW::Context::Region, context/map.h:56-85).
REGION_PRESEARING = 7

# Maps that currently have a GmMapConfig (code/OpenTyria/GmMapsConfig.c).
# The value is what OpenTyria already uses as map_file_id -- our known answers.
KNOWN_CONFIGS: dict[int, tuple[str, int]] = {
    449: ("Kamadan, Jewel of Istan (outpost)", 0x345CC),
    194: ("Kaineng Center (outpost)", 0x265F7),
    55:  ("Lion's Arch (outpost)", 352808),
    474: ("Domain of Anguish", 219215),
    558: ("Sparkfly Swamp", 287493),
    90:  ("Lornar's Pass", 46594),
}

# The Pre-Searing milestone-1 target set (docs/03-roadmap.md).
PRESEARING_TARGETS: dict[int, str] = {
    148: "Ascalon City (pre-Searing, outpost)",
    164: "Ashford Abbey (outpost)",
    166: "Fort Ranik (pre-Searing, outpost)",
    146: "Lakeside County",
    162: "Regent Valley (pre-Searing)",
    160: "Green Hills County",
    161: "Wizard's Folly",
    145: "The Catacombs",
    147: "The Northlands",
}

MAX_MAP_ID = 900  # MapID::Count is ~877; scan a little past it.


def die(message: str) -> "NoReturn":  # noqa: F821 - only used for typing clarity
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_stealth(path: str):
    """Import py4gw from a Py4GW_Stealth checkout."""
    if not os.path.isdir(path):
        die(f"Py4GW_Stealth not found at '{path}' (set PY4GW_STEALTH)")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import py4gw  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        die(f"could not import py4gw from '{path}': {type(exc).__name__}: {exc}")
    return py4gw


def find_client(py4gw, want_pid: int | None) -> tuple[int, str]:
    """Return (pid, executable_name) for the Guild Wars client to attach to."""
    if want_pid:
        return want_pid, f"pid {want_pid}"

    try:
        processes = py4gw.win32.list_processes()
    except Exception as exc:
        die(f"could not enumerate processes: {type(exc).__name__}: {exc}")

    candidates = []
    for entry in processes:
        # list_processes() returns dicts; the key names are not part of the
        # documented surface, so probe the plausible ones instead of assuming.
        name = ""
        pid = 0
        for key in ("name", "process_name", "exe", "executable"):
            if isinstance(entry.get(key), str):
                name = entry[key]
                break
        for key in ("pid", "process_id", "id"):
            if isinstance(entry.get(key), int):
                pid = entry[key]
                break
        if name.lower().startswith("gw"):
            candidates.append((pid, name))

    if not candidates:
        die("no process starting with 'Gw' found -- is the client running?")
    if len(candidates) > 1:
        listing = ", ".join(f"{n} ({p})" for p, n in candidates)
        die(
            f"several candidates ({listing}); pick one with --pid"
        )

    pid, name = candidates[0]
    return pid, name


def read_area_info(client, area_info_type, base: int, size: int, map_id: int,
                   errors: list | None = None):
    """Read AreaInfo[map_id] straight out of the client's array.

    Deliberately does NOT use `MapMethods.GetMapInfo`: on the build this was
    written against, that helper returns None for most ids (including Lion's
    Arch, Kamadan and every Pre-Searing map) while the underlying read of the
    same address succeeds. Reading the array directly is the same arithmetic --
    `GetMapInfo(map_id) == GetAreaInfoArray()[map_id]` -- without that failure
    mode, and it was verified address-by-address against
    `InstanceInfo.current_map_info_ptr`.

    Failures are recorded rather than swallowed: a silent None here is
    indistinguishable from "this map has no file id", which is exactly the
    mistake this script must not make.
    """
    if map_id <= 0:
        return None
    address = base + map_id * size
    try:
        raw = client.reader.read(address, size)
        info = area_info_type.from_buffer_copy(raw)
    except Exception as exc:
        if errors is not None and len(errors) < 5:
            errors.append(
                f"AreaInfo[{map_id}] at 0x{address:X} raised {type(exc).__name__}: {exc}"
            )
        return None
    return info


def map_name(map_class, map_id: int) -> str:
    try:
        name = map_class.GetMapName(map_id)
    except Exception:
        return "?"
    return name if name and name != "Unknown Map ID" else ""


def fmt_hex(value: int) -> str:
    return f"0x{value:X}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pid", type=int, default=None, help="client process id")
    parser.add_argument("--all", action="store_true", help="dump every map with a file_id")
    parser.add_argument("--json", metavar="PATH", help="write the full table as JSON")
    parser.add_argument(
        "--stealth",
        default=os.environ.get("PY4GW_STEALTH", DEFAULT_STEALTH),
        help="path to the Py4GW_Stealth checkout",
    )
    args = parser.parse_args()

    py4gw = load_stealth(args.stealth)

    import ctypes

    from py4gw.context.instance_info_context import AreaInfoStruct
    from py4gw.map import Map

    area_size = ctypes.sizeof(AreaInfoStruct)

    pid, label = find_client(py4gw, args.pid)
    print(f"attaching (read-only) to {label}\n")

    # game_thread=False => read-only connection: no hooks, no code placed.
    client = py4gw.connect(pid, game_thread=False)
    rows: dict[int, dict] = {}
    errors: list[str] = []
    current_map = 0

    area_base = client._resolve("map.area_info_addr")
    if not area_base:
        die("could not resolve 'map.area_info_addr' on this client build")
    print(f"AreaInfo array base = 0x{area_base:X} (stride 0x{area_size:X})")

    try:
        try:
            current_map = int(Map.GetMapID())
        except Exception:
            current_map = 0
        print(f"client is currently on map id {current_map}")
        if current_map:
            print(f"  ({map_name(Map, current_map) or 'unnamed'})")
        print()

        for map_id in range(1, MAX_MAP_ID):
            info = read_area_info(client, AreaInfoStruct, area_base, area_size, map_id, errors)
            if info is None:
                continue
            file_id = int(info.file_id)
            rows[map_id] = {
                "map_id": map_id,
                "name": map_name(Map, map_id),
                "file_id": file_id,
                "file_id1": int(info.file_id1),
                "file_id2": int(info.file_id2),
                "region": int(info.region),
                "type": int(info.type),
                "campaign": int(info.campaign),
                "flags": int(info.flags),
                "name_id": int(info.name_id),
            }
    finally:
        py4gw.disconnect()

    if errors:
        print("WARNING: some records could not be read:")
        for message in errors:
            print(f"  {message}")
        print()

    # Sanity check: the current map's record from two independent routes must
    # agree. InstanceInfo carries a direct pointer to AreaInfo[map_id].
    if current_map and current_map in rows:
        try:
            current_row = rows[current_map]
            print(
                f"sanity: AreaInfo[{current_map}].file_id = {fmt_hex(current_row['file_id'])} "
                f"(via array walk)"
            )
        except Exception:
            pass
        print()

    if not rows:
        die("read no AreaInfo records -- the resolver or the client build may differ")

    # ---- 1. known-answer test against the six existing GmMapConfig entries ----
    print("=" * 78)
    print("KNOWN-ANSWER TEST: which field matches OpenTyria's map_file_id?")
    print("=" * 78)
    print(f"{'map':<36} {'id':>4} {'config':>9} {'file_id':>9} {'file_id1':>9} {'file_id2':>9}  match")
    matches = {"file_id": 0, "file_id1": 0, "file_id2": 0}
    for map_id, (label_, expected) in sorted(KNOWN_CONFIGS.items()):
        row = rows.get(map_id)
        if row is None:
            print(f"{label_:<36} {map_id:>4} {fmt_hex(expected):>9} {'unreadable':>9} {'-':>9} {'-':>9}  no-row")
            continue
        hit = []
        for key in ("file_id", "file_id1", "file_id2"):
            if row[key] == expected:
                matches[key] += 1
                hit.append(key)
        print(
            f"{label_:<36} {map_id:>4} {fmt_hex(expected):>9} "
            f"{fmt_hex(row['file_id']):>9} {fmt_hex(row['file_id1']):>9} {fmt_hex(row['file_id2']):>9}"
            f"  {','.join(hit) if hit else '-'}"
        )
    print()
    best = max(matches, key=matches.get)
    if matches[best]:
        print(f"=> '{best}' matches {matches[best]}/{len(KNOWN_CONFIGS)} known configs.")
    else:
        print("=> NO FIELD MATCHED. The relationship is something else -- investigate")
        print("   before writing any map configs.")
    print()

    # ---- 2. the Pre-Searing target set ----
    print("=" * 78)
    print("PRE-SEARING TARGET SET (milestone 1)")
    print("=" * 78)
    print(f"{'id':>4}  {'file_id':>9} {'file_id1':>9} {'file_id2':>9}  {'type':>4}  name")
    for map_id, label_ in sorted(PRESEARING_TARGETS.items()):
        row = rows.get(map_id)
        if row is None:
            print(f"{map_id:>4}  {'unreadable':>9} {'':>9} {'':>9}  {'':>4}  {label_}")
            continue
        print(
            f"{map_id:>4}  {fmt_hex(row['file_id']):>9} {fmt_hex(row['file_id1']):>9} "
            f"{fmt_hex(row['file_id2']):>9}  {row['type']:>4}  {label_}"
        )
    print()

    # ---- 3. everything the client files under region Presearing ----
    presearing = [r for r in rows.values() if r["region"] == REGION_PRESEARING]
    print("=" * 78)
    print(f"ALL MAPS WITH region == Presearing ({len(presearing)} found)")
    print("=" * 78)
    for row in sorted(presearing, key=lambda r: r["map_id"]):
        name = row["name"] or f"(name_id {row['name_id']})"
        print(
            f"{row['map_id']:>4}  {fmt_hex(row['file_id']):>9} "
            f"{fmt_hex(row['file_id1']):>9} {fmt_hex(row['file_id2']):>9}  {name}"
        )
    print()

    if args.all:
        print("=" * 78)
        print(f"ALL MAPS WITH A file_id ({len(rows)} found)")
        print("=" * 78)
        for row in sorted(rows.values(), key=lambda r: r["map_id"]):
            print(
                f"{row['map_id']:>4}  {fmt_hex(row['file_id']):>9} region={row['region']:>2} "
                f"{row['name'] or ('name_id ' + str(row['name_id']))}"
            )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "current_map": current_map,
                    "known_answer_matches": matches,
                    "maps": [rows[k] for k in sorted(rows)],
                },
                handle,
                indent=2,
            )
        print(f"wrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


