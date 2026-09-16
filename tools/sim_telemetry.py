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
    python sim_telemetry.py --trace               # print the speed trace and exit

The lap is generated the way a simple lap-time simulator does it: take the
apex speed of every corner, integrate backwards under a braking limit and
forwards under an acceleration limit, and keep whichever is lower at each
point. That produces a speed trace with real braking zones and real
corner exits, instead of a sine wave that happens to wobble.
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

# ── vehicle ───────────────────────────────────────────────────────────────
REV_LIMIT = 11800.0
IDLE_RPM = 3800.0
# Top speed reachable in each gear, km/h. Index 0 is unused so the list index
# is the gear number. Gear 1 topping at 95 km/h is a race car, not a road car:
# first is sized for the slowest hairpin on the track, not for pulling away.
GEAR_TOP_KPH = [0.0, 95.0, 130.0, 168.0, 205.0, 240.0, 272.0, 295.0, 312.0]

A_ACCEL = 4.5    # m/s², traction- and power-limited average
A_BRAKE = 15.0   # m/s², a car with downforce brakes far harder than it accelerates
V_MAX = 312.0 / 3.6

# ── track ─────────────────────────────────────────────────────────────────
LAP_LENGTH_M = 5300.0
DS = 5.0  # integration step, metres

# (distance along the lap in metres, apex speed in km/h)
#
# The gap from the last corner around to T1 is deliberately ~1600 m. A shorter
# main straight never lets the car reach top gear, which makes the whole upper
# half of the gearbox dead weight on the display.
CORNERS = [
    (1000, 100),   # T1, heavy braking at the end of the main straight
    (1450, 175),   # fast right
    (1950, 78),    # hairpin — slowest point of the lap
    (2500, 160),
    (3050, 120),
    (3650, 205),   # long fast sweeper
    (4150, 90),    # late chicane
    (4700, 150),   # last corner, onto the main straight
]


def build_speed_trace():
    """Forward/backward integration over the corner list.

    Backward pass: from every corner apex, how fast could you have been
    travelling and still slow down in time? Forward pass: from every apex,
    how fast can you actually be by here given you had to accelerate out?
    The lower of the two is the speed the car can hold.
    """
    n = int(LAP_LENGTH_M / DS)
    v = [V_MAX] * n

    for dist, kph in CORNERS:
        i = int(dist / DS) % n
        v[i] = min(v[i], kph / 3.6)

    # Twice around, so the constraints wrap across the start/finish line.
    for _ in range(2):
        for i in range(n - 1, -1, -1):
            nxt = v[(i + 1) % n]
            v[i] = min(v[i], math.sqrt(nxt * nxt + 2 * A_BRAKE * DS))
    for _ in range(2):
        for i in range(n):
            prv = v[(i - 1) % n]
            v[i] = min(v[i], math.sqrt(prv * prv + 2 * A_ACCEL * DS))

    return v


TRACE = build_speed_trace()
N = len(TRACE)


def gear_and_rpm(kph):
    """Engine speed follows road speed through whichever gear holds it.

    Picking the lowest gear whose top speed covers the current road speed
    reproduces the sawtooth for free: as the car slows into a corner it drops
    through the gears and the rpm jumps back up on each downshift.
    """
    gear = len(GEAR_TOP_KPH) - 1
    for i in range(1, len(GEAR_TOP_KPH)):
        if kph <= GEAR_TOP_KPH[i]:
            gear = i
            break
    rpm = REV_LIMIT * (kph / GEAR_TOP_KPH[gear])
    return gear, max(IDLE_RPM, min(REV_LIMIT, rpm))


class Car:
    """Walks the speed trace, carrying lap distance between frames."""

    def __init__(self):
        self.distance = 0.0
        self.lap = 1

    def step(self, dt):
        i = int(self.distance / DS) % N
        v = TRACE[i]

        self.distance += v * dt
        if self.distance >= LAP_LENGTH_M:
            self.distance -= LAP_LENGTH_M
            self.lap += 1

        # Longitudinal acceleration straight off the trace: v·dv/ds.
        v_next = TRACE[(i + 1) % N]
        accel = (v_next * v_next - v * v) / (2.0 * DS)

        if accel > 0.3:
            throttle, brake = min(1.0, accel / A_ACCEL), 0.0
        elif accel < -0.3:
            throttle, brake = 0.0, min(1.0, -accel / A_BRAKE)
        elif v > 0.985 * V_MAX:
            # Flat out on the straight: the car is power-limited, so it is at
            # full throttle even though it has stopped accelerating.
            throttle, brake = 1.0, 0.0
        else:
            throttle, brake = 0.42, 0.0  # holding speed through a fast corner

        # Steering follows how tight the corner is: the slower the car is
        # being held relative to the straight-line maximum, the more lock.
        tightness = max(0.0, 1.0 - v / V_MAX)
        steer = math.sin(self.distance / LAP_LENGTH_M * 2.0 * math.pi * 4.0) * tightness

        kph = v * 3.6
        gear, rpm = gear_and_rpm(kph)
        drs = 1 if (throttle > 0.95 and kph > 240.0) else 0

        return {
            "kph": kph, "rpm": rpm, "throttle": throttle, "brake": brake,
            "steer": max(-1.0, min(1.0, steer)), "gear": gear, "drs": drs,
            "distance": self.distance, "lap": self.lap,
        }


def build(frame, t, s):
    load = 0.45 + 0.55 * s["throttle"]
    heat = 0.6 + 0.4 * (s["kph"] / 312.0)
    return struct.pack(
        FORMAT,
        MAGIC, VERSION, PACKET_CAR_TELEMETRY, frame,
        t,
        s["kph"], s["rpm"], s["throttle"], s["brake"], s["steer"],
        s["gear"], s["drs"], 0,
        88.0 + 16.0 * load,
        96.0 + 22.0 * heat, 97.0 + 22.0 * heat,
        101.0 + 24.0 * heat, 100.0 + 24.0 * heat,
        s["distance"],
        s["lap"],
    )


def print_trace():
    print(f"lap {LAP_LENGTH_M:.0f} m · {N} points · {DS:.0f} m step\n")
    print(f"{'dist':>6} {'kph':>6} {'gear':>5} {'rpm':>7}")
    for i in range(0, N, N // 40):
        kph = TRACE[i] * 3.6
        g, rpm = gear_and_rpm(kph)
        bar = "#" * int(kph / 8)
        print(f"{i*DS:>6.0f} {kph:>6.1f} {g:>5} {rpm:>7.0f}  {bar}")
    speeds = [v * 3.6 for v in TRACE]
    print(f"\nmin {min(speeds):.1f} kph · max {max(speeds):.1f} kph")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=20777)
    p.add_argument("--rate", type=float, default=60.0, help="packets per second")
    p.add_argument("--drop", type=float, default=0.0, help="drop probability, 0..1")
    p.add_argument("--jitter", type=float, default=0.0, help="max reorder delay in seconds")
    p.add_argument("--trace", action="store_true", help="print the speed trace and exit")
    args = p.parse_args()

    if args.trace:
        print_trace()
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    period = 1.0 / args.rate
    car = Car()
    start = time.perf_counter()
    frame = 0
    held = []  # packets deliberately delayed, to force out-of-order arrival

    print(f"sending {args.rate:g} Hz to {args.host}:{args.port}  "
          f"(drop={args.drop:g} jitter={args.jitter:g})  Ctrl-C to stop")

    try:
        while True:
            now = time.perf_counter()
            t = now - start
            payload = build(frame, t, car.step(period))
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
        print(f"\nstopped after {frame} frames, lap {car.lap}")


if __name__ == "__main__":
    main()
