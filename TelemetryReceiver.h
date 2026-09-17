#pragma once

#include <QObject>
#include <QUdpSocket>
#include <QNetworkDatagram>
#include <QElapsedTimer>
#include <QQueue>

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
        quint64 restarts      = 0;  // the source began counting again
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
        m_stats.packetsPerSec = rate();
    }

private:
    // Packet rate over a short trailing window, not over the whole session.
    // Dividing total packets by total uptime answers "what was the average
    // since the program started", which is not the question: a display opened
    // minutes before the source reports a dead link that is actually healthy.
    double rate()
    {
        const qint64 now = m_clock.elapsed();
        while (!m_arrivals.isEmpty() && now - m_arrivals.head() > kRateWindowMs)
            m_arrivals.dequeue();
        return m_arrivals.size() * 1000.0 / double(kRateWindowMs);
    }

    static constexpr qint64 kRateWindowMs = 2000;
    QQueue<qint64> m_arrivals;

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
        m_arrivals.enqueue(m_clock.elapsed());
        return frame;
    }

    // A frame number far below the highest seen is not a late packet — it is a
    // source that restarted and began counting from zero again. Treating that
    // as reordering floods the statistics with hundreds of phantom events and
    // buries the next real problem, so rebase instead and count the restart.
    static constexpr quint32 kRestartGap = 100;

    void accountForOrdering(quint32 frameNo)
    {
        if (!m_seenAny) {
            m_seenAny = true;
            m_highestFrame = frameNo;
            return;
        }
        if (frameNo + kRestartGap < m_highestFrame) {
            ++m_stats.restarts;
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
