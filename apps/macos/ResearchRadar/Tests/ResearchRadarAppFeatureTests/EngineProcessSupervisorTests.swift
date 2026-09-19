import Darwin
import Foundation
import Testing
@testable import ResearchRadarAppFeature

@Suite struct EngineProcessSupervisorTests {
    @Test func supervisorCompletesAStartedProcess() async throws {
        let fixture = try fixtureURL()
        let root = try privateTemporaryDirectory()
        let events = root.appending(path: "events.jsonl")
        let supervisor = EngineProcessSupervisor(terminationGrace: .milliseconds(200))

        let outcome = try await supervisor.run(
            executable: URL(fileURLWithPath: "/usr/bin/python3"),
            arguments: [fixture.path, "normal", events.path],
            eventsURL: events
        )

        let stderr = String(data: outcome.standardError, encoding: .utf8) ?? ""
        #expect(outcome.exitCode == 0, "fixture stderr: \(stderr)")
        #expect(outcome.startedProcessGroup != nil)
        #expect(outcome.standardError.isEmpty)
    }

    @Test func supervisorCancelsTheWholeProcessGroup() async throws {
        let fixture = try fixtureURL()
        let root = try privateTemporaryDirectory()
        let events = root.appending(path: "events.jsonl")
        let childPID = root.appending(path: "child.pid")
        let supervisor = EngineProcessSupervisor(terminationGrace: .milliseconds(200))

        let task = Task {
            try await supervisor.run(
                executable: URL(fileURLWithPath: "/usr/bin/python3"),
                arguments: [fixture.path, "ignore-term-process-tree", events.path, childPID.path],
                eventsURL: events
            )
        }
        try await waitForFile(childPID)
        await supervisor.cancel()
        _ = try? await task.value

        let pids = try processTreePIDs(childPID)
        #expect(kill(pids.child, 0) != 0)
        #expect(kill(pids.grandchild, 0) != 0)
    }

    @Test func supervisorReportsCrashBeforeStartedEvent() async throws {
        let fixture = try fixtureURL()
        let root = try privateTemporaryDirectory()
        let events = root.appending(path: "events.jsonl")
        let supervisor = EngineProcessSupervisor(terminationGrace: .milliseconds(100))

        let outcome = try await supervisor.run(
            executable: URL(fileURLWithPath: "/usr/bin/python3"),
            arguments: [fixture.path, "crash-before-started", events.path],
            eventsURL: events
        )

        #expect(outcome.exitCode == 17)
        #expect(outcome.startedProcessGroup == nil)
    }

    @Test func cancelBeforeStartedTerminatesOnlyTheEnginePID() async throws {
        let fixture = try fixtureURL()
        let root = try privateTemporaryDirectory()
        let events = root.appending(path: "events.jsonl")
        let enginePID = root.appending(path: "engine.pid")
        let supervisor = EngineProcessSupervisor(terminationGrace: .milliseconds(100))

        let task = Task {
            try await supervisor.run(
                executable: URL(fileURLWithPath: "/usr/bin/python3"),
                arguments: [fixture.path, "wait-before-started", events.path, enginePID.path],
                eventsURL: events
            )
        }
        try await waitForFile(enginePID)
        let pid = try #require(Int32(String(contentsOf: enginePID, encoding: .utf8)))
        await supervisor.cancel()
        _ = try? await task.value

        #expect(kill(pid, 0) != 0)
        #expect(!FileManager.default.fileExists(atPath: events.path))
    }

    @Test func responsiveChildAndGrandchildExitOnTerm() async throws {
        let fixture = try fixtureURL()
        let root = try privateTemporaryDirectory()
        let events = root.appending(path: "events.jsonl")
        let processTree = root.appending(path: "process-tree.json")
        let supervisor = EngineProcessSupervisor(terminationGrace: .seconds(1))

        let task = Task {
            try await supervisor.run(
                executable: URL(fileURLWithPath: "/usr/bin/python3"),
                arguments: [fixture.path, "term-process-tree", events.path, processTree.path],
                eventsURL: events
            )
        }
        try await waitForFile(processTree)
        let pids = try processTreePIDs(processTree)
        let startedCancel = ContinuousClock.now
        await supervisor.cancel()
        let cancelDuration = ContinuousClock.now - startedCancel
        _ = try? await task.value

        #expect(cancelDuration < .milliseconds(500))
        #expect(kill(pids.child, 0) != 0)
        #expect(kill(pids.grandchild, 0) != 0)
    }

    @Test func leaderExitDoesNotFreeSlotWhileTermIgnoringChildLives() async throws {
        let fixture = try fixtureURL()
        let root = try privateTemporaryDirectory()
        let events = root.appending(path: "events.jsonl")
        let tree = root.appending(path: "tree.json")
        let supervisor = EngineProcessSupervisor(terminationGrace: .milliseconds(500))
        let task = Task {
            try await supervisor.run(
                executable: URL(fileURLWithPath: "/usr/bin/python3"),
                arguments: [fixture.path, "ignore-term-process-tree", events.path, tree.path], eventsURL: events
            )
        }
        try await waitForFile(tree)
        let pids = try processTreePIDs(tree)
        let leader = getpgid(pids.child)
        #expect(leader > 0)
        guard leader > 0 else { await supervisor.cancel(); _ = try? await task.value; return }
        kill(leader, SIGKILL)
        await #expect(throws: EngineSupervisorError.self) {
            _ = try await supervisor.run(
                executable: URL(fileURLWithPath: "/usr/bin/true"), arguments: [],
                eventsURL: root.appending(path: "second-events.jsonl")
            )
        }
        _ = try await task.value
        #expect(kill(pids.child, 0) != 0)
        _ = try await supervisor.run(
            executable: URL(fileURLWithPath: "/usr/bin/true"), arguments: [],
            eventsURL: root.appending(path: "second-events.jsonl")
        )
    }

    @Test func cancellationBeforeStartedRechecksLateProcessGroup() async throws {
        let root = try privateTemporaryDirectory()
        let events = root.appending(path: "events.jsonl")
        let ready = root.appending(path: "ready.pid")
        let childPID = root.appending(path: "child.pid")
        // SIGTERM publishes started and creates a TERM-ignoring child before the leader exits.
        let script = #"""
        import errno,json,os,signal,subprocess,sys,time
        from pathlib import Path
        events,ready,child = map(Path,sys.argv[1:])
        try:
            os.setsid()
        except OSError as error:
            if error.errno != errno.EPERM or os.getpgrp() != os.getpid():
                raise
        def finish(signum, frame):
            code = 'import os,signal,sys,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)'
            subprocess.Popen([sys.executable,'-c',code,str(child)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while not child.exists():
                time.sleep(0.001)
            events.write_text(json.dumps({'type':'started'})+'\n')
            sys.exit(0)
        signal.signal(signal.SIGTERM,finish)
        ready.write_text(str(os.getpid()))
        time.sleep(60)
        """#
        let supervisor = EngineProcessSupervisor(terminationGrace: .seconds(1))
        let task = Task {
            try await supervisor.run(
                executable: URL(fileURLWithPath: "/usr/bin/python3"),
                arguments: ["-c", script, events.path, ready.path, childPID.path], eventsURL: events
            )
        }
        try await waitForFile(ready)
        #expect(!FileManager.default.fileExists(atPath: events.path))
        await supervisor.cancel()
        let pid = try #require(Int32(String(contentsOf: childPID, encoding: .utf8)))
        defer { if kill(pid, 0) == 0 { kill(pid, SIGKILL) } }
        let outcome = try await task.value
        #expect(outcome.startedProcessGroup != nil)
        #expect(kill(pid, 0) != 0)
    }
}

private struct ProcessTreePIDs: Decodable {
    let child: Int32
    let grandchild: Int32
}

private func processTreePIDs(_ url: URL) throws -> ProcessTreePIDs {
    try JSONDecoder().decode(ProcessTreePIDs.self, from: Data(contentsOf: url))
}

private func fixtureURL() throws -> URL {
    try #require(
        Bundle.module.url(
            forResource: "process_fixture",
            withExtension: "py",
            subdirectory: "Fixtures"
        )
    )
}

private func privateTemporaryDirectory() throws -> URL {
    let sourceFile = URL(fileURLWithPath: #filePath)
    let packageRoot = sourceFile
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
    let url = packageRoot
        .appending(path: ".build/test-data", directoryHint: .isDirectory)
        .appending(path: "research-radar-supervisor-\(UUID().uuidString)")
    try FileManager.default.createDirectory(
        at: url,
        withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700]
    )
    return url
}

private func waitForFile(_ url: URL) async throws {
    for _ in 0..<100 {
        if FileManager.default.fileExists(atPath: url.path) { return }
        try await Task.sleep(for: .milliseconds(20))
    }
    throw CocoaError(.fileReadNoSuchFile)
}
