// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "VMRunner",
    platforms: [.macOS("26.0")],
    products: [
        .library(name: "VMRunnerCore", targets: ["VMRunnerCore"]),
        .executable(name: "VMRunner", targets: ["VMRunner"]),
        .library(name: "VMInstallerCore", targets: ["VMInstallerCore"]),
        .executable(name: "VMInstaller", targets: ["VMInstaller"]),
    ],
    targets: [
        .target(name: "VMRunnerCore"),
        .executableTarget(name: "VMRunner", dependencies: ["VMRunnerCore"]),
        .target(name: "VMInstallerCore", dependencies: ["VMRunnerCore"]),
        .executableTarget(
            name: "VMInstaller",
            dependencies: ["VMInstallerCore", "VMRunnerCore"]
        ),
        .testTarget(name: "VMRunnerCoreTests", dependencies: ["VMRunnerCore"]),
        .testTarget(
            name: "VMInstallerCoreTests",
            dependencies: ["VMInstallerCore"]
        ),
    ]
)
