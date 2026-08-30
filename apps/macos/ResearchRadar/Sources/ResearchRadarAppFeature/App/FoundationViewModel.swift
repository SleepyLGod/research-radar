import Foundation
import Observation
import ResearchRadarCore

public enum FoundationPreflightState: Equatable, Sendable {
    case ready
    case running
    case succeeded
    case failed(String)
}

@MainActor
@Observable
public final class FoundationViewModel {
    public private(set) var state: FoundationPreflightState = .ready
    private let supervisor: EngineProcessSupervisor
    private let engineURL: URL
    private var runTask: Task<Void, Never>?

    public init(
        supervisor: EngineProcessSupervisor = EngineProcessSupervisor(),
        engineURL: URL = EngineLocation.bundledFoundationEngine()
    ) {
        self.supervisor = supervisor
        self.engineURL = engineURL
    }

    public var isRunning: Bool {
        if case .running = state { return true }
        return false
    }

    public func runPreflight() {
        guard !isRunning else { return }
        state = .running
        runTask = Task { [weak self] in
            guard let self else { return }
            do {
                let paths = try FoundationJobBuilder.create(
                    appSupportRoot: FoundationJobBuilder.developmentRoot()
                )
                let outcome = try await supervisor.run(
                    executable: engineURL,
                    arguments: [
                        "--request", paths.request.path,
                        "--events", paths.events.path,
                        "--result", paths.result.path,
                        "--error", paths.error.path,
                    ],
                    eventsURL: paths.events
                )
                finish(outcome: outcome, paths: paths)
            } catch EngineSupervisorError.executableMissing {
                state = .failed("engine_missing")
            } catch EngineSupervisorError.alreadyRunning {
                state = .failed("engine_busy")
            } catch {
                state = .failed("engine_crashed")
            }
        }
    }

    public func cancel() async {
        guard isRunning else { return }
        await supervisor.cancel()
        _ = await runTask?.result
    }

    private func finish(outcome: EngineProcessOutcome, paths: FoundationJobPaths) {
        if outcome.exitCode == 0,
           let data = try? Data(contentsOf: paths.result),
           let result = try? EngineProtocolCodec.decodeResult(data),
           result.command == .preflight,
           let preflight = result.preflight
        {
            state = preflight.ready ? .succeeded : .failed("preflight_not_ready")
            return
        }
        if let data = try? Data(contentsOf: paths.error),
           let error = try? EngineProtocolCodec.decodeError(data)
        {
            state = .failed(error.code)
            return
        }
        state = .failed("engine_crashed")
    }
}

public enum EngineLocation {
    public static func bundledFoundationEngine(bundle: Bundle = .main) -> URL {
        bundle.bundleURL
            .appending(path: "Contents/Helpers/ResearchRadarEngine.app", directoryHint: .isDirectory)
            .appending(path: "Contents/MacOS", directoryHint: .isDirectory)
            .appending(path: "research-radar-engine")
    }
}
