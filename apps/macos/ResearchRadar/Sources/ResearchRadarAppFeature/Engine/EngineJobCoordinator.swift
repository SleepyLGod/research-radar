import Foundation
import ResearchRadarCore

public protocol EngineProcessRunning: Sendable {
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome
    func cancel() async
    func run(
        executable: URL, arguments: [String], eventsURL: URL,
        shouldCancel: @escaping @Sendable () -> Bool
    ) async throws -> EngineProcessOutcome
}

public extension EngineProcessRunning {
    func run(
        executable: URL, arguments: [String], eventsURL: URL,
        shouldCancel: @escaping @Sendable () -> Bool
    ) async throws -> EngineProcessOutcome {
        guard !shouldCancel() else { throw EngineExecutionGateError.cancelled }
        return try await run(executable: executable, arguments: arguments, eventsURL: eventsURL)
    }
}

extension EngineProcessSupervisor: EngineProcessRunning {}

public enum EngineJobCoordinatorError: Error, Equatable, Sendable {
    case invalidTerminalArtifact
    case requestMismatch
    case missingReportArtifact(String)
    case unknownTopic(String)
}

/// Stop draining and reconcile artifacts before admitting any more engine work.
public enum EnginePersistenceError: Error, Equatable, Sendable {
    case reconciliationRequired(jobID: UUID?)
}

/// Connects the durable queue to the typed engine protocol without duplicating research logic.
public actor EngineJobCoordinator {
    private let runner: any EngineProcessRunning
    private let engineURL: URL
    private let pdfHelperURL: URL?
    private let appSupportRoot: URL
    private let queue: JobQueue
    private let reports: ReportIndexStore
    private let clock: @Sendable () -> Date
    private let gate: EngineExecutionGate

    public init(
        runner: any EngineProcessRunning,
        engineURL: URL,
        appSupportRoot: URL,
        queue: JobQueue,
        reports: ReportIndexStore,
        pdfHelperURL: URL? = nil,
        gate: EngineExecutionGate = .shared,
        clock: @escaping @Sendable () -> Date = Date.init
    ) {
        self.runner = runner; self.engineURL = engineURL
        self.pdfHelperURL = pdfHelperURL
        self.appSupportRoot = appSupportRoot.standardizedFileURL
        self.queue = queue; self.reports = reports; self.clock = clock
        self.gate = gate
    }

    public func executeNext(configuration: AppConfigurationV1) async throws -> EngineResultV1? {
        let lease = try gate.acquire()
        defer { gate.release(lease) }
        let next: JobRecordV1?
        do {
            next = try await queue.nextPending()
        } catch {
            gate.requireReconciliation()
            throw EnginePersistenceError.reconciliationRequired(jobID: nil)
        }
        guard let job = next else { return nil }
        var launched = false
        let resolution: EngineTerminalResolution
        do {
            try await validateDeliveryAdmission(job)
            let request = try request(for: job, configuration: configuration)
            let paths = try FoundationJobBuilder.create(
                request: request, jobDirectory: URL(fileURLWithPath: job.jobDirectory)
            )
            var arguments = [
                "--request", paths.request.path, "--events", paths.events.path,
                "--result", paths.result.path, "--error", paths.error.path,
            ]
            if let pdfHelperURL { arguments += ["--pdf-helper", pdfHelperURL.path] }
            launched = true
            _ = try await gate.run(
                lease: lease, runner: runner,
                executable: engineURL,
                arguments: arguments,
                eventsURL: paths.events
            )
            resolution = try await resolve(job: job)
        } catch {
            // Only known setup/launch failures prove that no external effect occurred.
            if let supervisorError = error as? EngineSupervisorError,
               case .alreadyRunning = supervisorError {
                do { try await queue.releaseUnstarted(jobID: job.id) }
                catch {
                    gate.requireReconciliation()
                    throw EnginePersistenceError.reconciliationRequired(jobID: job.id)
                }
                throw EngineExecutionGateError.busy
            }
            let prelaunch = !launched || error is EngineExecutionGateError
                || (error as? EngineSupervisorError)?.isPrelaunchFailure == true
            // A runner can report cleanup failure after it wrote a valid result.
            if launched, let recovered = try? await resolve(job: job), case .success = recovered {
                try await persist(job: job, resolution: recovered)
                if case .success(let result) = recovered { return result }
            }
            let redacted = RedactedEngineErrorV1(
                code: prelaunch ? "engine_launch_failed" : "terminal_invalid",
                message: prelaunch ? "The engine could not start." : "The terminal artifact could not be confirmed.",
                retryable: job.kind == .research || prelaunch
            )
            let cancelled = error as? EngineExecutionGateError == .cancelled
            let state: JobState = cancelled ? .cancelled : prelaunch ? .failed
                : job.kind == .delivery ? .deliveryUnknown : .interrupted
            try await persist(job: job, resolution: .failure(state, redacted, nil))
            throw error
        }
        try await persist(job: job, resolution: resolution)
        switch resolution {
        case .success(let result): return result
        case .failure(_, let error, let stage): throw EngineCommandFailure(error: error, stage: stage)
        }
    }

    public func cancel() async { await gate.cancel() }

    /// Restores jobs whose engine reached a terminal artifact before the App stopped.
    public func reconcileAfterLaunch() async throws {
        let lease = try gate.acquire(reconciling: true)
        defer { gate.release(lease) }
        let active = await queue.jobs().filter {
            $0.state == .running || $0.state == .cancelling
                || $0.state == .succeeded || $0.state == .partialSuccess
                || $0.state == .interrupted || $0.state == .deliveryUnknown
        }
        for job in active {
            // Retain rejected artifacts for diagnostics without retrying them on every boot.
            if JobRecordV1.terminalStates.contains(job.state), job.error?.code == "terminal_invalid" { continue }
            let resultExists = FileManager.default.fileExists(
                atPath: URL(fileURLWithPath: job.jobDirectory).appending(path: "result.json").path
            )
            if JobRecordV1.terminalStates.contains(job.state), !resultExists { continue }
            let resolution: EngineTerminalResolution
            do {
                resolution = try await resolve(job: job)
            } catch {
                if job.state == .succeeded || job.state == .partialSuccess { continue }
                resolution = invalidTerminalResolution(job)
            }
            try await persist(job: job, resolution: resolution)
        }
        do {
            try await restoreMissingDeliveryJobs()
        } catch {
            gate.requireReconciliation()
            throw EnginePersistenceError.reconciliationRequired(jobID: nil)
        }
        gate.didReconcile()
    }

    private func resolve(job: JobRecordV1) async throws -> EngineTerminalResolution {
        let resolution = try EngineTerminalResolver.resolve(
            directory: URL(fileURLWithPath: job.jobDirectory), requestID: job.id,
            command: job.kind == .research ? .runDaily : .retryDelivery,
            runDirectory: job.runDirectory, channel: job.deliveryChannel, reportDate: job.reportDate,
            topicID: job.topicID, appSupportRoot: appSupportRoot
        )
        if case .success(let result) = resolution, let summary = result.report {
            let run = try containedDirectory(summary.runDirectory)
            try requireRegularFile(summary.articleDraftPath, inside: run)
            try requireRegularFile(summary.reportHTMLPath, inside: run)
            let existing = await reports.reports().first { $0.runDirectory == summary.runDirectory }
            if let existing, existing.topicID != job.topicID || existing.reportDate != summary.reportDate {
                throw EngineJobCoordinatorError.requestMismatch
            }
        }
        return resolution
    }

    private func invalidTerminalResolution(_ job: JobRecordV1) -> EngineTerminalResolution {
        .failure(
            job.kind == .delivery ? .deliveryUnknown : .interrupted,
            RedactedEngineErrorV1(
                code: "terminal_invalid", message: "The terminal artifact could not be confirmed.",
                retryable: job.kind == .research
            ), job.stage
        )
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

    private func validateDeliveryAdmission(_ job: JobRecordV1) async throws {
        guard job.kind == .delivery else { return }
        guard let report = await reports.reports().first(where: { $0.runDirectory == job.runDirectory }),
              report.topicID == job.topicID, report.reportDate == job.reportDate,
              let delivery = report.deliveries.first(where: { $0.channel == job.deliveryChannel }) else {
            throw EngineJobCoordinatorError.requestMismatch
        }
        if delivery.state == .unknown && !job.acknowledgeUnknownOutcome {
            throw JobRecordError.unknownDeliveryRequiresAcknowledgement
        }
        if (delivery.state == .sent || delivery.state == .created) && !job.allowResend {
            throw JobRecordError.successfulDeliveryRequiresResend
        }
    }

    private func persist(job: JobRecordV1, resolution: EngineTerminalResolution) async throws {
        do {
            switch resolution {
            case .success(let result): try await complete(job: job, result: result)
            case .failure(let state, let error, let stage):
                guard job.state != .succeeded && job.state != .partialSuccess else { return }
                if let channel = job.deliveryChannel, let runDirectory = job.runDirectory {
                    let prior = await reports.reports().first { $0.runDirectory == runDirectory }?
                        .deliveries.first { $0.channel == channel }
                    let protectsPreviousSuccess = (prior?.state == .created || prior?.state == .sent) && !job.allowResend
                    let protectsPreviousUnknown = prior?.state == .unknown && !job.acknowledgeUnknownOutcome
                    if await isLatestDeliveryAttempt(job), !protectsPreviousSuccess, !protectsPreviousUnknown {
                        try await reports.updateDelivery(
                            runDirectory: runDirectory, channel: channel,
                            state: state == .deliveryUnknown ? .unknown : .failed,
                            error: error, at: clock()
                        )
                    }
                }
                try await queue.transition(jobID: job.id, to: state, stage: stage, error: error)
            }
        } catch {
            gate.requireReconciliation()
            throw EnginePersistenceError.reconciliationRequired(jobID: job.id)
        }
    }

    private func isLatestDeliveryAttempt(_ job: JobRecordV1) async -> Bool {
        let latest = await queue.jobs().filter {
            $0.kind == .delivery && $0.runDirectory == job.runDirectory && $0.deliveryChannel == job.deliveryChannel
        }.max {
            if $0.attemptCount != $1.attemptCount { return $0.attemptCount < $1.attemptCount }
            if $0.createdAt != $1.createdAt { return $0.createdAt < $1.createdAt }
            return $0.id.uuidString < $1.id.uuidString
        }
        return latest?.id == job.id
    }

    private func restoreMissingDeliveryJobs() async throws {
        let existingJobs = await queue.jobs()
        for report in await reports.reports() {
            for delivery in report.deliveries where delivery.state == .pending {
                let alreadyRecorded = existingJobs.contains {
                    $0.kind == .delivery
                        && $0.runDirectory == report.runDirectory
                        && $0.deliveryChannel == delivery.channel
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

    private func complete(
        job: JobRecordV1,
        result: EngineResultV1
    ) async throws {
        if job.kind == .research {
            guard let summary = result.report else {
                throw EngineJobCoordinatorError.invalidTerminalArtifact
            }
            let existing = await reports.reports().first { $0.runDirectory == summary.runDirectory }
            var deliveryRecords = existing?.deliveries ?? []
            for channel in job.requestedDeliveryChannels where !deliveryRecords.contains(where: { $0.channel == channel }) {
                deliveryRecords.append(DeliveryRecordV1(channel: channel, state: .pending))
            }
            let report = ReportRecordV1(
                id: existing?.id ?? job.id,
                topicID: job.topicID, reportDate: summary.reportDate,
                runDirectory: summary.runDirectory, articleDraftPath: summary.articleDraftPath,
                reportHTMLPath: summary.reportHTMLPath, title: summary.title,
                summary: summary.summary, sourceCount: summary.sourceCount,
                deepReadCount: summary.deepReadCount,
                publishableClaimCount: summary.publishableClaimCount,
                deliveries: deliveryRecords, createdAt: result.completedAt
            )
            try await reports.upsert(report)
            try await queue.transition(
                jobID: job.id, to: result.status == .partialSuccess ? .partialSuccess : .succeeded,
                stage: .complete
            )
            try await restoreMissingDeliveryJobs()
        } else {
            guard let delivery = result.delivery else {
                throw EngineJobCoordinatorError.invalidTerminalArtifact
            }
            let state: DeliveryState = delivery.status == .created ? .created : .sent
            if await isLatestDeliveryAttempt(job) {
                try await reports.updateDelivery(
                    runDirectory: delivery.runDirectory, channel: delivery.channel,
                    state: state, error: nil, at: delivery.completedAt
                )
            }
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
