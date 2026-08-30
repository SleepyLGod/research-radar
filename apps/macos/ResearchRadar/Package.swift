// swift-tools-version: 6.3

import PackageDescription

let package = Package(
    name: "ResearchRadar",
    defaultLocalization: "en",
    platforms: [.macOS("26.0")],
    products: [
        .library(name: "ResearchRadarCore", targets: ["ResearchRadarCore"]),
        .library(name: "ResearchRadarAppFeature", targets: ["ResearchRadarAppFeature"]),
        .executable(name: "ResearchRadar", targets: ["ResearchRadarExecutable"]),
    ],
    targets: [
        .target(name: "ResearchRadarCore"),
        .target(
            name: "ResearchRadarAppFeature",
            dependencies: ["ResearchRadarCore"],
            resources: [.process("Resources")]
        ),
        .executableTarget(
            name: "ResearchRadarExecutable",
            dependencies: ["ResearchRadarAppFeature"]
        ),
        .testTarget(
            name: "ResearchRadarCoreTests",
            dependencies: ["ResearchRadarCore"]
        ),
        .testTarget(
            name: "ResearchRadarAppFeatureTests",
            dependencies: ["ResearchRadarAppFeature", "ResearchRadarCore"],
            resources: [.copy("Fixtures")]
        ),
    ]
)
