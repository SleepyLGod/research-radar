import Foundation
import ResearchRadarCore

/// A per-attempt observer. Its owner must stop it before resolving terminal artifacts.
public actor EngineEventObserver {
    private let eventsURL: URL
    private let requestID: UUID
    private var offset: UInt64 = 0
    private var partial = Data()
    private var discardingLine = false
    private var lastSequence = 0
    private var task: Task<Void, Never>?
    private var onEvent: (@Sendable (EngineEventV1) async -> Void)?
    private var onFailure: (@Sendable () async -> Void)?
    public var isObserving: Bool { task != nil }

    public init(eventsURL: URL, requestID: UUID) {
        self.eventsURL = eventsURL; self.requestID = requestID
    }

    public func start(
        onEvent: @escaping @Sendable (EngineEventV1) async -> Void,
        onFailure: @escaping @Sendable () async -> Void
    ) {
        guard task == nil else { return }
        self.onEvent = onEvent; self.onFailure = onFailure
        task = Task {
            while !Task.isCancelled {
                await deliverAvailable()
                do { try await Task.sleep(for: .milliseconds(100)) }
                catch { break }
            }
        }
    }

    public func stop() async {
        guard let task else { return }
        task.cancel()
        await task.value
        await deliverAvailable()
        self.task = nil
        onEvent = nil; onFailure = nil
    }

    private func deliverAvailable() async {
        do {
            for event in try readAvailable() { await onEvent?(event) }
        } catch {
            // Observation is advisory; a read failure cannot decide the job outcome.
            await onFailure?()
        }
    }

    /// Read at most 1 MiB per pass and retain at most 256 KiB of an unfinished line.
    public func readAvailable() throws -> [EngineEventV1] {
        guard FileManager.default.fileExists(atPath: eventsURL.path) else { return [] }
        let handle = try FileHandle(forReadingFrom: eventsURL)
        defer { try? handle.close() }
        try handle.seek(toOffset: offset)
        var events: [EngineEventV1] = []
        for _ in 0..<16 {
            guard let data = try handle.read(upToCount: 65_536), !data.isEmpty else { break }
            offset += UInt64(data.count)
            for byte in data {
                if byte == 10 {
                    if !discardingLine,
                       let event = try? EngineProtocolCodec.decodeEvent(partial),
                       event.requestID == requestID, event.sequence > lastSequence {
                        lastSequence = event.sequence
                        events.append(event)
                    }
                    partial.removeAll(keepingCapacity: true)
                    discardingLine = false
                } else if !discardingLine {
                    if partial.count < 262_144 { partial.append(byte) }
                    else { partial.removeAll(keepingCapacity: true); discardingLine = true }
                }
            }
        }
        return events
    }
}
