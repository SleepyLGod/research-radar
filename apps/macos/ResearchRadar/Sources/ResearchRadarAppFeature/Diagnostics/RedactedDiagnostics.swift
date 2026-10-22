import Foundation
import ResearchRadarCore

/// Export only known identifiers and typed state, never raw configuration or error prose.
@MainActor
enum RedactedDiagnostics {
    static func text(for store: AppStore) throws -> String {
        let defaults = AppConfigurationDefaults.make(workspaceRoot: URL(fileURLWithPath: "/"), codexExecutable: nil)
        let knownModels = Set(defaults.routes.map(\.model))
        let routes = defaults.routes.map { supported -> [String: String] in
            let route = store.configuration.routes.first { $0.task == supported.task }
            let provider = store.configuration.providers.first { $0.id == route?.providerID }
            return [
                "task": supported.task,
                "provider": SettingsPresentation.providerName(route?.providerID) ?? "custom_omitted",
                "model": allowed(route?.model, in: knownModels),
                "reasoning_effort": allowed(provider?.reasoningEffort, in: ["medium", "high", "xhigh"]),
                "thinking": allowed(provider?.thinking, in: ["enabled", "disabled"]),
            ]
        }
        let os = ProcessInfo.processInfo.operatingSystemVersion
        var report: [String: Any] = [
            "diagnostics_version": 1,
            "scope": "selected_topic",
            "app_version": version(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String),
            "engine_version": engineVersion(from: store.preflight?.checks.first { $0.id == "engine" }?.message),
            "macos_version": "\(os.majorVersion).\(os.minorVersion).\(os.patchVersion)",
            "architecture": architecture,
            "routes": routes,
            "last_error_code": errorCode(store.lastErrorCode),
            "runtime": [
                "engine_running": store.isEngineRunning,
                "shutting_down": store.isShuttingDown,
                "reconciliation_required": store.requiresReconciliation,
                "schedule_faulted": store.scheduleFaulted,
                "schedules_paused": store.runtime.schedulesPaused,
                "pending_jobs": store.jobs.filter { $0.state == .pending }.count,
            ] as [String: Any],
        ]
        if let job = store.selectedTopicJobs.first {
            report["latest_attempt"] = [
                "kind": job.kind.rawValue,
                "state": job.state.rawValue,
                "recorded_stage": job.stage?.rawValue ?? "not_recorded",
                "channel": job.deliveryChannel?.rawValue ?? "none",
                "error_code": errorCode(job.error?.code),
            ]
        }
        if let latest = store.latestReport {
            report["latest_report"] = [
                "public_deep_read": latest.isEffectiveDeepReport,
                "research_outcome": latest.researchOutcome?.status.rawValue ?? "not_recorded",
                "deliveries": [DeliveryChannel.wechat, .email].compactMap { channel -> [String: String]? in
                    guard let delivery = latest.deliveries.first(where: { $0.channel == channel }) else { return nil }
                    return ["channel": channel.rawValue, "state": delivery.state.rawValue,
                        "error_code": errorCode(delivery.error?.code)]
                },
            ] as [String: Any]
        }
        let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        return String(decoding: data, as: UTF8.self)
    }

    static func engineVersion(from message: String?) -> String {
        guard let message, message.utf8.count < 100,
              message.range(of: #"\AResearchRadar [0-9]+(?:\.[0-9]+){1,3} on Python [0-9]+(?:\.[0-9]+){1,2}\.\z"#,
                options: .regularExpression) != nil else { return "not_recorded" }
        return version(String(message.split(separator: " ")[1]))
    }

    private static func version(_ value: String?) -> String {
        guard let value, value.utf8.count <= 32,
              value.range(of: #"\A[0-9]+(?:\.[0-9]+){0,3}\z"#, options: .regularExpression) != nil
        else { return "not_recorded" }
        return value
    }

    private static func errorCode(_ value: String?) -> String {
        guard let value else { return "none" }
        return UserFacingErrorCatalog.knownCodes.contains(value) ? value : "unknown"
    }

    private static func allowed(_ value: String?, in values: Set<String>) -> String {
        guard let value else { return "not_configured" }
        return values.contains(value) ? value : "custom_omitted"
    }

    private static var architecture: String {
        #if arch(arm64)
        "arm64"
        #elseif arch(x86_64)
        "x86_64"
        #else
        "unknown"
        #endif
    }
}
