#pragma once

#include <QObject>
#include <QUdpSocket>
#include <QNetworkDatagram>
#include <QElapsedTimer>

#include <cstring>
#include <optional>

#include "TelemetryPacket.h"

// Receives telemetry datagrams and turns them into validated frames.
//
// The parsing itself is three lines. Everything else here is the part that
// actually matters on a real link: rejecting malformed input before it can
// hurt you, and measuring what the link is doing to you rather than assuming
// it is behaving.

class TelemetryReceiver : public QObject
{
    Q_OBJECT

public:
    struct Stats {
        quint64 received      = 0;
        quint64 rejected      = 0;  // wrong size, bad magic, wrong version
        quint64 lost          = 0;  // inferred from gaps in the frame counter
        quint64 outOfOrder    = 0;  // arrived with a frame number we passed already
        double  packetsPerSec = 0.0;
    };

    explicit TelemetryReceiver(QObject *parent = nullptr)
        : QObject(parent), m_socket(new QUdpSocket(this))
    {
        connect(m_socket, &QUdpSocket::readyRead, this, &TelemetryReceiver::drain);
    }

    bool listen(quint16 port = telemetry::kDefaultPort)
    {
        m_clock.start();
        // ShareAddress lets you run a second tool on the same stream while
        // developing — a packet sniffer alongside the dash, for instance.
        return m_socket->bind(QHostAddress::AnyIPv4, port,
                              QUdpSocket::ShareAddress | QUdpSocket::ReuseAddressHint);
    }

    Stats stats() const { return m_stats; }

signals:
    void frameReceived(const telemetry::CarTelemetry &frame);

private slots:
    void drain()
    {
        while (m_socket->hasPendingDatagrams()) {
            const QNetworkDatagram dg = m_socket->receiveDatagram();
            if (const auto frame = parse(dg.data()))
                emit frameReceived(*frame);
        }
        const double secs = m_clock.elapsed() / 1000.0;
        m_stats.packetsPerSec = secs > 0.0 ? double(m_stats.received) / secs : 0.0;
    }

private:
    // Never reinterpret_cast a network buffer into a struct. The buffer has no
    // alignment guarantee and an attacker (or a bug) controls its length; a
    // size check plus memcpy costs nothing and cannot trap.
    std::optional<telemetry::CarTelemetry> parse(const QByteArray &bytes)
    {
        using namespace telemetry;

        if (bytes.size() != int(sizeof(CarTelemetry))) { ++m_stats.rejected; return std::nullopt; }

        CarTelemetry frame{};
        std::memcpy(&frame, bytes.constData(), sizeof(frame));

        if (frame.header.magic   != kMagic)           { ++m_stats.rejected; return std::nullopt; }
        if (frame.header.version != kProtocolVersion) { ++m_stats.rejected; return std::nullopt; }
        if (frame.header.packetId != quint8(PacketId::CarTelemetry)) {
            ++m_stats.rejected;  // a packet type this build does not know yet
            return std::nullopt;
        }

        accountForOrdering(frame.header.frame);
        ++m_stats.received;
        return frame;
    }

    void accountForOrdering(quint32 frameNo)
    {
        if (!m_seenAny) {
            m_seenAny = true;
            m_highestFrame = frameNo;
            return;
        }
        if (frameNo > m_highestFrame + 1)
            m_stats.lost += frameNo - m_highestFrame - 1;
        if (frameNo <= m_highestFrame) {
            ++m_stats.outOfOrder;
            // A late packet that we already compensated for is not also a loss.
            if (m_stats.lost > 0) --m_stats.lost;
        }
        m_highestFrame = qMax(m_highestFrame, frameNo);
    }

    QUdpSocket   *m_socket;
    QElapsedTimer m_clock;
    Stats         m_stats;
    quint32       m_highestFrame = 0;
    bool          m_seenAny      = false;
};
