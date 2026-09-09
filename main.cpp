#include <QCoreApplication>
#include <QCommandLineParser>
#include <QTimer>
#include <QTextStream>

#include "TelemetryReceiver.h"

// Console sink for the telemetry stream.
//
// The stream runs at 60 Hz; printing every frame would tell you nothing and
// cost more than the parsing. Latch the newest frame and render at 10 Hz,
// which is roughly the fastest a person reads anyway. The dash in phase F1
// replaces this sink and keeps the receiver untouched.

int main(int argc, char *argv[])
{
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName("telemetry-probe");

    QCommandLineParser cli;
    cli.addHelpOption();
    QCommandLineOption portOpt({"p", "port"}, "UDP port to listen on.", "port",
                               QString::number(telemetry::kDefaultPort));
    cli.addOption(portOpt);
    cli.process(app);

    const quint16 port = quint16(cli.value(portOpt).toUShort());

    TelemetryReceiver receiver;
    if (!receiver.listen(port)) {
        QTextStream(stderr) << "cannot bind UDP port " << port
                            << " — is something else already listening?\n";
        return 1;
    }

    telemetry::CarTelemetry latest{};
    bool haveFrame = false;

    QObject::connect(&receiver, &TelemetryReceiver::frameReceived,
                     [&](const telemetry::CarTelemetry &f) { latest = f; haveFrame = true; });

    QTextStream out(stdout);
    out << "listening on udp/" << port << "  —  run tools/sim_telemetry.py to feed it\n\n";
    out.flush();

    QTimer render;
    QObject::connect(&render, &QTimer::timeout, [&] {
        const auto s = receiver.stats();
        if (!haveFrame) {
            out << "\rwaiting for packets…" << Qt::flush;
            return;
        }
        out << Qt::fixed
            << "\r"
            << qSetFieldWidth(6) << qSetRealNumberPrecision(1) << latest.speedKph << qSetFieldWidth(0) << " kph  "
            << qSetFieldWidth(7) << qSetRealNumberPrecision(0) << latest.rpm      << qSetFieldWidth(0) << " rpm  "
            << "G" << latest.gear << "  "
            << "thr " << qSetRealNumberPrecision(2) << latest.throttle << "  "
            << "brk " << latest.brake << "  "
            << "| " << qSetRealNumberPrecision(1) << s.packetsPerSec << " pkt/s"
            << "  rx " << s.received
            << "  lost " << s.lost
            << "  ooo " << s.outOfOrder
            << "  bad " << s.rejected
            << "   " << Qt::flush;
    });
    render.start(100);

    return app.exec();
}
