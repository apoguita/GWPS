"""Build the packet catalogue: every header, from every source we have.

Why
---
`docs/07-packet-scope.md` defines how a header is categorised. This tool produces
the table that categorisation applies to, by joining four sources that each know a
different part of the truth:

| Source | What only it knows |
|--------|--------------------|
| `code/OpenTyria/msgdefs.c` | which headers our server can **parse** (format tables) and the struct size |
| `code/OpenTyria/opcodes.h` | the names our server uses |
| `code/OpenTyria/{Game,Auth}Srv.c` | which of those we actually **handle** today |
| `Py4GW_Stealth` + `Py4GW_Reforged_Native` | the **client's** names for the same headers |
| a capture from `tools/sniff-capture.py` | which headers the client really **sends**, and how big |

The point is the disagreements. A header the client sends at 28 bytes whose format
in our table is 26 is a parse bug waiting to happen (that is exactly how `0x3D` was
settled); a header the client names `AGENT_SPAWNED` that we call `WORLD_CREATE_AGENT`
is a translation hazard for whoever reads the two side by side.

Usage
-----
    py tools/packet-catalog.py                      # uses any capture in captures/
    py tools/packet-catalog.py --capture captures/live-20261024-212230.jsonl
    py tools/packet-catalog.py --no-capture          # static view only

Writes `data/packet-catalog.csv`. Nothing here needs a client or elevation.
"""

from __future__ import annotations

import argparse
import csv
import glob
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

#: Field sizes in the *struct* (not on the wire): ``TYPE_MSG_HEADER`` is 2 bytes in
#: the struct and 4 on the wire, which is why ``wire_expected = struct_size + 2``.
FIELD_SIZES = {
    "MSG_HEADER": 2,
    "BYTE": 1,
    "WORD": 2,
    "DWORD": 4,
    "FLOAT": 4,
    "AGENT_ID": 4,
    "VECT2": 8,
    "VECT3": 12,
}

#: Types whose length is not knowable from the table alone: a capacity, not a size.
VARIABLE_TYPES = {"BLOB", "STRING_16", "ARRAY_8", "ARRAY_16", "ARRAY_32", "NESTED_STRUCT"}

DIRECTIONS = ("AUTH_CMSG", "AUTH_SMSG", "GAME_CMSG", "GAME_SMSG")


# --------------------------------------------------------------------------- #
# our side
# --------------------------------------------------------------------------- #

def parse_fields(text: str) -> list[tuple[str, int]]:
    """Every ``{TYPE_X, n}`` in a ``MsgField`` array body."""
    return [(m.group(1), int(m.group(2)))
            for m in re.finditer(r"\{TYPE_(\w+),\s*(\d+)\}", text)]


def parse_arrays(msgdefs_c: str) -> dict[str, dict]:
    """``MsgField GAME_CMSG_0061[5] = { ... }`` -> {name: {types, size, variable}}."""
    arrays = {}
    for match in re.finditer(
        r"MsgField (\w+)\[(\d+)\]\s*=\s*\{(.*?)\n\}", msgdefs_c, re.DOTALL
    ):
        name, _declared, body = match.group(1), match.group(2), match.group(3)
        fields = parse_fields(body)
        size = 0
        variable = False
        for kind, param in fields:
            if kind in VARIABLE_TYPES:
                variable = True
                if kind == "STRING_16":
                    size += 2 + 2 * param
                elif kind.startswith("ARRAY_"):
                    unit = int(kind.split("_")[1]) // 8
                    size += unit * param
                elif kind == "BLOB":
                    size += param
            else:
                size += FIELD_SIZES.get(kind, 0)
        arrays[name] = {"fields": fields, "size": size, "variable": variable}
    return arrays


def parse_format_tables(msgdefs_c: str) -> dict[str, dict[int, dict]]:
    """The four ``*_FORMATS`` tables: direction -> header -> {array, size}."""
    tables: dict[str, dict[int, dict]] = {}
    for match in re.finditer(
        r"MsgFormat (\w+)\[(\d+)\]\s*=\s*\{(.*?)\n\}", msgdefs_c, re.DOTALL
    ):
        name, body = match.group(1), match.group(3)
        direction = name.replace("_FORMATS", "")
        if direction not in DIRECTIONS:
            continue
        entries = {}
        for entry in re.finditer(r"\{(\d+),\s*(\d+),\s*(\w+),\s*(\d+)\}", body):
            header, _n, array, size = entry.groups()
            entries[int(header)] = {"array": array, "size": int(size)}
        tables[direction] = entries
    return tables


def parse_our_names(opcodes_h: str) -> dict[str, list[tuple[int, str]]]:
    """``#define GAME_CMSG_POSITION_UPDATE (GAME_CMSG_MASK | 0x003D)`` -> header -> names."""
    by_header: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for line in opcodes_h.splitlines():
        match = re.match(
            r"\s*#define\s+((?:GAME|AUTH)_(?:CMSG|SMSG)_\w+)\s+\((?:\w+)\s*\|\s*0x([0-9A-Fa-f]+)\)",
            line,
        )
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        direction = "_".join(name.split("_")[:2])
        by_header[direction].append((int(value, 16), name))
    return by_header


def parse_dispatch(srv_sources: dict[str, str]) -> tuple[set[str], set[str]]:
    """Which ``*_CMSG_*`` names have a ``case``, and which ``*_SMSG_*`` are built."""
    handled, produced = set(), set()
    for text in srv_sources.values():
        handled.update(re.findall(r"case\s+((?:GAME|AUTH)_CMSG_\w+)\s*:", text))
        produced.update(re.findall(r"((?:GAME|AUTH)_SMSG_\w+)", text))
    return handled, produced


# --------------------------------------------------------------------------- #
# the client's side
# --------------------------------------------------------------------------- #

def client_names_sniffer(root: Path) -> tuple[dict[int, str], dict[int, str]]:
    """The sniffer's own tables from ``Py4GW_Stealth`` (no elevation, no client)."""
    if not (root / "py4gw" / "packet_sniffer.py").is_file():
        return {}, {}
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        # Import as a package member: the module uses relative imports, so loading
        # the file standalone fails.
        from py4gw import packet_sniffer as module
        return dict(module.STOC_HEADER_NAMES), dict(module.CTO_OPCODES)
    except Exception as exc:  # noqa: BLE001 - names are optional enrichment
        print(f"note: could not read the sniffer tables ({exc})", file=sys.stderr)
        return {}, {}


def client_names_reforged(include_root: Path) -> dict[int, str]:
    """``include/GW/common/opcodes.h``: the StoC names Reforged's packet structs use."""
    path = include_root / "common" / "opcodes.h"
    if not path.is_file():
        return {}
    names = {}
    for match in re.finditer(
        r"#define\s+GAME_SMSG_(\w+)\s+\(0x([0-9A-Fa-f]+)\)", path.read_text(encoding="utf-8")
    ):
        names[int(match.group(2), 16)] = match.group(1)
    return names


#: The sniffer names its halves by traffic direction; our tables name theirs by
#: protocol. The sniffer hooks the *game* send wrapper and the *game* handler
#: array, so there is no auth traffic in a capture to disambiguate.
CAPTURE_TO_TABLE = {"CToS": "GAME_CMSG", "StoC": "GAME_SMSG"}


def load_capture(paths: list[Path]) -> tuple[dict[tuple[str, int], int], dict[tuple[str, int], set]]:
    counts: dict[tuple[str, int], int] = defaultdict(int)
    sizes: dict[tuple[str, int], set] = defaultdict(set)
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("record") == "capture":
                continue
            direction = CAPTURE_TO_TABLE.get(record.get("direction"))
            if direction is None:
                continue
            key = (direction, int(record["header"]))
            counts[key] += 1
            sizes[key].add(int(record["size"]))
    return counts, sizes


# --------------------------------------------------------------------------- #
# joining
# --------------------------------------------------------------------------- #

def status_of(parsed: bool, handled: bool, observed: bool, direction: str) -> str:
    """The mechanical categorisation defined in ``docs/07-packet-scope.md``."""
    if direction.endswith("CMSG"):
        # The client can send these at any time; an unparseable one kills the connection.
        if not parsed:
            return "unparsed-inbound"
        if handled:
            return "handled-observed" if observed else "handled-unobserved"
        return "parsed-unhandled-observed" if observed else "parsed-unhandled"
    if not parsed:
        return "unparseable-outbound"
    return "produced" if handled else "never-produced"


def build_rows(args) -> list[dict]:
    repo = Path(args.repo)
    code = repo / "code" / "OpenTyria"
    msgdefs_c = (code / "msgdefs.c").read_text(encoding="utf-8", errors="replace")
    opcodes_h = (code / "opcodes.h").read_text(encoding="utf-8", errors="replace")
    srv_sources = {
        name: (code / name).read_text(encoding="utf-8", errors="replace")
        for name in ("GameSrv.c", "AuthSrv.c")
    }

    arrays = parse_arrays(msgdefs_c)
    tables = parse_format_tables(msgdefs_c)
    ours = parse_our_names(opcodes_h)
    handled, produced = parse_dispatch(srv_sources)

    stoc_sniffer, ctos_sniffer = client_names_sniffer(Path(args.py4gw_root))
    reforged = client_names_reforged(Path(args.reforged_root) / "include" / "GW")

    captures = []
    if not args.no_capture:
        captures = [Path(p) for p in args.capture] if args.capture else \
            [Path(p) for p in glob.glob(str(repo / "captures" / "*.jsonl"))]
    counts, sizes = load_capture(captures)

    rows = []
    for direction in DIRECTIONS:
        entries = tables.get(direction, {})
        our_names = defaultdict(list)
        for header, name in ours.get(direction, []):
            our_names[header].append(name)

        headers = set(entries)
        headers.update(h for h, _ in ours.get(direction, []))
        if direction == "GAME_SMSG":
            headers.update(stoc_sniffer)
            headers.update(reforged)
        if direction == "GAME_CMSG":
            headers.update(ctos_sniffer)
        if direction == "AUTH_CMSG":
            headers.update(h for (d, h) in counts if d == direction)

        for header in sorted(headers):
            entry = entries.get(header)
            array = arrays.get(entry["array"]) if entry else None
            struct_size = entry["size"] if entry else (array["size"] if array else None)
            fixed = bool(array) and not array["variable"]
            observed = counts.get((direction, header), 0)
            observed_sizes = sorted(sizes.get((direction, header), set()))

            name_ours = ", ".join(our_names.get(header, [])) or None
            name_sniffer = (stoc_sniffer if direction == "GAME_SMSG" else ctos_sniffer).get(header)
            name_reforged = reforged.get(header) if direction == "GAME_SMSG" else None

            handled_here = bool(name_ours) and any(
                n in handled or n in produced for n in our_names.get(header, [])
            )
            status = status_of(entry is not None, handled_here, observed > 0, direction)

            wire_expected = struct_size + 2 if struct_size is not None else None
            size_check = ""
            size_delta = ""
            if fixed and observed_sizes and struct_size is not None:
                if len(observed_sizes) == 1:
                    size_delta = observed_sizes[0] - struct_size
                    # The wire header is 4 bytes (u32, upper half always zero) while
                    # the format table counts 2, so a complete fixed-size entry lands
                    # on +2. Anything else means the two sources disagree.
                    size_check = "expected" if size_delta == 2 else "investigate"

            notes = []
            if name_sniffer and name_reforged and name_sniffer != name_reforged:
                notes.append("client tables disagree")
            if size_check == "investigate":
                notes.append(f"format says {struct_size}, wire carries {observed_sizes}")
            if fixed is False:
                notes.append("variable-length: size is a capacity")

            rows.append({
                "direction": direction,
                "header_hex": f"0x{header:04X}",
                "header_dec": header,
                "status": status,
                "name_ours": name_ours or "",
                "name_client_reforged": name_reforged or "",
                "name_client_sniffer": name_sniffer or "",
                "struct_size": "" if struct_size is None else struct_size,
                "wire_expected": "" if wire_expected is None else wire_expected,
                "fixed_size": "" if not array else ("yes" if fixed else "no"),
                "observed_count": observed,
                "observed_sizes": "/".join(str(s) for s in observed_sizes),
                "size_delta": size_delta,
                "size_check": size_check,
                "notes": "; ".join(notes),
            })
    return rows


FIELDS = [
    "direction", "header_hex", "header_dec", "status",
    "name_ours", "name_client_reforged", "name_client_sniffer",
    "struct_size", "wire_expected", "fixed_size",
    "observed_count", "observed_sizes", "size_delta", "size_check", "notes",
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build data/packet-catalog.csv.")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--py4gw-root", default=r"C:\Users\Apo\Py4GW_Stealth",
                        help="Py4GW_Stealth checkout, for the client's sniffer name tables")
    parser.add_argument("--reforged-root", default=r"C:\Users\Apo\Py4GW_Reforged_Native",
                        help="Py4GW_Reforged_Native checkout, for the StoC opcode names")
    parser.add_argument("--capture", action="append", default=None,
                        help="capture JSONL to fold in (default: every captures/*.jsonl)")
    parser.add_argument("--no-capture", action="store_true", help="static view only")
    parser.add_argument("--out", default=None, help="CSV path (default: data/packet-catalog.csv)")
    args = parser.parse_args(argv)

    rows = build_rows(args)
    out = Path(args.out) if args.out else Path(args.repo) / "data" / "packet-catalog.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    counts = defaultdict(int)
    for row in rows:
        counts[row["status"]] += 1
    print(f"--- {len(rows)} headers -> {out}")
    for status in sorted(counts):
        print(f"    {counts[status]:5d}  {status}")
    mismatches = [r for r in rows if r["size_check"] == "investigate"]
    if mismatches:
        print(f"--- {len(mismatches)} size mismatch(es):", file=sys.stderr)
        for row in mismatches:
            print(f"    {row['direction']} {row['header_hex']} {row['name_ours']} "
                  f"{row['notes']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
