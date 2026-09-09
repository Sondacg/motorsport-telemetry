# Racing Telemetry & Control Stack

A real-time telemetry and control system for motorsport, built end to end: from the wire
protocol, through a driver display, to a control law running on a microcontroller, validated
on a hardware-in-the-loop bench.

The plant is a racing simulator. That is a deliberate choice, not a shortcut — it provides a
repeatable, instrumented vehicle model that can be driven to the same corner a hundred times,
which a real car cannot.

> **Status:** Phase 1 of 4 — telemetry link and driver display.

---

## Roadmap

| Phase | Scope | State |
|---|---|---|
| **1** | UDP telemetry protocol, receiver, Qt/QML driver display | In progress |
| **2** | Traction control designed against a vehicle plant model, deployed to STM32 over CAN-FD, with a UDS diagnostic server | Planned |
| **3** | Hardware-in-the-loop bench, automated regression in CI, requirement-to-test traceability | Planned |
| **4** | Physical data logger (IMU, GPS, temperatures) and lap analysis in Python | Planned |

---

## Design notes

**The wire format is an ICD, not a struct.** `TelemetryPacket.h` is the single source of truth
for the link. Fixed-width types, explicit packing, little-endian on the wire, and
`static_assert` on `sizeof` so a field inserted in the middle fails the build instead of
silently corrupting a decode. Protocol changes go through `PROTOCOL_VERSION`.

**The stimulus came before the device under test.** `tools/sim_telemetry.py` generates
synthetic telemetry at 60 Hz and can misbehave on demand — `--drop` loses packets, `--jitter`
reorders them. Building it first means the receiver can be developed and tested with no
simulator, no game and no hardware, and it stays useful afterwards as a test fixture: proving
the receiver survives a bad link needs a link you can make bad on purpose.

**Network buffers are copied, never cast.** A datagram has no alignment guarantee and its
length is controlled by the sender, so the receiver checks the size and `memcpy`s into the
struct rather than reinterpreting the buffer in place.

**Loss and reordering are measured separately.** A late packet that arrives after its gap was
already counted is not also a loss — treating them as one number makes a healthy link look
broken and hides the difference between a congested path and a lossy one.

---

## Build

Requires Qt 6 (Core and Network) and a C++17 compiler.

```bash
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH="C:/Qt/6.11.2/mingw_64"
cmake --build build
```

## Run

Two terminals — the generator and the receiver:

```bash
python tools/sim_telemetry.py
```

```bash
./build/telemetry_probe
```

The probe prints a live line: speed, rpm, gear, throttle, brake, and the packet counters.

To verify the receiver handles a degraded link:

```bash
python tools/sim_telemetry.py --drop 0.1 --jitter 0.03
```

`lost` and `ooo` should climb while `bad` stays at zero.

---

## Layout

```
TelemetryPacket.h      Wire format — the contract between producer and consumer
TelemetryReceiver.h    Validating receiver with link statistics
main.cpp               Console sink, renders at 10 Hz
tools/sim_telemetry.py Synthetic telemetry source with fault injection
```

## License

MIT
