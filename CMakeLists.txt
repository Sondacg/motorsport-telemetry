cmake_minimum_required(VERSION 3.21)
project(telemetry LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Network Gui Quick)

qt_standard_project_setup(REQUIRES 6.5)

# Console probe — the debugging tool. Prints the stream as text, no GUI.
qt_add_executable(telemetry_probe
    main.cpp
    TelemetryReceiver.h
    TelemetryPacket.h
)
target_link_libraries(telemetry_probe PRIVATE Qt6::Core Qt6::Network)
set_target_properties(telemetry_probe PROPERTIES WIN32_EXECUTABLE OFF)

# Driver display.
qt_add_executable(telemetry_dash
    main_dash.cpp
    TelemetryModel.h
    TelemetryReceiver.h
    TelemetryPacket.h
)
qt_add_qml_module(telemetry_dash
    URI Dash
    VERSION 1.0
    QML_FILES qml/Main.qml
)
target_link_libraries(telemetry_dash PRIVATE Qt6::Core Qt6::Network Qt6::Gui Qt6::Quick)
