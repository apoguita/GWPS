"""Find the cached server addresses the client dials without DNS.

The client keeps a socket to a real File1 IP even when hosts points the name at 127.0.0.1, so
the address must be cached somewhere: Gw.dat, the exe, or a config. This scans candidate files
for the exact IPs we observed on the wire, in both byte orders, and prints surrounding context.

Usage: python find-server-ips.py <file> [<file> ...]
"""

import sys

# IPs observed on the wire, with both byte orders: network order (as they appear in a packet)
# and host order (as a little-endian dword).
OBSERVED = [
    '54.86.64.251',     # File1, in the capture and the surviving socket
    '54.196.189.234',   # File1 A record
    '18.209.181.207',   # File1 A record
    '52.29.66.37',      # the surviving peer in an earlier run
    '63.176.23.57',
    '3.65.211.216',
]

def ip_bytes(ip):
    parts = [int(p) for p in ip.split('.')]
    net = bytes(parts)
    host = bytes(reversed(parts))
    return {'network': net, 'host': host}

def scan(path, chunk_size=64 * 1024 * 1024, context=48):
    hits = []
    with open(path, 'rb') as f:
        base = 0
        tail = b''
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            buf = tail + chunk
            start_of_buf = base - len(tail)
            for ip in OBSERVED:
                for order, needle in ip_bytes(ip).items():
                    pos = 0
                    while True:
                        idx = buf.find(needle, pos)
                        if idx < 0:
                            break
                        pos = idx + 1
                        off = start_of_buf + idx
                        lo = max(0, idx - context)
                        hi = min(len(buf), idx + len(needle) + context)
                        hits.append((off, ip, order, buf[lo:hi]))
            tail = buf[-8:]
            base += len(chunk)
    return hits

def main():
    for path in sys.argv[1:]:
        print(f'\n=== {path} ===')
        try:
            hits = scan(path)
        except OSError as e:
            print('  cannot read:', e)
            continue
        if not hits:
            print('  no observed IP found')
            continue
        for off, ip, order, ctx in hits[:20]:
            hexs = ctx.hex(' ')
            asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in ctx)
            print(f'  0x{off:08X}  {ip} ({order})')
            print(f'    {hexs}')
            print(f'    {asc}')
        if len(hits) > 20:
            print(f'  ... {len(hits) - 20} more')

if __name__ == '__main__':
    main()
