#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QCommandLineParser>
#include <QTextStream>
#include <QTimer>

#include "TelemetryReceiver.h"
#include "TelemetryModel.h"
#include "AssettoCorsaSource.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QCoreApplication::setApplicationName("telemetry-dash");

    QCommandLineParser cli;
    cli.addHelpOption();
    QCommandLineOption portOpt({"p", "port"}, "UDP port to listen on.", "port",
                               QString::number(telemetry::kDefaultPort));
    QCommandLineOption shotOpt("shot",
        "Grab the window to a PNG once telemetry is flowing, then exit. "
        "Keeps the README image reproducible instead of hand-cropped.", "file");
    QCommandLineOption shotDelayOpt("shot-delay",
        "Milliseconds to wait before grabbing.", "ms", "2500");
    QCommandLineOption acOpt("ac",
        "Take telemetry from Assetto Corsa directly instead of this project's "
        "own UDP format.");
    QCommandLineOption acHostOpt("ac-host", "Machine running AC.", "host", "127.0.0.1");
    QCommandLineOption trackOpt("track-length",
        "Lap length in metres. AC reports position as a fraction of the lap, so "
        "the distance on screen is only as accurate as this.", "m", "5000");
    cli.addOption(portOpt);
    cli.addOption(shotOpt);
    cli.addOption(shotDelayOpt);
    cli.addOption(acOpt);
    cli.addOption(acHostOpt);
    cli.addOption(trackOpt);
    cli.process(app);

    // Two sources, one signal. The model is handed a frame producer and never
    // asks which kind it is.
    TelemetryReceiver receiver;
    AssettoCorsaSource assettoCorsa;
    const bool useAc = cli.isSet(acOpt);
    TelemetryModel model(useAc ? nullptr : &receiver);

    if (useAc) {
        QObject::connect(&assettoCorsa, &AssettoCorsaSource::frameReceived,
                         &model, &TelemetryModel::ingest);
        QObject::connect(&assettoCorsa, &AssettoCorsaSource::connectedToSim,
                         &app, [](const QString &car, const QString &track) {
            QTextStream(stdout) << "Assetto Corsa: " << car << " at " << track << "\n";
        });
        assettoCorsa.start(QHostAddress(cli.value(acHostOpt)),
                           AssettoCorsaSource::kAcPort,
                           cli.value(trackOpt).toFloat());
        QTextStream(stdout) << "waiting for Assetto Corsa — get on track\n";
    } else if (!receiver.listen(quint16(cli.value(portOpt).toUShort()))) {
        QTextStream(stderr) << "cannot bind UDP port — is something else listening?\n";
        return 1;
    }

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty("telemetry", &model);
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed,
                     &app, []() { QCoreApplication::exit(1); },
                     Qt::QueuedConnection);
    engine.loadFromModule("Dash", "Main");

    const QString shot = cli.value(shotOpt);
    if (!shot.isEmpty()) {
        QTimer::singleShot(cli.value(shotDelayOpt).toInt(), &app, [&engine, shot]() {
            const auto roots = engine.rootObjects();
            auto *window = roots.isEmpty() ? nullptr
                                           : qobject_cast<QQuickWindow *>(roots.first());
            if (!window) {
                QTextStream(stderr) << "no window to grab\n";
                QCoreApplication::exit(1);
                return;
            }
            const QImage image = window->grabWindow();
            if (image.isNull() || !image.save(shot)) {
                QTextStream(stderr) << "could not write " << shot << "\n";
                QCoreApplication::exit(1);
                return;
            }
            QTextStream(stdout) << "wrote " << shot << " ("
                                << image.width() << "x" << image.height() << ")\n";
            QCoreApplication::quit();
        });
    }

    return app.exec();
}
