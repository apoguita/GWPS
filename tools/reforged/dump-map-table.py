"""Dump the client's AreaInfo table -- run this INSIDE the injected client.

Companion to `tools/dump-map-table.py` (external, via Py4GW_Stealth). Use this
one when the outer shell is not elevated: Stealth needs an elevated token to
attach (PROCESS_VM_WRITE / PROCESS_VM_OPERATION), while code already running
inside the client needs nothing at all.

What it answers
---------------
`code/OpenTyria/GmMapsConfig.c` needs a `map_file_id` per map -- the key used to
fetch that map's blob from `Gw.dat` (`GameSrv.c:2030` -> `FaGetFile`). The
client holds the whole table in memory, indexed by map id:

    AreaInfo { ... uint32_t file_id; /* +0x68 */
               file_id1() = ((file_id-1) % 0xff00) + 0x100
               file_id2() = ((file_id-1) / 0xff00) + 0x100 }

and `MapMethods.GetMapInfo(map_id)` returns `AreaInfo[map_id]` for ANY map id,
loaded or not.

So this prints:
  1. a known-answer test: the six maps that already have a GmMapConfig, so we
     can tell whether OpenTyria's `map_file_id` is `file_id`, `file_id1` or
     `file_id2`. Kamadan is the anchor: `GmMapsConfig.c` says 0x345CC.
  2. the Pre-Searing milestone-1 target set, filled in.
  3. every map the client files under `region == Presearing`, which enumerates
     the Pre-Searing set without trusting a hand-written list.

How to run
----------
Any of these, from inside the injected client:

  * Py4GW console / script runner: paste or execute this file.
  * Drop it in `Py4GW_Reforged/Widgets/dump_map_table/` next to a `.widget`
    marker file to load it as a widget.
  * `exec(open(r"<path>\\tools\\reforged\\dump-map-table.py").read())`

Output goes to the Py4GW console when that is available, and to stdout always.
Copy the printed block into `docs/test-log.md`.
"""

from __future__ import annotations

# Region enum value for Pre-Searing (GW::Context::Region, context/map.h:56-85).
REGION_PRESEARING = 7

# Maps that already have a GmMapConfig (code/OpenTyria/GmMapsConfig.c).
# The number is what OpenTyria already uses as map_file_id -- our known answers.
KNOWN_CONFIGS = {
    449: ("Kamadan, Jewel of Istan (outpost)", 0x345CC),
    194: ("Kaineng Center (outpost)", 0x265F7),
    55:  ("Lion's Arch (outpost)", 352808),
    474: ("Domain of Anguish", 219215),
    558: ("Sparkfly Swamp", 287493),
    90:  ("Lornar's Pass", 46594),
}

# The Pre-Searing milestone-1 target set (docs/03-roadmap.md).
PRESEARING_TARGETS = {
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

_LINES: list[str] = []


def emit(line: str = "") -> None:
    """Record a line for both stdout and the in-client console."""
    _LINES.append(line)
    print(line)
    try:
        import PySystem
        PySystem.Console.Log(
            "GWPS/map-table", line, PySystem.Console.MessageType.Notice
        )
    except Exception:
        # Console binding is optional; stdout already has the line.
        pass


def hexs(value: int) -> str:
    return f"0x{value:X}"


def read_row(map_id: int):
    """Return a dict of the interesting AreaInfo fields for one map id."""
    from Py4GWCoreLib.native_src.methods.MapMethods import MapMethods

    try:
        info = MapMethods.GetMapInfo(map_id)
    except Exception as exc:
        emit(f"  !! GetMapInfo({map_id}) raised {type(exc).__name__}: {exc}")
        return None
    if info is None:
        return None

    file_id = int(info.file_id)
    if file_id == 0:
        return None
    return {
        "map_id": map_id,
        "file_id": file_id,
        "file_id1": int(info.file_id1),
        "file_id2": int(info.file_id2),
        "region": int(info.region),
        "type": int(info.type),
        "name_id": int(info.name_id),
    }


def try_map_name(map_id: int) -> str:
    try:
        from Py4GWCoreLib.Map import Map

        name = Map.GetMapName(map_id)
        return "" if not name or name == "Unknown Map ID" else name
    except Exception:
        return ""


def main() -> None:
    emit("=" * 78)
    emit("GWPS -- AreaInfo table dump (in-client)")
    emit("=" * 78)

    try:
        from Py4GWCoreLib.Map import Map

        current = int(Map.GetMapID())
        emit(f"client is currently on map id {current} ({try_map_name(current) or 'unnamed'})")
    except Exception as exc:
        emit(f"could not read current map id: {type(exc).__name__}: {exc}")
        current = 0
    emit()

    # ---- 1. known-answer test -------------------------------------------------
    emit("KNOWN-ANSWER TEST: which field matches OpenTyria's map_file_id?")
    emit(f"{'map':<36} {'id':>4} {'config':>9} {'file_id':>9} {'file_id1':>9} {'file_id2':>9}  match")
    matches = {"file_id": 0, "file_id1": 0, "file_id2": 0}
    for map_id, (label, expected) in sorted(KNOWN_CONFIGS.items()):
        row = read_row(map_id)
        if row is None:
            emit(f"{label:<36} {map_id:>4} {hexs(expected):>9} {'-':>9} {'-':>9} {'-':>9}  missing")
            continue
        hit = [key for key in ("file_id", "file_id1", "file_id2") if row[key] == expected]
        for key in hit:
            matches[key] += 1
        emit(
            f"{label:<36} {map_id:>4} {hexs(expected):>9} "
            f"{hexs(row['file_id']):>9} {hexs(row['file_id1']):>9} {hexs(row['file_id2']):>9}"
            f"  {','.join(hit) if hit else '-'}"
        )
    emit()
    best = max(matches, key=matches.get)
    if matches[best]:
        emit(f"=> '{best}' matches {matches[best]}/{len(KNOWN_CONFIGS)} known configs.")
        emit(f"   Use AreaInfo.{best} as GmMapConfig.map_file_id.")
    else:
        emit("=> NO FIELD MATCHED. The relationship is something else -- investigate")
        emit("   before writing any map configs.")
    emit()

    # ---- 2. Pre-Searing target set -------------------------------------------
    emit("PRE-SEARING TARGET SET (milestone 1)")
    emit(f"{'id':>4}  {'file_id':>9} {'file_id1':>9} {'file_id2':>9}  {'type':>4}  name")
    for map_id, label in sorted(PRESEARING_TARGETS.items()):
        row = read_row(map_id)
        if row is None:
            emit(f"{map_id:>4}  {'MISSING':>9} {'':>9} {'':>9}  {'':>4}  {label}")
            continue
        emit(
            f"{map_id:>4}  {hexs(row['file_id']):>9} {hexs(row['file_id1']):>9} "
            f"{hexs(row['file_id2']):>9}  {row['type']:>4}  {label}"
        )
    emit()

    # ---- 3. everything filed under region Presearing -------------------------
    rows = []
    for map_id in range(1, MAX_MAP_ID):
        row = read_row(map_id)
        if row is not None:
            rows.append(row)

    emit(f"ALL MAPS WITH region == Presearing (scanning 1..{MAX_MAP_ID})")
    presearing = [r for r in rows if r["region"] == REGION_PRESEARING]
    if not presearing:
        emit("  (none found -- region field may differ on this build)")
    for row in presearing:
        name = try_map_name(row["map_id"]) or f"(name_id {row['name_id']})"
        emit(
            f"{row['map_id']:>4}  {hexs(row['file_id']):>9} "
            f"{hexs(row['file_id1']):>9} {hexs(row['file_id2']):>9}  {name}"
        )
    emit()
    emit(f"total maps with a non-zero file_id: {len(rows)}")
    emit("Done. Copy this block into docs/test-log.md.")


if __name__ == "__main__":
    main()
