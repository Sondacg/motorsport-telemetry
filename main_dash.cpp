#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QCommandLineParser>
#include <QTextStream>
#include <QTimer>

#include "TelemetryReceiver.h"
#include "TelemetryModel.h"

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
    cli.addOption(portOpt);
    cli.addOption(shotOpt);
    cli.addOption(shotDelayOpt);
    cli.process(app);

    TelemetryReceiver receiver;
    if (!receiver.listen(quint16(cli.value(portOpt).toUShort()))) {
        QTextStream(stderr) << "cannot bind UDP port — is something else listening?\n";
        return 1;
    }

    TelemetryModel model(&receiver);

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
