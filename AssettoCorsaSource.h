#pragma once

#include <QObject>
#include <QUdpSocket>
#include <QNetworkDatagram>
#include <QHostAddress>
#include <QTimer>

#include <cstring>

#include "TelemetryPacket.h"

// Translates Assetto Corsa's telemetry into this project's wire format.
//
// This is an adapter, not a replacement. AC's layout stops here; everything
// downstream — the model, the display, and the controller in phase 2 — keeps
// speaking CarTelemetry and never learns that a game is involved. Adding a
// second simulator later means another class like this one and nothing else.
//
// THE OFFSETS BELOW WERE READ OFF THE WIRE, NOT COPIED FROM A HEADER.
// Third-party definitions of this struct disagree with each other. These were
// derived from a live capture (tools/ac_probe.py) against a Mercedes SLS GT3
// at Spa, anchored on two facts that cannot be coincidence: the int at offset
// 4 equals the packet length, and the three floats at 8, 12 and 16 are the
// same speed in km/h, mph and m/s.

class AssettoCorsaSource : public QObject
{
    Q_OBJECT

public:
    // AC's telemetry protocol: three int32s to its port, then it streams.
    static constexpr quint16 kAcPort = 9996;
    static constexpr int kOpHandshake = 0;
    static constexpr int kOpSubscribeUpdate = 1;
    static constexpr int kOpDismiss = 3;

    // Offsets into RTCarInfo (328 bytes).
    static constexpr int kSizeOfCarInfo   = 328;
    static constexpr int kOffSize         = 4;
    static constexpr int kOffSpeedKmh     = 8;
    static constexpr int kOffLapCount     = 52;
    static constexpr int kOffGas          = 56;
    static constexpr int kOffBrake        = 60;
    static constexpr int kOffEngineRpm    = 68;
    static constexpr int kOffSteerRad     = 72;
    static constexpr int kOffGear         = 76;
    static constexpr int kOffWheelOmega   = 84;   // 4 floats, rad/s
    static constexpr int kOffSlipRatio    = 132;  // 4 floats
    static constexpr int kOffPositionNorm = 308;  // 0..1 around the lap

    // AC reports steering as wheel rotation in radians, not as a normalised
    // axis, and the lock differs per car. This scales a GT3-sized lock into
    // the -1..1 the display expects.
    static constexpr float kSteerLockRad = 3.5f;

    explicit AssettoCorsaSource(QObject *parent = nullptr)
        : QObject(parent), m_socket(new QUdpSocket(this))
    {
        connect(m_socket, &QUdpSocket::readyRead, this, &AssettoCorsaSource::drain);

        // AC answers only while a session is on track, so keep knocking rather
        // than failing at startup: the display can be opened before the game.
        connect(&m_handshake, &QTimer::timeout, this, [this] {
            if (!m_subscribed) sendOp(kOpHandshake);
        });
    }

    ~AssettoCorsaSource() override
    {
        if (m_subscribed) sendOp(kOpDismiss);
    }

    void start(const QHostAddress &host = QHostAddress::LocalHost,
               quint16 port = kAcPort, float trackLengthM = 5000.0f)
    {
        m_host = host;
        m_port = port;
        m_trackLengthM = trackLengthM;
        m_socket->bind(QHostAddress::AnyIPv4, 0);
        sendOp(kOpHandshake);
        m_handshake.start(2000);
    }

signals:
    void frameReceived(const telemetry::CarTelemetry &frame);
    void connectedToSim(const QString &car, const QString &track);

private slots:
    void drain()
    {
        while (m_socket->hasPendingDatagrams()) {
            const QByteArray bytes = m_socket->receiveDatagram().data();

            // The handshake reply carries car, driver and track as fixed-width
            // UTF-16 blocks; anything of car-info length is a telemetry frame.
            if (!m_subscribed && bytes.size() > kSizeOfCarInfo) {
                emit connectedToSim(wideAt(bytes, 0, 100), wideAt(bytes, 208, 100));
                sendOp(kOpSubscribeUpdate);
                m_subscribed = true;
                m_handshake.stop();
                continue;
            }
            if (bytes.size() == kSizeOfCarInfo)
                emit frameReceived(translate(bytes));
        }
    }

private:
    void sendOp(int operation)
    {
        struct { qint32 identifier, version, operationId; } msg{ 1, 1, operation };
        m_socket->writeDatagram(reinterpret_cast<const char *>(&msg), sizeof(msg),
                                m_host, m_port);
    }

    // AC pads these fixed-width fields with '%' rather than with NUL, so
    // stopping at the first NUL still yields "ferrari_458_gt2%".
    static QString wideAt(const QByteArray &b, int offset, int bytes)
    {
        if (b.size() < offset + bytes) return {};
        const QString s = QString::fromUtf16(
            reinterpret_cast<const char16_t *>(b.constData() + offset), bytes / 2);

        int end = s.size();
        for (const QChar terminator : { QChar(u'%'), QChar(u'\0') }) {
            const int at = s.indexOf(terminator);
            if (at >= 0) end = qMin(end, at);
        }
        return s.left(end).trimmed();
    }

    // Unaligned reads: the datagram is a byte buffer, so copy rather than cast.
    static float f32(const QByteArray &b, int offset)
    {
        float v = 0.0f;
        std::memcpy(&v, b.constData() + offset, sizeof(v));
        return v;
    }
    static qint32 i32(const QByteArray &b, int offset)
    {
        qint32 v = 0;
        std::memcpy(&v, b.constData() + offset, sizeof(v));
        return v;
    }

    telemetry::CarTelemetry translate(const QByteArray &b)
    {
        using namespace telemetry;
        CarTelemetry out{};

        out.header.magic       = kMagic;
        out.header.version     = kProtocolVersion;
        out.header.packetId    = quint8(PacketId::CarTelemetry);
        out.header.frame       = m_frame++;
        out.header.sessionTime = float(m_frame) / 60.0f;

        out.speedKph = f32(b, kOffSpeedKmh);
        out.rpm      = f32(b, kOffEngineRpm);
        out.throttle = f32(b, kOffGas);
        out.brake    = f32(b, kOffBrake);
        out.steer    = qBound(-1.0f, f32(b, kOffSteerRad) / kSteerLockRad, 1.0f);

        // AC counts 0 = reverse, 1 = neutral, 2 = first. This project counts
        // -1, 0, 1 — so the two conventions are one subtraction apart.
        out.gear = qint8(i32(b, kOffGear) - 1);

        out.drs = 0;           // AC's UDP frame carries no DRS state
        out.engineTempC = 0.0f;  // nor engine temperature

        for (int i = 0; i < 4; ++i) {
            out.wheelAngularSpeed[i] = f32(b, kOffWheelOmega + 4 * i);
            out.wheelSlipRatio[i]    = f32(b, kOffSlipRatio + 4 * i);
        }

        // AC gives position as a fraction of the lap, not metres, so this is
        // only as right as the track length it is handed.
        out.lapDistanceM = f32(b, kOffPositionNorm) * m_trackLengthM;
        out.lapNumber    = quint32(i32(b, kOffLapCount) + 1);

        return out;
    }

    QUdpSocket *m_socket;
    QTimer m_handshake;
    QHostAddress m_host = QHostAddress::LocalHost;
    quint16 m_port = kAcPort;
    float m_trackLengthM = 5000.0f;
    bool m_subscribed = false;
    quint32 m_frame = 0;
};
