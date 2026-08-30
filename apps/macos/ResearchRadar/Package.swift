// swift-tools-version: 6.3

import PackageDescription

let package = Package(
    name: "ResearchRadar",
    defaultLocalization: "en",
    platforms: [.macOS("26.0")],
    products: [
        .library(name: "ResearchRadarCore", targets: ["ResearchRadarCore"]),
        .library(name: "ResearchRadarPDFCore", targets: ["ResearchRadarPDFCore"]),
        .library(name: "ResearchRadarAppFeature", targets: ["ResearchRadarAppFeature"]),
        .executable(name: "ResearchRadar", targets: ["ResearchRadarExecutable"]),
        .executable(name: "ResearchRadarPDFHelper", targets: ["ResearchRadarPDFHelper"]),
    ],
    targets: [
        .target(name: "ResearchRadarCore"),
        .target(name: "ResearchRadarPDFCore"),
        .executableTarget(
            name: "ResearchRadarPDFHelper",
            dependencies: ["ResearchRadarPDFCore"]
        ),
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
            name: "ResearchRadarPDFCoreTests",
            dependencies: ["ResearchRadarPDFCore"]
        ),
        .testTarget(
            name: "ResearchRadarPDFHelperTests",
            dependencies: ["ResearchRadarPDFHelper", "ResearchRadarPDFCore"]
        ),
        .testTarget(
            name: "ResearchRadarAppFeatureTests",
            dependencies: ["ResearchRadarAppFeature", "ResearchRadarCore"],
            resources: [.copy("Fixtures")]
        ),
    ]
)
