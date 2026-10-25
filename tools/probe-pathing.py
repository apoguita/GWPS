"""Fingerprint the map the client is standing in, and find its Gw.dat blob.

Why
---
`GmMapConfig` needs a `map_file_id` per map, and the client will not tell us:
`AreaInfo.file_id` reads 0 for every Pre-Searing map, even while standing in one
(`docs/06-client-tooling.md`, F5). But the stage-2 `Path` chunk of the blob *is*
the navmesh, and the client keeps the same navmesh in memory for the loaded map.
So: compute (plane count, trapezoid count, bounding box) from the client's own
pathing records, and match it against the same fingerprint computed from Gw.dat by
`tools/gwdat-pathing.c`.

Three independent numbers have to agree for a match, and 213 blobs are in play, so
an accidental collision is not a realistic worry; a real match is confirmed by
loading the blob in the server afterwards.

Needs an elevated shell
-----------------------
`py4gw.connect()` asserts an elevated token: connecting is a write (block,
dispatcher, hooks). Start PowerShell as administrator and approve the UAC prompt.
Unelevated it prints the reason and exits 2. Nothing here changes the game.

Usage
-----
    py tools/probe-pathing.py                    # match against build/pathing-fingerprints.csv
    py tools/probe-pathing.py --csv other.csv
    py tools/probe-pathing.py --json build/probe-pathing.json

Exit codes: 0 matched (or fingerprint printed with no sheet), 2 not elevated,
3 no client / not in a map, 4 could not read the pathing records.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

DEFAULT_PY4GW_ROOT = r"C:\Users\Apo\Py4GW_Stealth"
DEFAULT_CSV = "build/pathing-fingerprints.csv"


def hx(value: int) -> str:
    return f"0x{value:08X}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fingerprint the loaded map's navmesh.")
    parser.add_argument("--py4gw-root", default=os.environ.get("PY4GW_STEALTH", DEFAULT_PY4GW_ROOT))
    parser.add_argument("--csv", default=DEFAULT_CSV, help="fingerprint sheet from gwdat_pathing")
    parser.add_argument("--json", default=None, help="also write the report as JSON here")
    parser.add_argument("--pid", type=int, default=None)
    args = parser.parse_args(argv)

    root = Path(args.py4gw_root)
    if not (root / "py4gw").is_dir():
        print(f"py4gw not found under {root}", file=sys.stderr)
        return 3
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import py4gw
    from py4gw.map import Map
    from py4gw.player import Player
    from py4gw.win32 import Win32

    win32 = Win32()
    if not win32.is_elevated():
        print("this needs an elevated shell: py4gw.connect() is a write.", file=sys.stderr)
        print("start PowerShell as administrator (approve the UAC prompt) and run it again.",
              file=sys.stderr)
        return 2

    clients = [c for c in win32.find_guild_wars()
               if args.pid is None or int(c["pid"]) == args.pid]
    if not clients:
        print("no Gw.exe is running", file=sys.stderr)
        return 3

    report: dict = {"client": {"pid": int(clients[0]["pid"]), "path": clients[0].get("path")}}
    client = py4gw.connect(clients[0])
    try:
        map_id = int(Map.GetMapID() or 0)
        if not map_id:
            print("the client is not in a map (no map id yet)", file=sys.stderr)
            return 3
        report["map"] = {"id": map_id, "name": Map.GetMapName(map_id)}

        try:
            position = Player.GetXY()
            report["position"] = {"x": round(float(position[0]), 3), "y": round(float(position[1]), 3)}
        except Exception as exc:  # noqa: BLE001 - position is a bonus, not the point
            report["position_error"] = repr(exc)

        pathing_maps = Map.Pathing.GetPathingMaps()
        if not pathing_maps:
            print("the client reports no pathing records for this map", file=sys.stderr)
            return 4

        planes = len(pathing_maps)
        trapezoids = 0
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for plane in pathing_maps:
            # A plane is a `PathingMap` snapshot, not a list: the trapezoids live
            # under `.trapezoids` (py4gw/context/map_context.py).
            for trap in getattr(plane, "trapezoids", ()):
                for x in (trap.XTL, trap.XTR, trap.XBL, trap.XBR):
                    x = float(x)
                    if x < min_x:
                        min_x = x
                    if max_x < x:
                        max_x = x
                for y in (trap.YT, trap.YB):
                    y = float(y)
                    if y < min_y:
                        min_y = y
                    if max_y < y:
                        max_y = y
                trapezoids += 1

        fingerprint = {
            "planes": planes,
            "trapezoids": trapezoids,
            "min_x": round(min_x, 3), "min_y": round(min_y, 3),
            "max_x": round(max_x, 3), "max_y": round(max_y, 3),
        }
        report["fingerprint"] = fingerprint
        print(f"map {map_id} ({report['map']['name']})")
        if "position" in report:
            print(f"  player position  {report['position']['x']}, {report['position']['y']}"
                  f"   <- a usable spawn point for this map")
        print(f"  fingerprint      planes={planes} trapezoids={trapezoids} "
              f"bounds=({min_x:.3f}, {min_y:.3f}) .. ({max_x:.3f}, {max_y:.3f})")

        sheet = Path(args.csv)
        if not sheet.is_file():
            print(f"\nno fingerprint sheet at {sheet}; run gwdat_pathing first", file=sys.stderr)
            return 0

        matches = []
        with sheet.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if (int(row["planes"]) == planes
                        and int(row["trapezoids"]) == trapezoids
                        and abs(float(row["min_x"]) - min_x) < 0.01
                        and abs(float(row["min_y"]) - min_y) < 0.01
                        and abs(float(row["max_x"]) - max_x) < 0.01
                        and abs(float(row["max_y"]) - max_y) < 0.01):
                    matches.append(row)

        report["matches"] = matches
        if not matches:
            print("\nNO MATCH in the sheet. The loaded navmesh is not one of the fingerprinted "
                  "blobs; re-run gwdat_pathing over the full size range.", file=sys.stderr)
            return 4

        print(f"\n{len(matches)} matching blob(s) — a map is stored twice, so two is the expected "
              f"answer:")
        for row in matches:
            print(f"  file_id {row['file_id']}  size={row['size']}  "
                  f"planes={row['planes']} trapezoids={row['trapezoids']}")
        print(f"\nGmMapConfig candidate:\n"
              f"    .map_id      = {map_id},\n"
              f"    .map_file_id = {matches[0]['file_id']},   // confirm with the twin above")
        return 0
    finally:
        py4gw.disconnect()
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"\nreport -> {args.json}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
