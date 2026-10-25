"""Find which Gw.dat blob is the map the client is standing in, by containment.

Why containment rather than equality
------------------------------------
`gwdat_pathing` parses a map blob with the server's own `GmImportMap`, and that
importer reads **fewer trapezoids than the client holds** (finding F11: Kamadan
parses to 1270 here, while the client's count for a comparable outpost is in the
thousands). So the correct blob's parsed geometry is a *subset* of the client's, and
the test has to be "how much of this blob does the client also have", not "do the two
sets match".

The score is therefore `|blob ∩ client| / |blob|`: **1.0 means every trapezoid our
importer read from that blob exists in the map the client has loaded.** A wrong blob
scores near zero — the coordinates are world-space, so they only agree when it is the
same map.

Plane indices and trap ids are deliberately **not** compared: only the geometry is,
because plane numbering is an artefact of the parse and the ids are per-file.

Usage
-----
    # 1. (elevated, client in the map)
    py tools/probe-pathing.py --dump-trapezoids build/client-traps.csv
    # 2. (offline)
    gwdat_pathing Gw.dat --trapezoids build/all-traps.csv
    # 3. (offline)
    py tools/match-pathing.py --client build/client-traps.csv --blobs build/all-traps.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path


def key(row: dict) -> tuple:
    """The geometry tuple, at the precision both dumps print (two decimals)."""
    return (row["xtl"], row["xtr"], row["yt"], row["xbl"], row["xbr"], row["yb"])


def load_client(path: Path) -> set[tuple]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {key(row) for row in csv.DictReader(handle)}


def load_blobs(path: Path) -> dict[str, set[tuple]]:
    blobs: dict[str, set[tuple]] = defaultdict(set)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            blobs[row["file_id"]].add(key(row))
    return blobs


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Match the loaded map against Gw.dat blobs.")
    parser.add_argument("--client", default="build/client-traps.csv")
    parser.add_argument("--blobs", default="build/all-traps.csv")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--min-score", type=float, default=0.0,
                        help="only report blobs at or above this containment fraction")
    args = parser.parse_args(argv)

    client_path, blob_path = Path(args.client), Path(args.blobs)
    for path in (client_path, blob_path):
        if not path.is_file():
            print(f"missing {path}", file=sys.stderr)
            return 2

    client = load_client(client_path)
    blobs = load_blobs(blob_path)
    print(f"client trapezoids: {len(client)}   blobs: {len(blobs)}")

    scored = []
    for file_id, traps in blobs.items():
        if not traps:
            continue
        shared = len(traps & client)
        scored.append((shared / len(traps), shared, len(traps), file_id))

    scored.sort(reverse=True)
    best = scored[0] if scored else None
    if best is None:
        print("no trapezoids in either dump", file=sys.stderr)
        return 3

    print(f"\ntop {args.top} by containment (score = fraction of the blob's parsed "
          f"trapezoids the client also has):")
    for score, shared, total, file_id in scored[:args.top]:
        if score < args.min_score:
            break
        flag = "  <== " if score >= 0.999 else ""
        print(f"  {file_id}  {score*100:6.2f}%  {shared}/{total}{flag}")

    exact = [s for s in scored if s[0] >= 0.999]
    if not exact:
        print("\nNo blob is fully contained in the client's set. Either the dump is of a "
              "different map than the blobs cover, or the importer reads trapezoids the "
              "client does not have (a misparse rather than a subset).", file=sys.stderr)
        return 4

    print(f"\n{len(exact)} fully-contained blob(s) — a map is stored twice, so two is the "
          f"expected answer:")
    for score, shared, total, file_id in exact:
        print(f"  {file_id}  ({shared} trapezoids)")
    print(f"\nGmMapConfig candidate: .map_file_id = {exact[0][3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
