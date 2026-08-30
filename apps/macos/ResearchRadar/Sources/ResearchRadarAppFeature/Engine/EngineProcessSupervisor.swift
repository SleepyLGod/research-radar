import Darwin
import Foundation

public struct EngineProcessOutcome: Sendable {
    public let exitCode: Int32
    public let startedProcessGroup: Int32?
    public let standardOutput: Data
    public let standardError: Data
}

public enum EngineSupervisorError: Error, Sendable {
    case alreadyRunning
    case executableMissing
}

private final class ProcessBox: @unchecked Sendable {
    let process: Process
    let stdout = BoundedBuffer(limit: 1_048_576)
    let stderr = BoundedBuffer(limit: 1_048_576)
    let eventsURL: URL
    var processGroup: Int32?

    init(process: Process, eventsURL: URL) {
        self.process = process
        self.eventsURL = eventsURL
    }
}

private final class BoundedBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private let limit: Int
    private var data = Data()

    init(limit: Int) {
        self.limit = limit
    }

    func append(_ chunk: Data) {
        lock.lock()
        defer { lock.unlock() }
        data.append(chunk)
        if data.count > limit {
            data.removeFirst(data.count - limit)
        }
    }

    func snapshot() -> Data {
        lock.lock()
        defer { lock.unlock() }
        return data
    }
}

public actor EngineProcessSupervisor {
    private let terminationGrace: Duration
    private var running: ProcessBox?

    public init(terminationGrace: Duration = .seconds(5)) {
        self.terminationGrace = terminationGrace
    }

    public func run(
        executable: URL,
        arguments: [String],
        eventsURL: URL
    ) async throws -> EngineProcessOutcome {
        guard running == nil else { throw EngineSupervisorError.alreadyRunning }
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw EngineSupervisorError.executableMissing
        }

        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.environment = [
            "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
            "LANG": "en_US.UTF-8",
            "PATH": "/usr/bin:/bin",
            "TMPDIR": FileManager.default.temporaryDirectory.path,
        ]
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        let box = ProcessBox(process: process, eventsURL: eventsURL)
        running = box

        outputPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                try? handle.close()
            } else {
                box.stdout.append(data)
            }
        }
        errorPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                try? handle.close()
            } else {
                box.stderr.append(data)
            }
        }

        do {
            try process.run()
            try? outputPipe.fileHandleForWriting.close()
            try? errorPipe.fileHandleForWriting.close()
        } catch {
            Self.close(pipe: outputPipe)
            Self.close(pipe: errorPipe)
            running = nil
            throw error
        }

        let processGroupTask = Task { [eventsURL] in
            await Self.waitForStartedProcessGroup(eventsURL: eventsURL, processID: process.processIdentifier)
        }
        let exitCode = await withCheckedContinuation { continuation in
            process.terminationHandler = { terminated in
                continuation.resume(returning: terminated.terminationStatus)
            }
        }
        let detectedGroup = await processGroupTask.value
            ?? Self.declaredProcessGroup(eventsURL: eventsURL, processID: process.processIdentifier)
        box.processGroup = detectedGroup
        Self.finishReading(outputPipe.fileHandleForReading, into: box.stdout)
        Self.finishReading(errorPipe.fileHandleForReading, into: box.stderr)
        running = nil
        return EngineProcessOutcome(
            exitCode: exitCode,
            startedProcessGroup: detectedGroup,
            standardOutput: box.stdout.snapshot(),
            standardError: box.stderr.snapshot()
        )
    }

    public func cancel() async {
        guard let box = running else { return }
        let pid = box.process.processIdentifier
        let processGroup = Self.startedProcessGroup(eventsURL: box.eventsURL, processID: pid)
        box.processGroup = processGroup
        if let processGroup {
            Darwin.kill(-processGroup, SIGTERM)
            if await Self.waitForProcessGroupExit(processGroup, timeout: terminationGrace) {
                return
            }
        } else {
            Darwin.kill(pid, SIGTERM)
            if await Self.waitForProcessExit(box.process, timeout: terminationGrace) {
                return
            }
        }
        if let processGroup {
            Darwin.kill(-processGroup, SIGKILL)
            _ = await Self.waitForProcessGroupExit(processGroup, timeout: .seconds(2))
        } else if box.process.isRunning {
            Darwin.kill(pid, SIGKILL)
        }
    }

    private nonisolated static func waitForStartedProcessGroup(
        eventsURL: URL,
        processID: Int32
    ) async -> Int32? {
        for _ in 0..<200 {
            if let group = startedProcessGroup(eventsURL: eventsURL, processID: processID) {
                return group
            }
            if Darwin.kill(processID, 0) != 0 { return nil }
            try? await Task.sleep(for: .milliseconds(10))
        }
        return nil
    }

    private nonisolated static func finishReading(
        _ handle: FileHandle,
        into buffer: BoundedBuffer
    ) {
        handle.readabilityHandler = nil
        if let remaining = try? handle.readToEnd(), !remaining.isEmpty {
            buffer.append(remaining)
        }
        try? handle.close()
    }

    private nonisolated static func close(pipe: Pipe) {
        pipe.fileHandleForReading.readabilityHandler = nil
        try? pipe.fileHandleForReading.close()
        try? pipe.fileHandleForWriting.close()
    }

    private nonisolated static func startedProcessGroup(
        eventsURL: URL,
        processID: Int32
    ) -> Int32? {
        guard let group = declaredProcessGroup(eventsURL: eventsURL, processID: processID),
              Darwin.getpgid(processID) == group
        else { return nil }
        return group
    }

    private nonisolated static func declaredProcessGroup(
        eventsURL: URL,
        processID: Int32
    ) -> Int32? {
        guard let data = try? Data(contentsOf: eventsURL),
              let text = String(data: data, encoding: .utf8)
        else { return nil }
        for line in text.split(separator: "\n") {
            guard let lineData = line.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
                  object["kind"] as? String == "started",
                  let groupNumber = object["process_group_id"] as? NSNumber
            else { continue }
            let group = groupNumber.int32Value
            guard group == processID else { return nil }
            return group
        }
        return nil
    }

    private nonisolated static func processGroupExists(_ group: Int32) -> Bool {
        Darwin.kill(-group, 0) == 0 || errno == EPERM
    }

    private nonisolated static func waitForProcessGroupExit(
        _ group: Int32,
        timeout: Duration
    ) async -> Bool {
        let deadline = ContinuousClock.now + timeout
        while ContinuousClock.now < deadline {
            if !processGroupExists(group) { return true }
            try? await Task.sleep(for: .milliseconds(10))
        }
        return !processGroupExists(group)
    }

    private nonisolated static func waitForProcessExit(
        _ process: Process,
        timeout: Duration
    ) async -> Bool {
        let deadline = ContinuousClock.now + timeout
        while ContinuousClock.now < deadline {
            if !process.isRunning { return true }
            try? await Task.sleep(for: .milliseconds(10))
        }
        return !process.isRunning
    }
}
