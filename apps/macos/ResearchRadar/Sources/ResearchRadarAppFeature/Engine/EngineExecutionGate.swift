import Foundation

public enum EngineExecutionGateError: Error, Equatable, Sendable {
    case busy
    case admissionStopped
    case cancelled
    case reconciliationRequired
}

/// One shared instance admits work before either client changes durable state.
public final class EngineExecutionGate: @unchecked Sendable {
    public static let shared = EngineExecutionGate()
    private let lock = NSLock()
    private var accepting = true
    private var draining = false
    private var needsReconciliation = false
    private var lease: UUID?
    private var cancelled = false
    private var cancelling = false
    private var releaseRequested = false
    private var runner: (any EngineProcessRunning)?

    public init() {}

    public func beginDrain() -> Bool {
        lock.withLock {
            guard accepting, !draining, !needsReconciliation else { return false }
            draining = true
            return true
        }
    }

    public func endDrain() { lock.withLock { draining = false } }

    /// Call before cancelling on quit. This gate cannot be reopened.
    public func stopAdmission() { lock.withLock { accepting = false } }

    public func acquire(reconciling: Bool = false) throws -> UUID {
        try lock.withLock {
            guard accepting else { throw EngineExecutionGateError.admissionStopped }
            guard reconciling || !needsReconciliation else {
                throw EngineExecutionGateError.reconciliationRequired
            }
            guard lease == nil else { throw EngineExecutionGateError.busy }
            let id = UUID()
            lease = id
            cancelled = false
            releaseRequested = false
            return id
        }
    }

    func requireReconciliation() { lock.withLock { needsReconciliation = true } }
    func didReconcile() { lock.withLock { needsReconciliation = false } }

    public func release(_ id: UUID) {
        lock.withLock {
            guard lease == id else { return }
            guard !cancelling else { releaseRequested = true; return }
            lease = nil
            runner = nil
        }
    }

    func run(
        lease id: UUID, runner: any EngineProcessRunning,
        executable: URL, arguments: [String], eventsURL: URL
    ) async throws -> EngineProcessOutcome {
        try lock.withLock {
            guard lease == id, !cancelled, accepting else {
                throw EngineExecutionGateError.cancelled
            }
            self.runner = runner
        }
        do {
            return try await runner.run(
                executable: executable, arguments: arguments, eventsURL: eventsURL,
                shouldCancel: { [self] in
                    lock.withLock { lease != id || cancelled || !accepting }
                }
            )
        } catch {
            if let failure = error as? EngineSupervisorError, case .processGroupStillRunning = failure {
                requireReconciliation()
            }
            throw error
        }
    }

    /// Both clients may call this; only the current lease receives one cancellation.
    public func cancel() async {
        let active: (any EngineProcessRunning)? = lock.withLock {
            guard lease != nil, !cancelled else { return nil }
            cancelled = true
            cancelling = runner != nil
            return runner
        }
        guard let active else { return }
        await active.cancel()
        lock.withLock {
            cancelling = false
            if releaseRequested {
                lease = nil
                runner = nil
            }
        }
    }
}
