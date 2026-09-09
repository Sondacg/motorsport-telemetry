cmake_minimum_required(VERSION 3.21)
project(telemetry_probe LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Network)

qt_standard_project_setup()

qt_add_executable(telemetry_probe
    main.cpp
    TelemetryReceiver.h
    TelemetryPacket.h
)

target_link_libraries(telemetry_probe PRIVATE Qt6::Core Qt6::Network)

# Console app: keep stdout attached on Windows instead of opening a GUI shell.
set_target_properties(telemetry_probe PROPERTIES WIN32_EXECUTABLE OFF)
