"""Capture Guild Wars packet traffic from Py4GW_Stealth into a JSONL file.

Why this exists
---------------
`docs/06-client-tooling.md` describes the packet sniffer as the test oracle: run a
scripted sequence, capture both directions, and diff the byte stream against a
golden capture instead of eyeballing a screenshot. The sniffer itself lives in
`Py4GW_Stealth` and is live-verified; what was missing was the small, repeatable
front end that says "capture for N seconds, from this client, into this file".

This is that front end. It is a *development* tool: GWPS does not ship it and does
not depend on Py4GW at runtime.

Elevation is required, and not by choice
----------------------------------------
`py4gw.connect()` asserts an elevated token and refuses without one, because
connecting is a write — shared block, dispatcher, handler entries. A process cannot
raise its own token, so:

    Start an elevated PowerShell (approve the UAC prompt), then run this script.

Running it unelevated prints the reason and exits 2. There is no read-only mode to
fall back on; `--self-test` is the only path that needs neither a client nor
elevation, and it exercises the sanitizer and the writer only.

The log is a ring, so this drains it
------------------------------------
The sniffer keeps a capped log (`K_MAX_LOGS = 10000` in
`py4gw/native_src/packets/py_packet_sniffer.py`) and drops the oldest entry first.
A long session would therefore silently truncate itself. This script reads the log,
**clears it**, and repeats — so the file is complete regardless of how long it runs,
and the client-side vector stays small.

Records are sanitised by default
--------------------------------
`docs/06-client-tooling.md` rules of engagement: captures contain UTF-16 player
names and UUIDs, so a capture must be sanitised before it is committed. This script
therefore, by default:

  * replaces the payload of the 15 headers the sniffer itself names as carrying
    UTF-16 names (`NAME_RE_STOC_HEADERS`) with a marker, keeping `size`;
  * masks every run of printable UTF-16LE code units (>= 6) anywhere else, zeroing
    the bytes and recording the ranges in `masked`, so offsets stay meaningful.

`--raw` turns both off, keeps every byte, and prints a warning. A raw capture must
not be committed.

Usage
-----
    # StoC only, 30 seconds, header filter
    py tools/sniff-capture.py --seconds 30 --dir StoC --header 0x3D,0x3E

    # both directions, until Ctrl+C, into a named file
    py tools/sniff-capture.py --seconds 0 --dir both --out captures/walk.jsonl

    # no client, no elevation: prove the sanitizer and the writer work
    py tools/sniff-capture.py --self-test

Exit codes: 0 captured (or self-test passed), 2 not elevated, 3 no client found,
4 capture failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

#: Where Py4GW_Stealth lives by default. Overridable with ``--py4gw-root`` or the
#: ``PY4GW_STEALTH`` environment variable, because the path is per machine.
DEFAULT_PY4GW_ROOT = r"C:\Users\Apo\Py4GW_Stealth"

#: The shortest run of printable UTF-16LE code units treated as text. Six characters
#: is above the false-positive rate of binary payloads read as pairs of printable
#: bytes (~1e-5 per six-unit run) and below every player name.
UTF16_RUN_MIN = 6

#: Code units that count as text. Tab is included because client strings can hold it.
PRINTABLE_RANGES = ((0x20, 0x7E), (0x09, 0x09))


# --------------------------------------------------------------------------- #
# sanitising
# --------------------------------------------------------------------------- #

def _is_printable(unit: int) -> bool:
    return any(low <= unit <= high for low, high in PRINTABLE_RANGES)


def mask_utf16_runs(data: bytes) -> tuple[bytes, list[list[int]]]:
    """Zero every printable UTF-16LE run of at least ``UTF16_RUN_MIN`` characters.

    Returns the masked bytes and the ``[offset, byte_length]`` ranges that were
    zeroed. Offsets are byte offsets into the packet as captured, so a masked
    capture still lines up with an unmasked one field for field.
    """
    masked = bytearray(data)
    ranges: list[list[int]] = []

    start = -1          # byte offset where the current run began
    units = 0           # code units in the current run

    for offset in range(0, len(data) - 1, 2):
        unit = data[offset] | (data[offset + 1] << 8)
        if _is_printable(unit):
            if start < 0:
                start = offset
            units += 1
            continue

        if start >= 0 and units >= UTF16_RUN_MIN:
            length = units * 2
            ranges.append([start, length])
            masked[start:start + length] = b"\x00" * length
        start = -1
        units = 0

    # A run that reaches the end of the packet.
    if start >= 0 and units >= UTF16_RUN_MIN:
        length = min(units * 2, len(data) - start)
        ranges.append([start, length])
        masked[start:start + length] = b"\x00" * length

    return bytes(masked), ranges


def sanitise(direction: str, header: int, data: bytes, name_headers: frozenset[int]) -> dict:
    """Produce the ``data`` half of a record: hex, plus what was removed from it."""
    if direction == "StoC" and header in name_headers:
        # These headers are known to carry UTF-16 names; drop the payload wholesale
        # rather than trusting the run scan to find all of it.
        return {"data": None, "redacted": "utf16-name-header", "masked": []}

    masked, ranges = mask_utf16_runs(data)
    return {"data": masked.hex(), "redacted": None, "masked": ranges}


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #

def open_capture(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8", newline="\n")


def write_record(handle, record: dict) -> None:
    handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def exe_identity(exe_path: str | None) -> dict:
    """Identify the client executable, because that is what a capture must state.

    Offsets and packet layouts are build-specific (`06-client-tooling.md`), so a
    capture with no client identity is not evidence of anything. The version
    resource cannot be trusted for this: on the reference install
    (`F:\\GW\\GW1\\Gw.exe`) it reads `1.0.0.1`, while the build the tooling documents
    itself against is `39112`. So the **hash** is what identifies the build, and the
    version string is recorded beside it for the human reader.
    """
    identity = {"path": exe_path, "file_version": None, "sha256": None, "size": None}
    if not exe_path:
        return identity

    try:
        import hashlib

        digest = hashlib.sha256()
        with open(exe_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        identity["sha256"] = digest.hexdigest()
        identity["size"] = os.path.getsize(exe_path)
    except Exception:  # noqa: BLE001 - an unreadable exe must not fail a capture
        pass

    try:
        import ctypes
        from ctypes import wintypes

        version = ctypes.WinDLL("version")
        size = version.GetFileVersionInfoSizeW(exe_path, None)
        if size:
            buffer = ctypes.create_string_buffer(size)
            if version.GetFileVersionInfoW(exe_path, 0, size, buffer):
                value = ctypes.c_void_p()
                length = wintypes.UINT()
                if version.VerQueryValueW(
                    buffer, "\\", ctypes.byref(value), ctypes.byref(length)
                ):
                    class FixedFileInfo(ctypes.Structure):
                        _fields_ = [
                            ("signature", wintypes.DWORD),
                            ("struc_version", wintypes.DWORD),
                            ("file_version_ms", wintypes.DWORD),
                            ("file_version_ls", wintypes.DWORD),
                            ("product_version_ms", wintypes.DWORD),
                            ("product_version_ls", wintypes.DWORD),
                            ("flags_mask", wintypes.DWORD),
                            ("flags", wintypes.DWORD),
                            ("os", wintypes.DWORD),
                            ("type", wintypes.DWORD),
                            ("subtype", wintypes.DWORD),
                            ("date_ms", wintypes.DWORD),
                            ("date_ls", wintypes.DWORD),
                        ]

                    info = ctypes.cast(value, ctypes.POINTER(FixedFileInfo)).contents
                    ms, ls = info.file_version_ms, info.file_version_ls
                    identity["file_version"] = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:  # noqa: BLE001 - a missing version string is not worth failing
        pass

    return identity


# --------------------------------------------------------------------------- #
# both halves of the capture loop
# --------------------------------------------------------------------------- #

def parse_headers(text: str | None) -> set[int] | None:
    if not text:
        return None
    headers = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        headers.add(int(token, 0))
    return headers


def run_capture(args) -> int:
    root = Path(args.py4gw_root)
    if not (root / "py4gw").is_dir():
        print(f"py4gw not found under {root}", file=sys.stderr)
        print("pass --py4gw-root, or set PY4GW_STEALTH", file=sys.stderr)
        return 3
    sys.path.insert(0, str(root))

    import py4gw                                    # noqa: E402
    from py4gw.packet_sniffer import NAME_RE_STOC_HEADERS, SNIFFER   # noqa: E402
    from py4gw.win32 import Win32                   # noqa: E402

    win32 = Win32()
    if not win32.is_elevated():
        print("this needs an elevated shell: py4gw.connect() is a write.", file=sys.stderr)
        print("start PowerShell as administrator (approve the UAC prompt) and run it again.",
              file=sys.stderr)
        return 2

    clients = win32.find_guild_wars()
    if args.pid:
        clients = [c for c in clients if int(c["pid"]) == args.pid]
    if not clients:
        print("no Gw.exe is running" if not args.pid else f"no Gw.exe with pid {args.pid}",
              file=sys.stderr)
        return 3
    target = clients[0]

    names = frozenset(NAME_RE_STOC_HEADERS) if not args.raw else frozenset()
    headers = parse_headers(args.header)

    out = Path(args.out) if args.out else Path("captures") / (
        f"packets-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    )

    client = py4gw.connect(target)
    identity = exe_identity(target.get("path"))
    started = time.time()
    counts: dict[str, int] = {}
    seq = 0
    captured = 0

    try:
        with open_capture(out) as handle:
            write_record(handle, {
                "record": "capture",
                "tool": "gwps/tools/sniff-capture.py",
                "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
                "client": {
                    "pid": int(target["pid"]),
                    "name": target.get("name"),
                    **identity,
                },
                "directions": args.dir,
                "header_filter": sorted(headers) if headers else None,
                "seconds": args.seconds,
                "sanitised": not args.raw,
                "notes": (
                    "sanitised: name-headers dropped, UTF-16 runs masked (offsets preserved)"
                    if not args.raw else
                    "RAW: contains names/UUIDs -- do not commit"
                ),
            })

            SNIFFER.initialize(args.dir)
            print(f"--- capturing {args.dir} from pid {target['pid']} "
                  f"(client sha256 {(identity['sha256'] or '?')[:16]}, "
                  f"version {identity['file_version']}) -> {out}")

            deadline = started + args.seconds if args.seconds else None
            try:
                while True:
                    entries = SNIFFER.get_logs(args.dir)
                    if entries:
                        for entry in entries:
                            header = int(entry.header)
                            if headers is not None and header not in headers:
                                continue
                            seq += 1
                            captured += 1
                            name = SNIFFER.get_packet_name(entry.direction, header)
                            counts[f"{entry.direction} {header:#06x} {name}"] = (
                                counts.get(f"{entry.direction} {header:#06x} {name}", 0) + 1
                            )
                            payload = sanitise(entry.direction, header, bytes(entry.data), names)
                            write_record(handle, {
                                "seq": seq,
                                "t": round(time.time() - started, 3),
                                "direction": entry.direction,
                                "header": header,
                                "name": name,
                                "size": int(entry.size),
                                **payload,
                            })
                        handle.flush()
                        # Drain: the client-side log is a ring with a fixed cap.
                        SNIFFER.clear_logs(args.dir)

                    if deadline is not None and time.time() >= deadline:
                        break
                    time.sleep(args.poll)
            except KeyboardInterrupt:
                print("\n--- interrupted")
    except Exception as exc:  # noqa: BLE001 - always disconnect before leaving
        print(f"capture failed: {exc}", file=sys.stderr)
        try:
            SNIFFER.terminate(args.dir)
            py4gw.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return 4
    finally:
        try:
            SNIFFER.terminate(args.dir)     # puts every handler entry back
        finally:
            py4gw.disconnect()

    print(f"--- {captured} packet(s) in {time.time() - started:.1f}s -> {out}")
    if counts:
        print("--- by header:")
        for key in sorted(counts, key=lambda k: counts[k], reverse=True):
            print(f"      {counts[key]:5d}  {key}")
    if args.raw:
        print("--- WARNING: raw capture. It contains player names and UUIDs. Do not commit it.")
    return 0


# --------------------------------------------------------------------------- #
# self-test: no client, no elevation
# --------------------------------------------------------------------------- #

def run_self_test() -> int:
    """Exercise the sanitizer and the writer against synthetic packets."""
    failures = 0

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal failures
        if condition:
            print(f"  ok   {label}")
        else:
            failures += 1
            print(f"  FAIL {label}{(' -- ' + detail) if detail else ''}")

    name = "Test Player One"
    utf16 = name.encode("utf-16le")
    payload = b"\x11\x22\x33\x44" + utf16 + b"\x55\x66\x77\x88"

    masked, ranges = mask_utf16_runs(payload)
    check("a UTF-16 name is found and masked", ranges == [[4, len(utf16)]], f"ranges={ranges}")
    check("masking preserves length", len(masked) == len(payload))
    check("the name is gone from the masked bytes", name.encode("utf-16le") not in masked)
    check("the surrounding words survive", masked[:4] == b"\x11\x22\x33\x44")

    short = "ab".encode("utf-16le")
    _, short_ranges = mask_utf16_runs(b"\x01\x02" + short + b"\x03\x04")
    check("a run shorter than the floor is left alone", short_ranges == [])

    odd, _ = mask_utf16_runs(b"\x00")
    check("a one-byte payload does not crash", odd == b"\x00")

    record = sanitise("StoC", 0x0084, payload, frozenset({0x0084}))
    check("a name header is dropped wholesale",
          record["data"] is None and record["redacted"] == "utf16-name-header")

    plain = sanitise("CToS", 0x003D, b"\x3d\x00\x00\x00" + b"\x00" * 24, frozenset({0x0084}))
    check("a non-name header keeps its bytes", plain["data"] is not None and plain["redacted"] is None)

    target = Path(os.environ.get("TEMP", ".")) / "gwps-sniff-selftest.jsonl"
    with open_capture(target) as handle:
        write_record(handle, {"record": "capture", "tool": "self-test"})
        write_record(handle, {"seq": 1, "header": 0x3D, "size": 28, **plain})
    lines = target.read_text(encoding="utf-8").splitlines()
    check("the writer emits one JSON object per line", len(lines) == 2)
    check("the first line is the capture header", json.loads(lines[0])["record"] == "capture")
    check("the record round-trips through JSON",
          json.loads(lines[1])["header"] == 0x3D and json.loads(lines[1])["size"] == 28)
    target.unlink(missing_ok=True)

    print(f"\n--- self-test: {'PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 0 if failures == 0 else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Capture Guild Wars packets from Py4GW_Stealth (needs an elevated shell).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage\n-----")[1] if "Usage\n-----" in __doc__ else None,
    )
    parser.add_argument("--dir", choices=("StoC", "CToS", "both"), default="StoC",
                        help="which half of the sniffer to start (default: StoC)")
    parser.add_argument("--seconds", type=float, default=30.0,
                        help="capture window; 0 waits for Ctrl+C (default: 30)")
    parser.add_argument("--header", type=str, default=None,
                        help="comma-separated header allow-list, e.g. 0x3D,0x3E")
    parser.add_argument("--out", type=str, default=None,
                        help="JSONL path (default: captures/packets-<timestamp>.jsonl)")
    parser.add_argument("--pid", type=int, default=None, help="target a specific Gw.exe pid")
    parser.add_argument("--poll", type=float, default=0.05, help="drain interval in seconds")
    parser.add_argument("--raw", action="store_true",
                        help="do not sanitise -- keeps names and UUIDs; do not commit the result")
    parser.add_argument("--py4gw-root", type=str,
                        default=os.environ.get("PY4GW_STEALTH", DEFAULT_PY4GW_ROOT),
                        help="where Py4GW_Stealth lives (default: %(default)s)")
    parser.add_argument("--self-test", action="store_true",
                        help="exercise the sanitizer and writer offline; no client, no elevation")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()
    return run_capture(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
