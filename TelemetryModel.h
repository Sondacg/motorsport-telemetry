#pragma once

#include <QObject>
#include <QVariantList>
#include <QTimer>
#include <QElapsedTimer>

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
    Q_PROPERTY(QVariantList tyreTempC MEMBER m_tyreTempC NOTIFY updated)
    Q_PROPERTY(qreal lapDistanceM MEMBER m_lapDistanceM NOTIFY updated)
    Q_PROPERTY(int   lapNumber    MEMBER m_lapNumber    NOTIFY updated)

    Q_PROPERTY(qreal revLimit     MEMBER m_revLimit     CONSTANT)

    // Link health — separate from the car's state, because a display that
    // cannot tell "the car is stationary" from "the link is dead" is worse
    // than no display.
    Q_PROPERTY(bool  live         MEMBER m_live         NOTIFY updated)
    Q_PROPERTY(qreal packetsPerSec MEMBER m_pps         NOTIFY updated)
    Q_PROPERTY(qint64 received    MEMBER m_received     NOTIFY updated)
    Q_PROPERTY(qint64 lost        MEMBER m_lost         NOTIFY updated)
    Q_PROPERTY(qint64 outOfOrder  MEMBER m_outOfOrder   NOTIFY updated)
    Q_PROPERTY(qint64 rejected    MEMBER m_rejected     NOTIFY updated)

public:
    explicit TelemetryModel(TelemetryReceiver *rx, QObject *parent = nullptr)
        : QObject(parent), m_rx(rx)
    {
        m_tyreTempC = QVariantList{ 0.0, 0.0, 0.0, 0.0 };
        m_sinceFrame.start();

        connect(rx, &TelemetryReceiver::frameReceived,
                this, [this](const telemetry::CarTelemetry &f) {
            m_latest = f;
            m_haveFrame = true;
            m_sinceFrame.restart();
        });

        // 60 Hz publish rate, independent of how fast packets arrive.
        connect(&m_publish, &QTimer::timeout, this, &TelemetryModel::publish);
        m_publish.start(16);
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
            m_tyreTempC    = QVariantList{ f.tyreTempC[0], f.tyreTempC[1],
                                           f.tyreTempC[2], f.tyreTempC[3] };
            m_lapDistanceM = f.lapDistanceM;
            m_lapNumber    = int(f.lapNumber);
        }
        m_live = live;

        const auto s  = m_rx->stats();
        m_pps         = s.packetsPerSec;
        m_received    = qint64(s.received);
        m_lost        = qint64(s.lost);
        m_outOfOrder  = qint64(s.outOfOrder);
        m_rejected    = qint64(s.rejected);

        emit updated();
    }

    TelemetryReceiver *m_rx;
    QTimer m_publish;
    QElapsedTimer m_sinceFrame;
    telemetry::CarTelemetry m_latest{};
    bool m_haveFrame = false;

    qreal m_speedKph = 0, m_rpm = 0, m_throttle = 0, m_brake = 0, m_steer = 0;
    int   m_gear = 0;
    bool  m_drs = false;
    qreal m_engineTempC = 0;
    QVariantList m_tyreTempC;
    qreal m_lapDistanceM = 0;
    int   m_lapNumber = 0;

    qreal m_revLimit = 11800.0;

    bool   m_live = false;
    qreal  m_pps = 0;
    qint64 m_received = 0, m_lost = 0, m_outOfOrder = 0, m_rejected = 0;
};
