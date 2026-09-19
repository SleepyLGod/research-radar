import Foundation
import ResearchRadarCore

enum EngineTerminalResolution {
    case success(EngineResultV1)
    case failure(JobState, RedactedEngineErrorV1, EngineStage?)
}

/// Uses the same artifact validation for process completion and crash recovery.
enum EngineTerminalResolver {
    static func resolve(
        directory: URL, requestID: UUID, command: EngineCommand,
        runDirectory: String? = nil, channel: DeliveryChannel? = nil,
        reportDate: String? = nil, topicID: String? = nil, appSupportRoot: URL? = nil,
        launched: Bool = true
    ) throws -> EngineTerminalResolution {
        let resultURL = directory.appending(path: "result.json")
        let errorURL = directory.appending(path: "error.json")
        let hasResult = FileManager.default.fileExists(atPath: resultURL.path)
        let hasError = FileManager.default.fileExists(atPath: errorURL.path)
        if hasResult || hasError {
            let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: directory.appending(path: "request.json")))
            guard request.requestID == requestID, request.command == command else {
                throw EngineJobCoordinatorError.requestMismatch
            }
            switch request.payload {
            case .runDaily(let payload):
                guard payload.topicID == topicID, payload.reportDate == reportDate else {
                    throw EngineJobCoordinatorError.requestMismatch
                }
            case .retryDelivery(let payload):
                guard payload.runDirectory == runDirectory, payload.channel == channel else {
                    throw EngineJobCoordinatorError.requestMismatch
                }
            default: break
            }
        }
        if hasResult {
            let request = try EngineProtocolCodec.decodeRequest(Data(contentsOf: directory.appending(path: "request.json")))
            guard request.requestID == requestID, request.command == command else {
                throw EngineJobCoordinatorError.requestMismatch
            }
            let result = try EngineProtocolCodec.decodeResult(Data(contentsOf: resultURL))
            guard result.requestID == requestID, result.command == command else {
                throw EngineJobCoordinatorError.requestMismatch
            }
            switch command {
            case .runDaily:
                guard let report = result.report,
                      case .runDaily(let payload) = request.payload,
                      payload.topicID == topicID, payload.reportDate == reportDate,
                      report.reportDate == payload.reportDate,
                      let appSupportRoot else {
                    throw EngineJobCoordinatorError.invalidTerminalArtifact
                }
                let run = URL(fileURLWithPath: report.runDirectory).resolvingSymlinksInPath().standardizedFileURL
                let workspace = appSupportRoot.appending(path: "workspace").resolvingSymlinksInPath().standardizedFileURL
                let draft = URL(fileURLWithPath: report.articleDraftPath).resolvingSymlinksInPath().standardizedFileURL
                guard run.path.hasPrefix(workspace.path + "/"), draft.path.hasPrefix(run.path + "/") else {
                    throw EngineJobCoordinatorError.invalidTerminalArtifact
                }
                let identity = try JSONDecoder().decode(ReportIdentity.self, from: Data(contentsOf: draft))
                guard identity.topicID == payload.topicID else { throw EngineJobCoordinatorError.requestMismatch }
            case .retryDelivery:
                guard let delivery = result.delivery,
                      case .retryDelivery(let payload) = request.payload,
                      payload.runDirectory == runDirectory, payload.channel == channel,
                      delivery.runDirectory == runDirectory, delivery.channel == channel,
                      (delivery.channel == .email && delivery.status == .sent)
                        || (delivery.channel == .wechat && delivery.status == .created) else {
                    throw EngineJobCoordinatorError.requestMismatch
                }
            case .preflight:
                guard result.preflight != nil else { throw EngineJobCoordinatorError.invalidTerminalArtifact }
            case .bootstrapTopic:
                guard result.topicDraft != nil else { throw EngineJobCoordinatorError.invalidTerminalArtifact }
            }
            return .success(result)
        }
        if hasError {
            let error = try EngineProtocolCodec.decodeError(Data(contentsOf: errorURL))
            guard error.requestID == requestID else { throw EngineJobCoordinatorError.requestMismatch }
            let state: JobState
            if command == .retryDelivery && launched { state = .deliveryUnknown }
            else if error.code == "cancelled" { state = .cancelled }
            else if error.code == "interrupted" || error.code == "parent_lost" { state = .interrupted }
            else { state = .failed }
            return .failure(state, RedactedEngineErrorV1(
                code: error.code, message: error.message, retryable: error.retryable
            ), error.stage)
        }
        let state: JobState = !launched ? .failed : command == .retryDelivery ? .deliveryUnknown : .interrupted
        return .failure(state, RedactedEngineErrorV1(
            code: launched ? "terminal_unconfirmed" : "engine_launch_failed",
            message: launched ? "The engine outcome is unconfirmed." : "The engine could not start.",
            retryable: command != .retryDelivery || !launched
        ), nil)
    }

    private struct ReportIdentity: Decodable {
        let topicID: String
        enum CodingKeys: String, CodingKey { case topicID = "topic_id" }
    }
}
