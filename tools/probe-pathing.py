"""Fingerprint the map the client is standing in, and find its Gw.dat blob.

Why
---
`GmMapConfig` needs a `map_file_id` per map, and the client will not volunteer it:
`AreaInfo.file_id` reads 0 for every Pre-Searing map, even while standing in one
(`docs/06-client-tooling.md`, F5), and a blob carries no map identity of its own.
But the stage-2 `Path` chunk of a blob *is* the navmesh, and the client holds the
same navmesh for the map it is in. So: fingerprint the client's own pathing records
(planes, trapezoid count, bounding box) and match it against the same fingerprint
computed from Gw.dat by `tools/gwdat-pathing.c`.

A map is stored twice, so the expected answer is a pair. Every map's fingerprint is
distinct (297 distinct across 594 blobs), so a match is not a coincidence -- but it
does say "this blob has the navmesh the client is using", not "this blob is that map
by name". The name comes from `Map.GetMapName`, and from the tester's eyes.

Needs an elevated shell
-----------------------
`py4gw.connect()` asserts an elevated token: connecting is a write (block,
dispatcher, hooks). Start PowerShell as administrator and approve the UAC prompt.
Unelevated the script prints the reason and exits 2. Nothing here changes the game.

Which client to point it at
---------------------------
The client whose game server actually has the map loaded:

* **A map GWPS has no config for** -> the **live** client (plain `Gw.exe`, ArenaNet's
  server). GWPS cannot host such a map: `GameSrv_LoadMap` has no `GmMapConfig` and
  falls back to Kamadan, so a probe against our server would report map 449.
* **Verifying a config that exists** -> the patched client (`Gw.custom.exe` with
  `portal.dll`, `-authsrv 127.0.0.1`), which is what proves our blob and spawn point.

If both clients are running, `--list` shows them and `--pid` picks one. The map id in
the output is the check: 449 means the fallback happened and you are on the wrong side.

Usage
-----
    py tools/probe-pathing.py --list                  # no elevation, no client needed
    py tools/probe-pathing.py                         # the only Gw* client running
    py tools/probe-pathing.py --pid 37264             # a specific one
    py tools/probe-pathing.py --dump-trapezoids build/map.csv --json build/map.json

Exit codes: 0 ok, 2 not elevated, 3 no client / not in a map, 4 could not read pathing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

DEFAULT_PY4GW_ROOT = r"C:\Users\Apo\Py4GW_Stealth"
DEFAULT_CSV = "build/pathing-all.csv"


def find_clients(win32, pid):
    """Find the client, including the *patched* one.

    ``Win32.find_guild_wars()`` matches the executable name ``Gw.exe``. GWPS tests run
    the patched client, ``Gw.custom.exe`` (see ``scripts/phase0-prepare.ps1``), which
    that matcher never returns -- so this falls back to any process whose name starts
    with ``gw``, excluding our own server. ``--pid`` skips discovery entirely.
    """
    if pid is not None:
        return [{"pid": int(pid), "name": None, "path": None}]

    clients = list(win32.find_guild_wars())
    if clients:
        return clients

    for entry in win32.list_processes():
        name = str(entry.get("name") or "")
        lowered = name.lower()
        if lowered.startswith("gw") and not lowered.startswith("gwps"):
            path = None
            try:
                path, _ = win32._get_image_path(int(entry["pid"]))
            except Exception:
                pass
            clients.append({"pid": int(entry["pid"]), "name": name, "path": path})
    return clients


def fingerprint(pathing_maps):
    """(planes, trapezoids, bounding box) over the client's own pathing records."""
    planes = len(pathing_maps)
    trapezoids = 0
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    rows = []

    for plane_index, plane in enumerate(pathing_maps):
        # A plane is a `PathingMap` snapshot, not a list: its trapezoids live
        # under `.trapezoids` (py4gw/context/map_context.py).
        for trap in getattr(plane, "trapezoids", ()):
            for x in (float(trap.XTL), float(trap.XTR), float(trap.XBL), float(trap.XBR)):
                min_x = min(min_x, x)
                max_x = max(max_x, x)
            for y in (float(trap.YT), float(trap.YB)):
                min_y = min(min_y, y)
                max_y = max(max_y, y)
            trapezoids += 1
            rows.append(
                "{},{},{:.2f},{:.2f},{:.2f},{:.2f},{:.2f},{:.2f}".format(
                    plane_index, int(getattr(trap, "id", -1)),
                    float(trap.XTL), float(trap.XTR), float(trap.YT),
                    float(trap.XBL), float(trap.XBR), float(trap.YB))
            )

    return ({
        "planes": planes,
        "trapezoids": trapezoids,
        "min_x": round(min_x, 3), "min_y": round(min_y, 3),
        "max_x": round(max_x, 3), "max_y": round(max_y, 3),
    }, rows)


def match_sheet(sheet, fp, tolerance=0.0):
    """Rows matching the fingerprint. ``tolerance`` allows a trapezoid-count delta.

    Exact matching is the normal case. A small delta is a real possibility, not a
    rounding artefact: The Northlands reads 6889 trapezoids in the client and 6890
    through `GmImportMap` for the two blobs whose planes and bounds match exactly, so
    the importer and the client can disagree by one. Callers should treat a tolerant
    match as "verify by terrain", never as proof.
    """
    matches = []
    with sheet.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if int(row["planes"]) != fp["planes"]:
                continue
            if abs(int(row["trapezoids"]) - fp["trapezoids"]) > tolerance:
                continue
            if (abs(float(row["min_x"]) - fp["min_x"]) < 0.5
                    and abs(float(row["min_y"]) - fp["min_y"]) < 0.5
                    and abs(float(row["max_x"]) - fp["max_x"]) < 0.5
                    and abs(float(row["max_y"]) - fp["max_y"]) < 0.5):
                matches.append(row)
    return matches


def main(argv):
    parser = argparse.ArgumentParser(description="Fingerprint the loaded map's navmesh.")
    parser.add_argument("--py4gw-root", default=os.environ.get("PY4GW_STEALTH", DEFAULT_PY4GW_ROOT))
    parser.add_argument("--csv", default=DEFAULT_CSV, help="fingerprint sheet from gwdat_pathing")
    parser.add_argument("--json", default=None, help="also write the report as JSON here")
    parser.add_argument("--dump-trapezoids", default=None, metavar="PATH",
                        help="write every trapezoid as CSV (for containment matching)")
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--list", action="store_true",
                        help="list candidate clients (pid, name, path) and exit")
    parser.add_argument("--game-thread", action="store_true",
                        help="install the game-thread hooks (a write); off by default")
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

    if args.list:
        candidates = find_clients(win32, None)
        if not candidates:
            print("no Gw*.exe process found")
            return 0
        print("{:>8}  {:<16}  path".format("pid", "name"))
        for entry in candidates:
            print("{:>8}  {:<16}  {}".format(
                int(entry["pid"]), str(entry.get("name") or "?"), entry.get("path") or "?"))
        print("\nprobe one with:  --pid <pid>")
        return 0

    if not win32.is_elevated():
        print("this needs an elevated shell: py4gw.connect() is a write.", file=sys.stderr)
        print("start PowerShell as administrator (approve the UAC prompt) and run it again.",
              file=sys.stderr)
        return 2

    clients = find_clients(win32, args.pid)
    if not clients:
        print("no Guild Wars client is running (looked for Gw*.exe; pass --pid if it is "
              "named something else)", file=sys.stderr)
        return 3

    report = {"client": {"pid": int(clients[0]["pid"]), "name": clients[0].get("name"),
                         "path": clients[0].get("path")}}
    # Read-only by default. `game_thread=True` installs hooks, and on a 32-bit
    # controller that path dies in `list_modules` -- module handles in a 64-bit client
    # exceed 32 bits, and ctypes refuses the argument
    # ("OverflowError: int too long to convert"). This tool only reads, so it does not
    # need the hooks; --game-thread opts back in.
    try:
        client = py4gw.connect(clients[0], game_thread=args.game_thread)
    except OverflowError as exc:
        print("could not connect: {} -- this usually means a 32-bit Python is reading "
              "module handles from the 64-bit client. Run without --game-thread, or use a "
              "64-bit interpreter.".format(exc), file=sys.stderr)
        return 3
    try:
        map_id = int(Map.GetMapID() or 0)
        if not map_id:
            print("the client is not in a map (no map id yet)", file=sys.stderr)
            return 3
        report["map"] = {"id": map_id, "name": Map.GetMapName(map_id)}
        try:
            report["instance_uptime_s"] = int(Map.GetInstanceUptime())
        except Exception:
            pass

        try:
            position = Player.GetXY()
            report["position"] = {"x": round(float(position[0]), 3),
                                  "y": round(float(position[1]), 3)}
            try:
                from py4gw.agent import Agent
                agent_id = int(Player.GetAgentID())
                report["position"]["agent_id"] = agent_id
                # A GmMapConfig spawn point is (x, y, plane); the wrong plane puts the
                # character on another layer of the map.
                report["position"]["plane"] = int(Agent.GetZPlane(agent_id))
            except Exception as exc:
                report["position"]["plane_error"] = repr(exc)
        except Exception as exc:
            report["position_error"] = repr(exc)

        pathing_maps = Map.Pathing.GetPathingMaps()
        if not pathing_maps:
            print("the client reports no pathing records for this map", file=sys.stderr)
            return 4

        fp, rows = fingerprint(pathing_maps)
        report["fingerprint"] = fp

        if args.dump_trapezoids:
            out = Path(args.dump_trapezoids)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("plane,trap_id,xtl,xtr,yt,xbl,xbr,yb\n" + "\n".join(rows) + "\n",
                           encoding="utf-8")
            print("  trapezoids dumped -> {}".format(out))

        print("map {} ({})   instance uptime {}s".format(
            map_id, report["map"]["name"], report.get("instance_uptime_s", "?")))
        if "position" in report:
            where = report["position"]
            print("  player position  {}, {}   plane {}   <- a usable spawn point for this map"
                  .format(where["x"], where["y"], where.get("plane", "?")))
        print("  fingerprint      planes={} trapezoids={} bounds=({}, {}) .. ({}, {})".format(
            fp["planes"], fp["trapezoids"], fp["min_x"], fp["min_y"], fp["max_x"], fp["max_y"]))

        sheet = Path(args.csv)
        if not sheet.is_file():
            print("\nno fingerprint sheet at {}; run gwdat_pathing first".format(sheet),
                  file=sys.stderr)
            return 0

        matches = match_sheet(sheet, fp)
        report["matches"] = matches
        if not matches:
            # Planes and bounds still have to agree, so this is a narrow retry, not a
            # fudge: the importer and the client can differ by a trapezoid or two.
            tolerance = max(8, fp["trapezoids"] // 200)
            near = match_sheet(sheet, fp, tolerance=tolerance)
            if near:
                report["near_matches"] = near
                print("\nNo exact match; {} blob(s) agree on planes and bounds with a "
                      "trapezoid delta of at most {} -- treat as a NEAR match and confirm "
                      "by terrain:".format(len(near), tolerance))
                for row in near:
                    print("  file_id {}  traps={} (client {})  size={}".format(
                        row["file_id"], row["trapezoids"], fp["trapezoids"], row["size"]))
                print("\nGmMapConfig candidate for map {} (VERIFY by terrain):\n"
                      "    .map_file_id = {},".format(map_id, near[0]["file_id"]))
                return 0
            print("\nNO MATCH in the sheet, not even near. Either the map is not a RIFF map "
                  "blob, or the sheet was built with a size floor (never filter maps by "
                  "compressed size). Fall back to --find-floats in gwdat_pathing.",
                  file=sys.stderr)
            return 4

        print("\n{} matching blob(s), a map is stored twice so two is the expected answer:"
              .format(len(matches)))
        for row in matches:
            print("  file_id {}  size={}  planes={} trapezoids={}".format(
                row["file_id"], row["size"], row["planes"], row["trapezoids"]))
        print("\nGmMapConfig candidate for map {}:\n    .map_file_id = {},".format(
            map_id, matches[0]["file_id"]))
        return 0
    finally:
        py4gw.disconnect()
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print("\nreport -> {}".format(args.json))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
