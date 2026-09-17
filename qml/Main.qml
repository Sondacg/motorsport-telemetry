import QtQuick
import QtQuick.Window

Window {
    id: root
    width: 1100
    height: 400
    minimumWidth: 760
    minimumHeight: 340
    visible: true
    title: "Telemetry Dash"
    color: theme.bg

    // A driver display is read at 300 km/h through a helmet visor. It commits
    // to one dark, high-contrast look on purpose — there is no light mode on
    // a steering wheel.
    QtObject {
        id: theme
        readonly property color bg:      "#080B0D"
        readonly property color panel:   "#10161A"
        readonly property color edge:    "#1E2A31"
        readonly property color text:    "#E9EFF2"
        readonly property color muted:   "#5E727C"
        readonly property color green:   "#39D07A"
        readonly property color amber:   "#F0A73A"
        readonly property color red:     "#E2452F"
        readonly property color shift:   "#5AB4FF"
    }

    readonly property real revFrac: telemetry.revLimit > 0
                                    ? Math.min(1, telemetry.rpm / telemetry.revLimit) : 0
    readonly property bool atLimit: revFrac > 0.985

    // Smoothing exists because the link drops packets. Without it every lost
    // frame is a visible stutter; 70 ms is short enough that the reading is
    // still honest and long enough to hide a gap at 60 Hz.
    property real smoothSpeed: telemetry.speedKph
    property real smoothRev: revFrac
    Behavior on smoothSpeed { NumberAnimation { duration: 70 } }
    Behavior on smoothRev   { NumberAnimation { duration: 70 } }

    // ── shift lights ──────────────────────────────────────────────────────
    Row {
        id: revBar
        anchors { top: parent.top; left: parent.left; right: parent.right; margins: 14 }
        height: 26
        spacing: 4

        Repeater {
            model: 20
            Rectangle {
                width: (revBar.width - 19 * revBar.spacing) / 20
                height: revBar.height
                radius: 3

                readonly property real threshold: (index + 1) / 20
                readonly property bool lit: root.smoothRev >= threshold
                readonly property color tone: index < 10 ? theme.green
                                            : index < 16 ? theme.amber
                                                         : theme.red

                color: root.atLimit && blink.on ? theme.shift
                     : lit ? tone
                     : theme.panel
                border.width: 1
                border.color: lit || root.atLimit ? "transparent" : theme.edge
            }
        }
    }

    QtObject {
        id: blink
        property bool on: false
    }
    Timer {
        interval: 60; running: root.atLimit; repeat: true
        onTriggered: blink.on = !blink.on
        onRunningChanged: if (!running) blink.on = false
    }

    // ── main readouts ─────────────────────────────────────────────────────
    Item {
        id: main
        anchors { top: revBar.bottom; left: parent.left; right: parent.right
                  bottom: pedals.top; leftMargin: 14; rightMargin: 14
                  topMargin: 2; bottomMargin: 6 }

        // speed
        Column {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            width: parent.width * 0.3
            spacing: -6

            Text {
                text: Math.round(root.smoothSpeed)
                font { pixelSize: Math.min(root.height * 0.30, 128); bold: true
                       family: "Segoe UI"; letterSpacing: -2 }
                color: telemetry.live ? theme.text : theme.muted
            }
            Text {
                text: "km/h"
                font { pixelSize: 16; family: "Consolas"; letterSpacing: 1 }
                color: theme.muted
            }
        }

        // gear
        Text {
            anchors.centerIn: parent
            text: telemetry.gear > 0 ? telemetry.gear : (telemetry.gear === 0 ? "N" : "R")
            font { pixelSize: Math.min(root.height * 0.52, 210); bold: true
                   family: "Segoe UI" }
            color: root.atLimit ? theme.shift
                                : (telemetry.live ? theme.text : theme.muted)
        }

        // rpm and DRS
        Column {
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            spacing: 10

            Text {
                anchors.right: parent.right
                text: Math.round(telemetry.rpm)
                font { pixelSize: Math.min(root.height * 0.19, 74); bold: true
                       family: "Consolas" }
                color: root.atLimit ? theme.red : theme.text
            }
            Text {
                anchors.right: parent.right
                text: "rpm"
                font { pixelSize: 16; family: "Consolas"; letterSpacing: 1 }
                color: theme.muted
            }
            Rectangle {
                anchors.right: parent.right
                width: 76; height: 28; radius: 4
                color: telemetry.drs ? theme.green : "transparent"
                border.width: 1
                border.color: telemetry.drs ? theme.green : theme.edge
                Text {
                    anchors.centerIn: parent
                    text: "DRS"
                    font { pixelSize: 15; bold: true; family: "Consolas"; letterSpacing: 1 }
                    color: telemetry.drs ? theme.bg : theme.edge
                }
            }
        }
    }

    // ── pedals ────────────────────────────────────────────────────────────
    Row {
        id: pedals
        anchors { left: parent.left; right: parent.right; bottom: strip.top
                  leftMargin: 14; rightMargin: 14; bottomMargin: 12 }
        height: 22
        spacing: 16

        component PedalBar: Item {
            required property string label
            required property real value
            required property color tone
            width: (pedals.width - pedals.spacing) / 2
            height: pedals.height

            Text {
                id: tag
                anchors.verticalCenter: parent.verticalCenter
                width: 44
                text: parent.label
                font { pixelSize: 14; bold: true; family: "Consolas"; letterSpacing: 1 }
                color: theme.muted
            }
            Rectangle {
                anchors { left: tag.right; right: parent.right
                          verticalCenter: parent.verticalCenter }
                height: 12
                radius: 2
                color: theme.panel
                border.width: 1
                border.color: theme.edge

                Rectangle {
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom
                              margins: 1 }
                    width: Math.max(0, (parent.width - 2) * Math.min(1, parent.parent.value))
                    radius: 1
                    color: parent.parent.tone
                }
            }
        }

        PedalBar { label: "THR"; value: telemetry.throttle; tone: theme.green }
        PedalBar { label: "BRK"; value: telemetry.brake;    tone: theme.red }
    }

    // ── status strip ──────────────────────────────────────────────────────
    Rectangle {
        id: strip
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 38
        color: theme.panel
        border.width: 0

        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 1
            color: theme.edge
        }

        Row {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter
                      leftMargin: 14 }
            spacing: 22

            Text {
                text: "LAP " + telemetry.lapNumber
                font { pixelSize: 14; family: "Consolas"; letterSpacing: 1 }
                color: theme.text
            }
            Text {
                text: Math.round(telemetry.lapDistanceM) + " m"
                font { pixelSize: 14; family: "Consolas" }
                color: theme.muted
            }
            Row {
                spacing: 7
                Text {
                    text: "SLIP"
                    font { pixelSize: 14; family: "Consolas"; letterSpacing: 1 }
                    color: theme.muted
                }
                Repeater {
                    model: telemetry.wheelSlipRatio
                    Text {
                        required property var modelData
                        // Positive is a wheel spinning up, negative is one
                        // locking. Both matter, so the sign is kept.
                        text: (modelData >= 0 ? "+" : "") + (modelData * 100).toFixed(0)
                        font { pixelSize: 14; family: "Consolas" }
                        color: Math.abs(modelData) > 0.08 ? theme.amber : theme.text
                    }
                }
            }
        }

        // Link health. Deliberately plain and in the corner: it matters when
        // it is wrong, and should not compete with the car when it is right.
        Row {
            anchors { right: parent.right; verticalCenter: parent.verticalCenter
                      rightMargin: 14 }
            spacing: 16

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 8; height: 8; radius: 4
                color: telemetry.live ? theme.green : theme.red
            }
            Text {
                text: telemetry.live ? telemetry.packetsPerSec.toFixed(0) + " pkt/s" : "NO SIGNAL"
                font { pixelSize: 14; family: "Consolas" }
                color: telemetry.live ? theme.muted : theme.red
            }
            Text {
                visible: telemetry.linkStatsValid
                text: "rx " + telemetry.received
                font { pixelSize: 14; family: "Consolas" }
                color: theme.muted
            }
            Text {
                visible: telemetry.linkStatsValid
                text: "lost " + telemetry.lost
                font { pixelSize: 14; family: "Consolas" }
                color: telemetry.lost > 0 ? theme.amber : theme.muted
            }
            Text {
                visible: telemetry.linkStatsValid
                text: "ooo " + telemetry.outOfOrder
                font { pixelSize: 14; family: "Consolas" }
                color: theme.muted
            }
            Text {
                visible: telemetry.linkStatsValid
                text: "bad " + telemetry.rejected
                font { pixelSize: 14; family: "Consolas" }
                color: telemetry.rejected > 0 ? theme.red : theme.muted
            }
        }
    }

    // Waiting state, so a blank window is never mistaken for a broken one.
    Text {
        anchors.centerIn: parent
        visible: telemetry.received === 0
        text: "waiting for telemetry on udp/20777\nrun tools/sim_telemetry.py"
        horizontalAlignment: Text.AlignHCenter
        font { pixelSize: 17; family: "Consolas" }
        color: theme.muted
    }
}
