#pragma once

#include <cstdint>

// Wire format for the telemetry link.
//
// This is the contract between whatever produces telemetry (the synthetic
// generator today, a simulator or a real car later) and everything that
// consumes it. Treat it like an ICD: once something else depends on it,
// changes go through PROTOCOL_VERSION, never by silently moving a field.
//
// Design rules, and why:
//   - Fixed-width types only. `int` is not a wire type.
//   - Packed, no implicit padding, so the layout is what you can count.
//   - Little-endian on the wire. Both ends are x86 today; the day one end
//     is a big-endian MCU, this is the single place that has to change.
//   - A monotonic frame counter, so the receiver can measure loss instead
//     of guessing about it.

namespace telemetry {

inline constexpr uint16_t kMagic           = 0x5443;  // 'TC'
inline constexpr uint8_t  kProtocolVersion = 2;
inline constexpr uint16_t kDefaultPort     = 20777;

enum class PacketId : uint8_t {
    CarTelemetry = 0,
};

#pragma pack(push, 1)

struct Header {
    uint16_t magic;        // kMagic — cheap garbage filter
    uint8_t  version;      // kProtocolVersion
    uint8_t  packetId;     // PacketId
    uint32_t frame;        // monotonic, increments once per emitted frame
    float    sessionTime;  // seconds since session start
};
static_assert(sizeof(Header) == 12, "Header layout drifted");

struct CarTelemetry {
    Header  header;

    float   speedKph;
    float   rpm;
    float   throttle;      // 0.0 .. 1.0
    float   brake;         // 0.0 .. 1.0
    float   steer;         // -1.0 (full left) .. 1.0 (full right)

    int8_t  gear;          // -1 = reverse, 0 = neutral, 1..8
    uint8_t drs;           // 0 = closed, 1 = open
    uint16_t reserved;     // explicit — never let the compiler choose padding

    float   engineTempC;

    // Per-wheel state, FL FR RL RR.
    //
    // v2 replaced tyre temperatures with these. Temperatures were invented for
    // the synthetic source and no real telemetry link here carries them, while
    // wheel speed against road speed IS the signal a traction controller acts
    // on — so phase 2 needs these and would never have needed the other.
    float   wheelAngularSpeed[4];  // rad/s
    float   wheelSlipRatio[4];     // 0 = rolling, >0 = spinning, <0 = locking

    float   lapDistanceM;
    uint32_t lapNumber;
};
static_assert(sizeof(CarTelemetry) == 80, "CarTelemetry layout drifted");

#pragma pack(pop)

}  // namespace telemetry
