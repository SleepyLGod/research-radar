import Foundation
import ResearchRadarCore

/// Executes non-queued typed bridge commands through the same single engine supervisor.
public actor EngineCommandClient {
    private let runner: any EngineProcessRunning
    private let engineURL: URL
    private let appSupportRoot: URL
    private let clock: @Sendable () -> Date
    private let gate: EngineExecutionGate

    public init(
        runner: any EngineProcessRunning,
        engineURL: URL,
        appSupportRoot: URL,
        gate: EngineExecutionGate = .shared,
        clock: @escaping @Sendable () -> Date = Date.init
    ) {
        self.runner = runner; self.engineURL = engineURL
        self.appSupportRoot = appSupportRoot; self.clock = clock
        self.gate = gate
    }

    public func bootstrapTopic(
        description: String,
        language: ReportLanguageV1
    ) async throws -> TopicDraftV1 {
        let requestID = UUID()
        let request = try EngineRequestV1(
            requestID: requestID, command: .bootstrapTopic, createdAt: clock(),
            appSupportRoot: appSupportRoot.path,
            configPath: appSupportRoot.appending(path: "config/app-config.json").path,
            payload: .bootstrapTopic(BootstrapTopicPayloadV1(
                description: description, language: language
            ))
        )
        let result = try await execute(request)
        guard let draft = result.topicDraft else {
            throw EngineJobCoordinatorError.invalidTerminalArtifact
        }
        return draft
    }

    public func preflight(liveProbe: Bool) async throws -> PreflightSummaryV1 {
        let requestID = UUID()
        let request = try EngineRequestV1(
            requestID: requestID, command: .preflight, createdAt: clock(),
            appSupportRoot: appSupportRoot.path,
            configPath: appSupportRoot.appending(path: "config/app-config.json").path,
            payload: .preflight(PreflightPayloadV1(liveProbe: liveProbe))
        )
        let result = try await execute(request)
        guard let summary = result.preflight else {
            throw EngineJobCoordinatorError.invalidTerminalArtifact
        }
        return summary
    }

    public func cancel() async { await gate.cancel() }

    private func execute(_ request: EngineRequestV1) async throws -> EngineResultV1 {
        let lease = try gate.acquire()
        defer { gate.release(lease) }
        let job = appSupportRoot.appending(
            path: "jobs/\(request.requestID.uuidString.lowercased())", directoryHint: .isDirectory
        )
        let paths = try FoundationJobBuilder.create(request: request, jobDirectory: job)
        do {
            _ = try await gate.run(
                lease: lease, runner: runner,
                executable: engineURL,
                arguments: [
                    "--request", paths.request.path, "--events", paths.events.path,
                    "--result", paths.result.path, "--error", paths.error.path,
                ], eventsURL: paths.events
            )
        } catch {
            if let terminal = try? EngineTerminalResolver.resolve(
                directory: job, requestID: request.requestID, command: request.command
            ), case .success(let result) = terminal { return result }
            throw error
        }
        switch try EngineTerminalResolver.resolve(
            directory: job, requestID: request.requestID, command: request.command
        ) {
        case .success(let result): return result
        case .failure(_, let error, let stage):
            throw EngineCommandFailure(error: error, stage: stage)
        }
    }
}

public struct EngineCommandFailure: Error, Sendable {
    public let error: RedactedEngineErrorV1
    public let stage: EngineStage?
}
