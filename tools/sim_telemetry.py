#!/usr/bin/env python3
"""Synthetic telemetry source.

Emits CarTelemetry packets matching TelemetryPacket.h so the receiver can be
built and tested with no simulator, no game, and no hardware. It also does
what a real link does badly on purpose: it can drop packets and reorder them,
which is the only way to prove the receiver actually handles either.

    python sim_telemetry.py                       # clean 60 Hz stream
    python sim_telemetry.py --drop 0.05           # lose 5% of packets
    python sim_telemetry.py --jitter 0.02         # reorder within 20 ms
    python sim_telemetry.py --rate 120 --port 20777
"""

import argparse
import math
import random
import socket
import struct
import time

MAGIC = 0x5443
VERSION = 1
PACKET_CAR_TELEMETRY = 0

# Must stay in lockstep with TelemetryPacket.h.
#   <        little-endian, no padding
#   HBBI     magic, version, packetId, frame
#   f        sessionTime
#   fffff    speed, rpm, throttle, brake, steer
#   bBH      gear, drs, reserved
#   f        engineTemp
#   ffff     tyre temps
#   f        lapDistance
#   I        lapNumber
FORMAT = "<HBBIffffffbBHffffffI"
assert struct.calcsize(FORMAT) == 64, struct.calcsize(FORMAT)

GEAR_UPSHIFT_RPM = 11800.0
GEAR_RATIOS = [0.0, 60.0, 95.0, 130.0, 165.0, 200.0, 240.0, 280.0, 320.0]
LAP_LENGTH_M = 5891.0


def lap_model(t):
    """A crude but plausible lap: three straights joined by corner phases.

    Not a vehicle model — that arrives in phase F2. This only has to produce
    signals with the right shape and range so the dash has something honest
    to render.
    """
    phase = (t % 92.0) / 92.0
    corner = 0.5 * (1.0 + math.sin(phase * 2.0 * math.pi * 7.0))
    target = 90.0 + (310.0 - 90.0) * (1.0 - corner) ** 1.6

    throttle = max(0.0, min(1.0, (1.0 - corner) * 1.4))
    brake = max(0.0, min(1.0, (corner - 0.55) * 2.6))
    steer = math.sin(phase * 2.0 * math.pi * 7.0 + 0.4) * corner

    gear = 1
    for g, top in enumerate(GEAR_RATIOS):
        if target >= top:
            gear = max(1, g)
    gear = min(gear, 8)

    span = GEAR_RATIOS[gear] - GEAR_RATIOS[gear - 1] if gear > 1 else GEAR_RATIOS[1]
    into = (target - GEAR_RATIOS[gear - 1]) / span if span > 0 else 0.0
    into = max(0.0, min(1.0, into))  # keep rpm inside the rev limit
    rpm = 5200.0 + into * (GEAR_UPSHIFT_RPM - 5200.0)

    return target, rpm, throttle, brake, steer, gear


def build(frame, t):
    speed, rpm, throttle, brake, steer, gear = lap_model(t)
    load = 0.5 + 0.5 * throttle
    return struct.pack(
        FORMAT,
        MAGIC, VERSION, PACKET_CAR_TELEMETRY, frame,
        t,
        speed, rpm, throttle, brake, steer,
        gear, 1 if speed > 250.0 else 0, 0,
        88.0 + 14.0 * load,
        95.0 + 18.0 * load, 96.0 + 18.0 * load,
        99.0 + 20.0 * load, 98.0 + 20.0 * load,
        (speed / 3.6 * t) % LAP_LENGTH_M,
        int(t // 92.0) + 1,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=20777)
    p.add_argument("--rate", type=float, default=60.0, help="packets per second")
    p.add_argument("--drop", type=float, default=0.0, help="drop probability, 0..1")
    p.add_argument("--jitter", type=float, default=0.0, help="max reorder delay in seconds")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    period = 1.0 / args.rate
    start = time.perf_counter()
    frame = 0
    held = []  # packets deliberately delayed, to force out-of-order arrival

    print(f"sending {args.rate:g} Hz to {args.host}:{args.port}  "
          f"(drop={args.drop:g} jitter={args.jitter:g})  Ctrl-C to stop")

    try:
        while True:
            now = time.perf_counter()
            t = now - start
            payload = build(frame, t)
            frame += 1

            if random.random() < args.drop:
                pass  # dropped on purpose
            elif args.jitter > 0.0 and random.random() < 0.25:
                held.append((now + random.uniform(0.0, args.jitter), payload))
            else:
                sock.sendto(payload, (args.host, args.port))

            due = [h for h in held if h[0] <= now]
            for _, data in due:
                sock.sendto(data, (args.host, args.port))
            held = [h for h in held if h[0] > now]

            sleep = start + frame * period - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
    except KeyboardInterrupt:
        print(f"\nstopped after {frame} frames")


if __name__ == "__main__":
    main()
