import Foundation
import Testing
@testable import ResearchRadarAppFeature

@Suite struct EngineExecutionGateTests {
    @Test func onlyOneDrainAndNoAdmissionAfterStop() throws {
        let gate = EngineExecutionGate()
        #expect(gate.beginDrain())
        #expect(!gate.beginDrain())
        gate.endDrain()
        #expect(gate.beginDrain())
        let lease = try gate.acquire()
        #expect(throws: EngineExecutionGateError.busy) { try gate.acquire() }
        gate.stopAdmission()
        gate.release(lease)
        gate.endDrain()
        #expect(!gate.beginDrain())
        #expect(throws: EngineExecutionGateError.admissionStopped) { try gate.acquire() }
    }

    @Test func cancelBeforeLaunchPreventsRunning() async throws {
        let gate = EngineExecutionGate()
        let lease = try gate.acquire()
        defer { gate.release(lease) }
        await gate.cancel()
        let runner = GateTestRunner()
        await #expect(throws: EngineExecutionGateError.cancelled) {
            _ = try await gate.run(
                lease: lease, runner: runner, executable: URL(fileURLWithPath: "/fake"),
                arguments: [], eventsURL: URL(fileURLWithPath: "/fake/events")
            )
        }
        #expect(await runner.runs == 0)
    }
}

private actor GateTestRunner: EngineProcessRunning {
    private(set) var runs = 0
    func run(executable: URL, arguments: [String], eventsURL: URL) async throws -> EngineProcessOutcome {
        runs += 1
        return EngineProcessOutcome(exitCode: 0, startedProcessGroup: nil, standardOutput: Data(), standardError: Data())
    }
    func cancel() async {}
}
