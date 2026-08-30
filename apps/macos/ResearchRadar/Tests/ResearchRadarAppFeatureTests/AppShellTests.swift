import AppKit
import Foundation
import SwiftUI
import Testing
@testable import ResearchRadarAppFeature

@MainActor
@Suite struct AppShellTests {
    @Test func windowCoordinatorReusesOneWindow() {
        let coordinator = WindowCoordinator {
            AnyView(Text("ResearchRadar"))
        }

        let first = coordinator.window
        coordinator.show()
        coordinator.show()

        #expect(coordinator.window === first)
    }

    @Test func foundationJobBuilderWritesPrivateExactRequest() throws {
        let root = packageBuildRoot().appending(
            path: "job-builder-\(UUID().uuidString)",
            directoryHint: .isDirectory
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let job = try FoundationJobBuilder.create(appSupportRoot: root)

        let attributes = try FileManager.default.attributesOfItem(atPath: job.jobDirectory.path)
        let permissions = try #require(attributes[.posixPermissions] as? NSNumber)
        #expect(permissions.intValue == 0o700)
        let requestAttributes = try FileManager.default.attributesOfItem(atPath: job.request.path)
        let requestPermissions = try #require(requestAttributes[.posixPermissions] as? NSNumber)
        #expect(requestPermissions.intValue == 0o600)

        let object = try #require(
            JSONSerialization.jsonObject(with: Data(contentsOf: job.request)) as? [String: Any]
        )
        #expect(object["command"] as? String == "preflight")
        #expect(object["request_id"] as? String == job.jobDirectory.lastPathComponent)
    }
}

private func packageBuildRoot() -> URL {
    URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appending(path: ".build/test-data", directoryHint: .isDirectory)
}
