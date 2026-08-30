import Foundation
import ResearchRadarCore

public enum AppBootstrapError: Error, Sendable {
    case invalidRoot
}

/// Loads the App's typed durable state, creating only missing first-run files.
public struct AppBootstrapService: Sendable {
    private let appSupportRoot: URL

    public init(appSupportRoot: URL) { self.appSupportRoot = appSupportRoot.standardizedFileURL }

    @MainActor
    public func load(engineURL: URL) throws -> AppStore {
        try prepareRoot()
        let store = AtomicJSONStore(root: appSupportRoot)
        let configPath = "config/app-config.json"
        let configuration: AppConfigurationV1
        if exists(configPath) {
            configuration = try store.read(AppConfigurationV1.self, from: configPath)
        } else {
            let codex = CodexExecutableResolver().resolve(
                savedPath: nil,
                environmentPath: ProcessInfo.processInfo.environment["PATH"],
                homeDirectory: FileManager.default.homeDirectoryForCurrentUser
            )
            configuration = AppConfigurationDefaults.make(
                workspaceRoot: appSupportRoot.appending(path: "workspace"),
                codexExecutable: codex
            )
            try store.write(configuration, to: configPath)
        }
        let runtime: AppRuntimeStateV1 = try loadOrCreate(
            AppRuntimeStateV1.self, path: "state/app-state.json", store: store,
            fallback: AppRuntimeStateV1(updatedAt: Date())
        )
        let queue: JobQueueSnapshotV1 = try loadOrCreate(
            JobQueueSnapshotV1.self, path: "state/queue.json", store: store,
            fallback: JobQueueSnapshotV1()
        )
        let schedules: ScheduleSnapshotV1 = try loadOrCreate(
            ScheduleSnapshotV1.self, path: "state/schedules.json", store: store,
            fallback: ScheduleSnapshotV1()
        )
        let reports: ReportIndexV1 = try loadOrCreate(
            ReportIndexV1.self, path: "state/report-index.json", store: store,
            fallback: ReportIndexV1()
        )
        let launchAgents = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/LaunchAgents", directoryHint: .isDirectory)
        let legacyScheduleTopics = (try? LegacyStateMigrationService().legacyScheduleTopics(
            launchAgentsDirectory: launchAgents
        )) ?? []
        return AppStore(
            configuration: configuration, queueSnapshot: queue,
            scheduleSnapshot: schedules, reportSnapshot: reports, runtime: runtime,
            appSupportRoot: appSupportRoot, engineURL: engineURL,
            legacyScheduleTopics: legacyScheduleTopics
        )
    }

    private func loadOrCreate<T: Codable & Sendable>(
        _ type: T.Type, path: String, store: AtomicJSONStore, fallback: T
    ) throws -> T {
        if exists(path) { return try store.read(type, from: path) }
        try store.write(fallback, to: path)
        return fallback
    }

    private func exists(_ relativePath: String) -> Bool {
        FileManager.default.fileExists(atPath: appSupportRoot.appending(path: relativePath).path)
    }

    private func prepareRoot() throws {
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: appSupportRoot.path, isDirectory: &isDirectory) {
            guard isDirectory.boolValue else { throw AppBootstrapError.invalidRoot }
        } else {
            try FileManager.default.createDirectory(
                at: appSupportRoot, withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
        }
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: appSupportRoot.path)
    }
}
