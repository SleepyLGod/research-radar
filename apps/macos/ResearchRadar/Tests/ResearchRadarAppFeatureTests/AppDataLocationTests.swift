import Foundation
import Testing
@testable import ResearchRadarAppFeature

@Suite struct AppDataLocationTests {
    @Test func developmentProbeCanUseAnExplicitTemporaryRoot() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "radar-root-probe")
        #expect(try AppDataLocation.root(environment: ["RESEARCH_RADAR_DEV_ROOT": root.path]).path == root.path)
        #expect(throws: CocoaError.self) {
            _ = try AppDataLocation.root(environment: ["RESEARCH_RADAR_DEV_ROOT": "relative"])
        }
    }
    @Test func developmentIsTheSafeDefaultAndProductionIsExplicit() {
        #expect(AppDataLocation.directoryName(developmentBuild: nil) == "ResearchRadar-Dev")
        #expect(AppDataLocation.directoryName(developmentBuild: true) == "ResearchRadar-Dev")
        #expect(AppDataLocation.directoryName(developmentBuild: false) == "ResearchRadar")
    }
}
