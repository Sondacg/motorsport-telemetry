#!/usr/bin/env python3
"""Observe Assetto Corsa's UDP telemetry before writing a parser for it.

Third-party headers for this protocol disagree with each other, and a struct
offset that is wrong by four bytes produces numbers that look almost right.
So: capture real packets from a real session, then work out the layout from
what actually arrives.

The protocol is a handshake. You send three int32s to AC's telemetry port,
it answers with car/driver/track names, you send a subscribe, and it streams
car state every physics frame.

    1. Start Assetto Corsa and get on track (any car, any circuit).
    2. python tools/ac_probe.py
    3. Drive. Accelerate to a decent speed and hold it while it samples.

It reports which byte offsets hold values that behave like speed, rpm, gear
and pedal positions, and dumps raw samples so the guess can be checked by eye.
"""

import argparse
import socket
import struct
import sys

AC_PORT = 9996

OP_HANDSHAKE = 0
OP_SUBSCRIBE_UPDATE = 1
OP_SUBSCRIBE_SPOT = 2
OP_DISMISS = 3


def handshake_packet(operation):
    # identifier, version, operationId — three little-endian int32s.
    return struct.pack("<iii", 1, 1, operation)


def decode_wide(raw):
    """AC pads its name fields with UTF-16 code units; cut at the first NUL."""
    try:
        text = raw.decode("utf-16-le", errors="replace")
    except Exception:
        return "<undecodable>"
    return text.split("\x00", 1)[0].strip()


def read_handshake_response(data):
    print(f"  handshake response: {len(data)} bytes")
    # Names are UTF-16 and fixed width; report the first few blocks so the
    # real field widths are visible instead of assumed.
    for name, start, width in (("field 1", 0, 100), ("field 2", 100, 100),
                               ("field 3", 208, 100), ("field 4", 308, 100)):
        chunk = data[start:start + width]
        if chunk:
            text = decode_wide(chunk)
            if text:
                print(f"    {name} @{start:>3}: {text!r}")
    if len(data) >= 208:
        ident, version = struct.unpack_from("<ii", data, 200)
        print(f"    ints @200: identifier={ident} version={version}")


def plausible(name, lo, hi, values):
    """A field is a candidate if every sample is in range and it actually moves."""
    if any(v != v or v in (float("inf"), float("-inf")) for v in values):
        return False
    if not all(lo <= v <= hi for v in values):
        return False
    return max(values) - min(values) > 1e-6


def analyse(samples):
    size = len(samples[0])
    print(f"\n  {len(samples)} samples of {size} bytes\n")

    floats = {}
    ints = {}
    for off in range(0, size - 3):
        try:
            floats[off] = [struct.unpack_from("<f", s, off)[0] for s in samples]
            ints[off] = [struct.unpack_from("<i", s, off)[0] for s in samples]
        except struct.error:
            break

    def report(title, table, lo, hi, limit=8):
        hits = [(off, vals) for off, vals in table.items()
                if plausible(title, lo, hi, vals)]
        print(f"  {title}")
        if not hits:
            print("    (no candidates — drive while it samples)")
        for off, vals in hits[:limit]:
            shown = "  ".join(f"{v:9.3f}" for v in vals[:6])
            print(f"    offset {off:>4}: {shown}")
        if len(hits) > limit:
            print(f"    ... and {len(hits) - limit} more")
        print()

    # Ranges chosen to be loose enough not to miss the field and tight enough
    # to throw out most of the noise.
    report("speed-like  (5..400, changing)", floats, 5.0, 400.0)
    report("rpm-like    (400..20000, changing)", floats, 400.0, 20000.0)
    report("pedal-like  (0..1, changing)", floats, 0.0, 1.0)
    report("steer-like  (-1..1, changing)", floats,
           -1.0, 1.0)

    gears = [(off, vals) for off, vals in ints.items()
             if all(-1 <= v <= 9 for v in vals) and len(set(vals)) > 1]
    print("  gear-like   (int -1..9, changing)")
    if not gears:
        print("    (no candidates — change gear while it samples)")
    for off, vals in gears[:8]:
        print(f"    offset {off:>4}: {vals[:8]}")
    print()


def hexdump(data, limit=128):
    for i in range(0, min(len(data), limit), 16):
        row = data[i:i + 16]
        hexpart = " ".join(f"{b:02x}" for b in row)
        print(f"    {i:>4}  {hexpart}")
    if len(data) > limit:
        print(f"    ... {len(data) - limit} more bytes")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1", help="machine running AC")
    p.add_argument("--port", type=int, default=AC_PORT)
    p.add_argument("--samples", type=int, default=40)
    p.add_argument("--hexdump", action="store_true", help="dump the first packet")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(4.0)
    target = (args.host, args.port)

    print(f"handshaking with {target[0]}:{target[1]}")
    sock.sendto(handshake_packet(OP_HANDSHAKE), target)
    try:
        data, _ = sock.recvfrom(4096)
    except (socket.timeout, ConnectionResetError):
        # Windows reports "nothing is listening on that UDP port" as
        # ECONNRESET rather than as a timeout, so both mean the same thing.
        print("\n  no response.\n"
              "  - is Assetto Corsa running and on track (not in a menu)?\n"
              "  - is UDP telemetry enabled in its settings?\n"
              "  - if AC is on another PC, pass --host\n", file=sys.stderr)
        return 1
    read_handshake_response(data)

    print("\nsubscribing to car updates — drive now")
    sock.sendto(handshake_packet(OP_SUBSCRIBE_UPDATE), target)

    samples = []
    sizes = set()
    try:
        while len(samples) < args.samples:
            data, _ = sock.recvfrom(4096)
            sizes.add(len(data))
            samples.append(data)
    except (socket.timeout, ConnectionResetError):
        pass
    finally:
        try:
            sock.sendto(handshake_packet(OP_DISMISS), target)
        except OSError:
            pass

    if not samples:
        print("  no car packets arrived", file=sys.stderr)
        return 1

    print(f"  packet sizes seen: {sorted(sizes)}")
    if len(sizes) > 1:
        print("  (more than one packet type on this port — "
              "filter by size before parsing)")
        biggest = max(sizes)
        samples = [s for s in samples if len(s) == biggest]
        print(f"  analysing the {len(samples)} packets of {biggest} bytes")

    if args.hexdump:
        print("\n  first packet:")
        hexdump(samples[0])

    analyse(samples)
    print("  Paste this output back and the C++ adapter can be written\n"
          "  against the offsets that actually showed up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
