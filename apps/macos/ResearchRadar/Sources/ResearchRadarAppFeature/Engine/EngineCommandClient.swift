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

    public func readTopicKnowledge(topicID: String) async throws -> TopicKnowledgeV1 {
        let request = try EngineRequestV1(requestID: UUID(), command: .readTopicKnowledge, createdAt: clock(),
            appSupportRoot: appSupportRoot.path,
            configPath: appSupportRoot.appending(path: "config/app-config.json").path,
            payload: .readTopicKnowledge(.init(topicID: topicID)))
        guard let knowledge = try await execute(request).knowledge else {
            throw EngineJobCoordinatorError.invalidTerminalArtifact
        }
        return knowledge
    }

    public func readPaperLedger(topicID: String, reports: [LedgerReportReferenceV1]) async throws -> TopicPaperLedgerV1 {
        let request = try EngineRequestV1(requestID: UUID(), command: .readPaperLedger, createdAt: clock(),
            appSupportRoot: appSupportRoot.path,
            configPath: appSupportRoot.appending(path: "config/app-config.json").path,
            payload: .readPaperLedger(.init(topicID: topicID, reports: reports)))
        guard let ledger = try await execute(request).paperLedger else {
            throw EngineJobCoordinatorError.invalidTerminalArtifact
        }
        return ledger
    }

    public func uploadWeChatCover(data: Data, fileExtension: String, sha256: String) async throws -> WeChatCoverResultV1 {
        let requestID = UUID()
        let path = appSupportRoot.appending(path: "jobs/\(requestID.uuidString.lowercased())/cover.\(fileExtension)")
        let request = try EngineRequestV1(requestID: requestID, command: .uploadWeChatCover, createdAt: clock(),
            appSupportRoot: appSupportRoot.path,
            configPath: appSupportRoot.appending(path: "config/app-config.json").path,
            payload: .uploadWeChatCover(.init(imagePath: path.path, imageSHA256: sha256)))
        let result = try await execute(request, coverData: data)
        guard let cover = result.cover else { throw EngineJobCoordinatorError.invalidTerminalArtifact }
        return cover
    }

    private func execute(_ request: EngineRequestV1, coverData: Data? = nil) async throws -> EngineResultV1 {
        let lease = try gate.acquire()
        defer { gate.release(lease) }
        let job = appSupportRoot.appending(
            path: "jobs/\(request.requestID.uuidString.lowercased())", directoryHint: .isDirectory
        )
        let paths = try FoundationJobBuilder.create(request: request, jobDirectory: job)
        if let coverData, case .uploadWeChatCover(let payload) = request.payload {
            let image = URL(fileURLWithPath: payload.imagePath)
            guard image.deletingLastPathComponent() == job else { throw EngineProtocolError.invalidValue }
            try coverData.write(to: image, options: .withoutOverwriting)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: image.path)
        }
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
