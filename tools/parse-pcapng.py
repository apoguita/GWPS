"""Extract the TCP conversations from a pktmon pcapng capture and print their payloads.

No external libraries: pcapng is a simple block format and we only need the Enhanced Packet
Block, so this parses the blocks directly, then Ethernet -> IPv4 -> TCP by handoff.

Usage: python parse-pcapng.py <capture.pcapng>
"""

import struct
import sys


def blocks(data):
    off = 0
    while off + 12 <= len(data):
        block_type = struct.unpack_from('<I', data, off)[0]
        block_len = struct.unpack_from('<I', data, off + 4)[0]
        if block_len < 12 or off + block_len > len(data):
            break
        yield block_type, data[off:off + block_len]
        off += block_len


def parse(path):
    data = open(path, 'rb').read()
    linktype = 1  # assume Ethernet until an IDB says otherwise
    packets = []
    for block_type, block in blocks(data):
        if block_type == 0x00000001:  # Interface Description Block
            linktype = struct.unpack_from('<H', block, 8)[0]
        elif block_type == 0x00000006:  # Enhanced Packet Block
            captured = struct.unpack_from('<I', block, 20)[0]
            packets.append((linktype, block[28:28 + captured]))
    return packets


def parse_tcp(linktype, frame):
    """Return (src, dst, payload) or None."""
    off = 0
    if linktype == 1:  # Ethernet
        if len(frame) < 14:
            return None
        ethertype = struct.unpack_from('>H', frame, 12)[0]
        off = 14
        while ethertype in (0x8100, 0x88a8) and len(frame) > off + 4:  # VLAN tags
            ethertype = struct.unpack_from('>H', frame, off + 2)[0]
            off += 4
        if ethertype != 0x0800:
            return None
    elif linktype != 101:  # 101 = raw IP
        return None

    if len(frame) < off + 20:
        return None
    version_ihl = frame[off]
    if version_ihl >> 4 != 4:
        return None
    ihl = (version_ihl & 0x0F) * 4
    proto = frame[off + 9]
    if proto != 6:  # TCP only
        return None
    total_len = struct.unpack_from('>H', frame, off + 2)[0]
    src = '.'.join(str(b) for b in frame[off + 12:off + 16])
    dst = '.'.join(str(b) for b in frame[off + 16:off + 20])

    tcp_off = off + ihl
    if len(frame) < tcp_off + 20:
        return None
    sport, dport = struct.unpack_from('>HH', frame, tcp_off)
    data_off = (frame[tcp_off + 12] >> 4) * 4
    flags = frame[tcp_off + 13]
    payload = frame[tcp_off + data_off: off + total_len]
    return f'{src}:{sport}', f'{dst}:{dport}', flags, payload


def main():
    path = sys.argv[1]
    packets = parse(path)
    print(f'{len(packets)} packets')

    convos = {}
    for linktype, frame in packets:
        r = parse_tcp(linktype, frame)
        if not r:
            continue
        src, dst, flags, payload = r
        key = tuple(sorted([src, dst]))
        convos.setdefault(key, []).append((src, dst, flags, payload))

    for key, pkts in convos.items():
        total = sum(len(p[3]) for p in pkts)
        print(f'\n=== {key[0]}  <->  {key[1]}   ({len(pkts)} segments, {total} payload bytes) ===')
        shown = 0
        for src, dst, flags, payload in pkts:
            if not payload:
                if flags & 0x02:
                    print(f'  {src} -> {dst}  SYN')
                elif flags & 0x01:
                    print(f'  {src} -> {dst}  FIN')
                continue
            if shown >= 12:
                continue
            shown += 1
            hexs = payload[:64].hex(' ')
            asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in payload[:64])
            print(f'  {src} -> {dst}  {len(payload):4d}B  {hexs}')
            print(f'  {"":21s}  ascii  {asc}')


if __name__ == '__main__':
    main()
