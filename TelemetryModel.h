#pragma once

#include <QObject>
#include <QVariantList>
#include <QString>
#include <QTimer>
#include <QElapsedTimer>
#include <QQueue>

#include "TelemetryReceiver.h"

// Presentation model: the bridge between the telemetry link and the display.
//
// Two deliberate choices here.
//
// One signal for the whole frame, not one per property. A packet is an atomic
// snapshot of the car; emitting eight separate change signals would let a
// binding evaluate against a half-updated state, showing this frame's speed
// next to last frame's gear.
//
// Frames are latched and published on a timer rather than forwarded as they
// arrive. The link can run faster than the screen — and on a real car it will
// — so decoupling them means the display costs the same whether telemetry
// arrives at 60 Hz or 500 Hz.

class TelemetryModel : public QObject
{
    Q_OBJECT

    Q_PROPERTY(qreal speedKph     MEMBER m_speedKph     NOTIFY updated)
    Q_PROPERTY(qreal rpm          MEMBER m_rpm          NOTIFY updated)
    Q_PROPERTY(qreal throttle     MEMBER m_throttle     NOTIFY updated)
    Q_PROPERTY(qreal brake        MEMBER m_brake        NOTIFY updated)
    Q_PROPERTY(qreal steer        MEMBER m_steer        NOTIFY updated)
    Q_PROPERTY(int   gear         MEMBER m_gear         NOTIFY updated)
    Q_PROPERTY(bool  drs          MEMBER m_drs          NOTIFY updated)
    Q_PROPERTY(qreal engineTempC  MEMBER m_engineTempC  NOTIFY updated)
    Q_PROPERTY(QVariantList wheelSlipRatio MEMBER m_wheelSlip NOTIFY updated)
    Q_PROPERTY(qreal lapDistanceM MEMBER m_lapDistanceM NOTIFY updated)
    Q_PROPERTY(int   lapNumber    MEMBER m_lapNumber    NOTIFY updated)

    // Not CONSTANT: the limit depends on the car, and a source that does not
    // announce it has to be observed instead.
    Q_PROPERTY(qreal revLimit     MEMBER m_revLimit     NOTIFY updated)

    // Link health — separate from the car's state, because a display that
    // cannot tell "the car is stationary" from "the link is dead" is worse
    // than no display.
    Q_PROPERTY(bool  live         MEMBER m_live         NOTIFY updated)
    Q_PROPERTY(qreal packetsPerSec MEMBER m_pps         NOTIFY updated)
    Q_PROPERTY(qint64 received    MEMBER m_received     NOTIFY updated)
    Q_PROPERTY(qint64 lost        MEMBER m_lost         NOTIFY updated)
    Q_PROPERTY(qint64 outOfOrder  MEMBER m_outOfOrder   NOTIFY updated)
    Q_PROPERTY(qint64 rejected    MEMBER m_rejected     NOTIFY updated)
    // False when the source carries no sequence number, so loss and ordering
    // cannot be measured. Showing zeros there would claim a perfect link
    // rather than admit the question is unanswerable.
    Q_PROPERTY(bool linkStatsValid MEMBER m_linkStatsValid CONSTANT)
    // What to tell the viewer while nothing has arrived. It depends on the
    // source, and a hint that names the wrong one sends them to fix the wrong
    // thing.
    Q_PROPERTY(QString waitingHint MEMBER m_waitingHint CONSTANT)

public:
    // rx may be null: a source that is not this project's own UDP link has no
    // frame counter behind it, so there are no loss statistics to report.
    explicit TelemetryModel(TelemetryReceiver *rx, QObject *parent = nullptr)
        : QObject(parent), m_rx(rx), m_linkStatsValid(rx != nullptr)
    {
        m_wheelSlip = QVariantList{ 0.0, 0.0, 0.0, 0.0 };
        m_sinceFrame.start();
        m_clock.start();

        if (rx)
            connect(rx, &TelemetryReceiver::frameReceived,
                    this, &TelemetryModel::ingest);

        // 60 Hz publish rate, independent of how fast packets arrive.
        connect(&m_publish, &QTimer::timeout, this, &TelemetryModel::publish);
        m_publish.start(16);
    }

    void setWaitingHint(const QString &hint) { m_waitingHint = hint; }
    void setRevLimit(qreal rpm) { if (rpm > 0.0) m_revLimit = rpm; }

public slots:
    // Every source funnels through here, whatever protocol it came off.
    void ingest(const telemetry::CarTelemetry &frame)
    {
        m_latest = frame;
        m_haveFrame = true;
        ++m_ownCount;
        m_arrivals.enqueue(m_clock.elapsed());
        m_sinceFrame.restart();

        // Shift lights that never reach the top are worse than none. When a
        // car revs past the configured limit, believe the car.
        if (frame.rpm > m_revLimit)
            m_revLimit = frame.rpm;
    }

signals:
    void updated();

private:
    void publish()
    {
        // A link is live if a frame landed recently. Half a second is long
        // enough to ride out a burst of loss, short enough that a pulled
        // cable shows up before the driver trusts a stale number.
        const bool live = m_haveFrame && m_sinceFrame.elapsed() < 500;

        if (live) {
            const auto &f = m_latest;
            m_speedKph     = f.speedKph;
            m_rpm          = f.rpm;
            m_throttle     = f.throttle;
            m_brake        = f.brake;
            m_steer        = f.steer;
            m_gear         = f.gear;
            m_drs          = f.drs != 0;
            m_engineTempC  = f.engineTempC;
            m_wheelSlip    = QVariantList{ f.wheelSlipRatio[0], f.wheelSlipRatio[1],
                                           f.wheelSlipRatio[2], f.wheelSlipRatio[3] };
            m_lapDistanceM = f.lapDistanceM;
            m_lapNumber    = int(f.lapNumber);
        }
        m_live = live;

        if (m_rx) {
            const auto s  = m_rx->stats();
            m_pps         = s.packetsPerSec;
            m_received    = qint64(s.received);
            m_lost        = qint64(s.lost);
            m_outOfOrder  = qint64(s.outOfOrder);
            m_rejected    = qint64(s.rejected);
        } else {
            // Trailing window, for the same reason the receiver uses one: an
            // average taken since startup describes the wait, not the link.
            const qint64 now = m_clock.elapsed();
            while (!m_arrivals.isEmpty() && now - m_arrivals.head() > 2000)
                m_arrivals.dequeue();
            m_pps      = m_arrivals.size() / 2.0;
            m_received = qint64(m_ownCount);
        }

        emit updated();
    }

    TelemetryReceiver *m_rx;
    QTimer m_publish;
    QElapsedTimer m_sinceFrame;
    QElapsedTimer m_clock;
    telemetry::CarTelemetry m_latest{};
    bool m_haveFrame = false;
    quint64 m_ownCount = 0;
    QQueue<qint64> m_arrivals;
    bool m_linkStatsValid = true;
    QString m_waitingHint;

    qreal m_speedKph = 0, m_rpm = 0, m_throttle = 0, m_brake = 0, m_steer = 0;
    int   m_gear = 0;
    bool  m_drs = false;
    qreal m_engineTempC = 0;
    QVariantList m_wheelSlip;
    qreal m_lapDistanceM = 0;
    int   m_lapNumber = 0;

    qreal m_revLimit = 11800.0;

    bool   m_live = false;
    qreal  m_pps = 0;
    qint64 m_received = 0, m_lost = 0, m_outOfOrder = 0, m_rejected = 0;
};
