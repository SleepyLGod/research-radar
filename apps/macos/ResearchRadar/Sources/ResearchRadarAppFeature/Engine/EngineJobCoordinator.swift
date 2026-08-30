import Foundation
import ResearchRadarCore

public protocol EngineProcessRunning: Sendable {
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome
    func cancel() async
}

extension EngineProcessSupervisor: EngineProcessRunning {}

public enum EngineJobCoordinatorError: Error, Equatable, Sendable {
    case invalidTerminalArtifact
    case requestMismatch
    case missingReportArtifact(String)
    case unknownTopic(String)
}

/// Connects the durable queue to the typed engine protocol without duplicating research logic.
public actor EngineJobCoordinator {
    private let runner: any EngineProcessRunning
    private let engineURL: URL
    private let appSupportRoot: URL
    private let queue: JobQueue
    private let reports: ReportIndexStore
    private let clock: @Sendable () -> Date

    public init(
        runner: any EngineProcessRunning,
        engineURL: URL,
        appSupportRoot: URL,
        queue: JobQueue,
        reports: ReportIndexStore,
        clock: @escaping @Sendable () -> Date = Date.init
    ) {
        self.runner = runner; self.engineURL = engineURL
        self.appSupportRoot = appSupportRoot.standardizedFileURL
        self.queue = queue; self.reports = reports; self.clock = clock
    }

    public func executeNext(configuration: AppConfigurationV1) async throws -> EngineResultV1? {
        guard let job = try await queue.nextPending() else { return nil }
        do {
            let request = try request(for: job, configuration: configuration)
            let paths = try FoundationJobBuilder.create(
                request: request, jobDirectory: URL(fileURLWithPath: job.jobDirectory)
            )
            let outcome = try await runner.run(
                executable: engineURL,
                arguments: [
                    "--request", paths.request.path, "--events", paths.events.path,
                    "--result", paths.result.path, "--error", paths.error.path,
                ],
                eventsURL: paths.events
            )
            let result = try terminalResult(outcome: outcome, paths: paths, requestID: job.id)
            try await complete(
                job: job,
                result: result
            )
            return result
        } catch {
            let redacted = RedactedEngineErrorV1(
                code: "engine_failed", message: "The engine job did not complete.", retryable: true
            )
            try? await queue.transition(jobID: job.id, to: .failed, error: redacted)
            if let channel = job.deliveryChannel, let runDirectory = job.runDirectory {
                try? await reports.updateDelivery(
                    runDirectory: runDirectory, channel: channel, state: .failed,
                    error: redacted, at: clock()
                )
            }
            throw error
        }
    }

    public func cancel() async { await runner.cancel() }

    /// Restores jobs whose engine reached a terminal artifact before the App stopped.
    public func reconcileAfterLaunch() async throws {
        let active = await queue.jobs().filter {
            $0.state == .running || $0.state == .cancelling
        }
        for job in active {
            do {
                let directory = URL(fileURLWithPath: job.jobDirectory)
                let resultURL = directory.appending(path: "result.json")
                if FileManager.default.fileExists(atPath: resultURL.path) {
                    let result = try EngineProtocolCodec.decodeResult(Data(contentsOf: resultURL))
                    guard result.requestID == job.id else {
                        throw EngineJobCoordinatorError.requestMismatch
                    }
                    try await complete(job: job, result: result)
                    continue
                }

                let errorURL = directory.appending(path: "error.json")
                if FileManager.default.fileExists(atPath: errorURL.path) {
                    let error = try EngineProtocolCodec.decodeError(Data(contentsOf: errorURL))
                    guard error.requestID == job.id else {
                        throw EngineJobCoordinatorError.requestMismatch
                    }
                    if error.code == "cancelled", job.kind == .research {
                        try await queue.transition(jobID: job.id, to: .cancelled)
                    } else {
                        try await markInterrupted(job)
                    }
                } else {
                    try await markInterrupted(job)
                }
            } catch {
                try? await markInterrupted(job)
            }
        }
        try await restoreMissingDeliveryJobs()
    }

    private func request(for job: JobRecordV1, configuration: AppConfigurationV1) throws -> EngineRequestV1 {
        let config = appSupportRoot.appending(path: "config/app-config.json")
        let payload: EnginePayloadV1
        let command: EngineCommand
        switch job.kind {
        case .research:
            guard let topic = configuration.topics.first(where: { $0.id == job.topicID }) else {
                throw EngineJobCoordinatorError.unknownTopic(job.topicID)
            }
            command = .runDaily
            payload = .runDaily(RunDailyPayloadV1(
                topicID: job.topicID, reportDate: job.reportDate,
                limit: topic.sourceLimit, deepLimit: topic.deepReadLimit,
                language: topic.reportLanguage, modelCache: topic.modelCacheEnabled,
                modelCacheLimitBytes: configuration.storage.modelCacheLimitBytes.flatMap(Int.init(exactly:))
            ))
        case .delivery:
            command = .retryDelivery
            guard let channel = job.deliveryChannel, let runDirectory = job.runDirectory else {
                throw EngineJobCoordinatorError.invalidTerminalArtifact
            }
            payload = .retryDelivery(RetryDeliveryPayloadV1(
                runDirectory: runDirectory, channel: channel, allowResend: job.allowResend,
                acknowledgeUnknownOutcome: job.acknowledgeUnknownOutcome
            ))
        }
        return try EngineRequestV1(
            requestID: job.id, command: command, createdAt: clock(),
            appSupportRoot: appSupportRoot.path, configPath: config.path, payload: payload
        )
    }

    private func markInterrupted(_ job: JobRecordV1) async throws {
        let state: JobState = job.kind == .delivery ? .deliveryUnknown : .interrupted
        try await queue.transition(jobID: job.id, to: state)
        if let channel = job.deliveryChannel, let runDirectory = job.runDirectory {
            try await reports.updateDelivery(
                runDirectory: runDirectory,
                channel: channel,
                state: .unknown,
                error: RedactedEngineErrorV1(
                    code: "delivery_interrupted",
                    message: "The delivery result is unknown.",
                    retryable: false
                ),
                at: clock()
            )
        }
    }

    private func restoreMissingDeliveryJobs() async throws {
        let existingJobs = await queue.jobs()
        for report in await reports.reports() {
            for delivery in report.deliveries where delivery.state == .pending {
                let alreadyRecorded = existingJobs.contains {
                    $0.kind == .delivery
                        && $0.runDirectory == report.runDirectory
                        && $0.deliveryChannel == delivery.channel
                        && !JobRecordV1.terminalStates.contains($0.state)
                }
                if !alreadyRecorded {
                    _ = try await queue.enqueueDelivery(
                        runDirectory: URL(fileURLWithPath: report.runDirectory),
                        topicID: report.topicID,
                        reportDate: report.reportDate,
                        channel: delivery.channel,
                        trigger: .schedule
                    )
                }
            }
        }
    }

    private func terminalResult(
        outcome: EngineProcessOutcome,
        paths: FoundationJobPaths,
        requestID: UUID
    ) throws -> EngineResultV1 {
        guard outcome.exitCode == 0,
              let data = try? Data(contentsOf: paths.result),
              let result = try? EngineProtocolCodec.decodeResult(data)
        else { throw EngineJobCoordinatorError.invalidTerminalArtifact }
        guard result.requestID == requestID else { throw EngineJobCoordinatorError.requestMismatch }
        return result
    }

    private func complete(
        job: JobRecordV1,
        result: EngineResultV1
    ) async throws {
        if job.kind == .research {
            guard let summary = result.report else {
                throw EngineJobCoordinatorError.invalidTerminalArtifact
            }
            let run = try containedDirectory(summary.runDirectory)
            try requireRegularFile(summary.articleDraftPath, inside: run)
            try requireRegularFile(summary.reportHTMLPath, inside: run)
            let deliveryRecords = job.requestedDeliveryChannels.map {
                DeliveryRecordV1(channel: $0, state: .pending)
            }
            let report = ReportRecordV1(
                topicID: job.topicID, reportDate: summary.reportDate,
                runDirectory: summary.runDirectory, articleDraftPath: summary.articleDraftPath,
                reportHTMLPath: summary.reportHTMLPath, title: summary.title,
                summary: summary.summary, sourceCount: summary.sourceCount,
                deepReadCount: summary.deepReadCount,
                publishableClaimCount: summary.publishableClaimCount,
                deliveries: deliveryRecords, createdAt: result.completedAt
            )
            try await reports.upsert(report)
            try await queue.transition(jobID: job.id, to: .succeeded, stage: .complete)
            for channel in job.requestedDeliveryChannels {
                _ = try await queue.enqueueDelivery(
                    runDirectory: run, topicID: job.topicID, reportDate: job.reportDate,
                    channel: channel, trigger: .schedule
                )
            }
        } else {
            guard let delivery = result.delivery else {
                throw EngineJobCoordinatorError.invalidTerminalArtifact
            }
            let state: DeliveryState = delivery.status == .created ? .created : .sent
            try await reports.updateDelivery(
                runDirectory: delivery.runDirectory, channel: delivery.channel,
                state: state, error: nil, at: delivery.completedAt
            )
            try await queue.transition(jobID: job.id, to: .succeeded, stage: .complete)
        }
    }

    private func containedDirectory(_ path: String) throws -> URL {
        let workspace = appSupportRoot.appending(path: "workspace", directoryHint: .isDirectory)
            .resolvingSymlinksInPath().standardizedFileURL
        let directory = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL
        guard directory.path.hasPrefix(workspace.path + "/") else {
            throw EngineJobCoordinatorError.missingReportArtifact(path)
        }
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDirectory),
              isDirectory.boolValue
        else { throw EngineJobCoordinatorError.missingReportArtifact(path) }
        return directory
    }

    private func requireRegularFile(_ path: String, inside directory: URL) throws {
        let file = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL
        guard file.path.hasPrefix(directory.path + "/"),
              let type = try? FileManager.default.attributesOfItem(atPath: file.path)[.type] as? FileAttributeType,
              type == .typeRegular
        else { throw EngineJobCoordinatorError.missingReportArtifact(path) }
    }
}
