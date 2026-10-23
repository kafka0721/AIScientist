"""Summarize scoped pktmon TCP headers; no TLS payload extraction."""
import collections
import json
import socket
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = (ROOT / 'artifacts/gateway-upload.pcapng').read_bytes()
interfaces, packets = [], []
offset = 0
while offset + 12 <= len(data):
    kind, size = struct.unpack_from('<II', data, offset)
    if size < 12:
        break
    body = data[offset + 8:offset + size - 4]
    if kind == 1:
        linktype = struct.unpack_from('<H', body)[0]
        resolution = 1e-6
        option = 8
        while option + 4 <= len(body):
            code, length = struct.unpack_from('<HH', body, option)
            value = body[option + 4:option + 4 + length]
            if code == 9 and value:
                resolution = (2 if value[0] & 128 else 10) ** -(value[0] & 127)
            option += 4 + (length + 3) // 4 * 4
        interfaces.append((linktype, resolution))
    elif kind == 6:
        interface, high, low, caplen, packetlen = struct.unpack_from('<IIIII', body)
        frame = body[20:20 + caplen]
        linktype, resolution = interfaces[interface]
        ipoff = 14 if linktype == 1 else 0
        if len(frame) > ipoff + 40 and frame[ipoff] >> 4 == 4 and frame[ipoff + 9] == 6:
            ihl = (frame[ipoff] & 15) * 4
            tcp = ipoff + ihl
            if len(frame) >= tcp + 20:
                sport, dport, seq, ack = struct.unpack_from('!HHII', frame, tcp)
                tcp_len = (frame[tcp + 12] >> 4) * 4
                ip_len = struct.unpack_from('!H', frame, ipoff + 2)[0]
                packets.append(dict(time=((high << 32) + low) * resolution,
                    interface=interface, source=socket.inet_ntoa(frame[ipoff + 12:ipoff + 16]),
                    destination=socket.inet_ntoa(frame[ipoff + 16:ipoff + 20]),
                    sport=sport, dport=dport, seq=seq, ack=ack, flags=frame[tcp + 13],
                    window=struct.unpack_from('!H', frame, tcp + 14)[0], ttl=frame[ipoff + 8],
                    payload=max(0, ip_len - ihl - tcp_len), frame_bytes=packetlen))
    offset += size

streams = collections.defaultdict(list)
for packet in packets:
    port = packet['dport'] if packet['sport'] == 443 else packet['sport']
    streams[port].append(packet)
report = []
for port, rows in streams.items():
    rows.sort(key=lambda row: row['time'])
    start = rows[0]['time']
    base_seq = {}
    for row in rows:
        direction = 'in' if row['sport'] == 443 else 'out'
        base_seq.setdefault(direction, row['seq'])
    compact = []
    for row in rows:
        direction = 'in' if row['sport'] == 443 else 'out'
        compact.append(dict(t=round(row['time'] - start, 4), direction=direction,
                            seq=(row['seq'] - base_seq[direction]) % 2**32,
                            ack=(row['ack'] - base_seq.get('out' if direction == 'in' else 'in', 0)) % 2**32,
                            flags=row['flags'], payload=row['payload'], window=row['window'], ttl=row['ttl'],
                            interface=row['interface']))
    sent = [row for row in compact if row['direction'] == 'out' and row['payload']]
    incoming = [row for row in compact if row['direction'] == 'in']
    sequences = collections.Counter((row['seq'], row['payload']) for row in sent)
    summary = dict(port=port, packets=len(rows), seconds=round(rows[-1]['time'] - start, 3),
                   max_sent_end=max((r['seq'] + r['payload'] for r in sent), default=0),
                   max_inbound_ack=max((r['ack'] for r in incoming if r['ack'] < 2**31), default=0),
                   repeated_sent_segments=[{'seq': key[0], 'bytes': key[1], 'count': value} for key, value in sequences.items() if value > 1],
                   resets=[row for row in compact if row['flags'] & 4],
                   first=compact[:7], last=compact[-10:])
    report.append(summary)
(ROOT / 'artifacts/gateway-upload-tcp-summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
