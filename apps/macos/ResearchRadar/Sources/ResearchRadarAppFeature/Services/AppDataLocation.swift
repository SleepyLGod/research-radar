import Foundation

/// Keeps local development data separate from an explicitly assembled production App.
public enum AppDataLocation {
    public static func directoryName(developmentBuild: Bool?) -> String {
        developmentBuild == false ? "ResearchRadar" : "ResearchRadar-Dev"
    }

    public static func isDevelopment(bundle: Bundle = .main) -> Bool {
        (bundle.object(forInfoDictionaryKey: "ResearchRadarDevelopmentBuild") as? Bool) != false
    }

    public static func root(
        bundle: Bundle = .main,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws -> URL {
        if isDevelopment(bundle: bundle), let path = environment["RESEARCH_RADAR_DEV_ROOT"] {
            guard path.hasPrefix("/"), path != "/" else {
                throw CocoaError(.fileReadInvalidFileName)
            }
            return URL(fileURLWithPath: path, isDirectory: true).standardizedFileURL
        }
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: false
        )
        return base.appending(
            path: directoryName(developmentBuild: isDevelopment(bundle: bundle)),
            directoryHint: .isDirectory
        )
    }
}
