import Foundation

/// Resolves a user-selected or locally installed Codex executable without invoking a shell.
public struct CodexExecutableResolver: Sendable {
    private let systemExecutableDirectories: [URL]
    private let systemApplicationDirectories: [URL]

    public init() {
        self.init(
            systemExecutableDirectories: [URL(fileURLWithPath: "/opt/homebrew/bin"), URL(fileURLWithPath: "/usr/local/bin")],
            systemApplicationDirectories: [URL(fileURLWithPath: "/Applications")]
        )
    }

    init(systemExecutableDirectories: [URL], systemApplicationDirectories: [URL]) {
        self.systemExecutableDirectories = systemExecutableDirectories
        self.systemApplicationDirectories = systemApplicationDirectories
    }

    public func resolve(
        savedPath: String?,
        environmentPath: String?,
        homeDirectory: URL
    ) -> URL? {
        var candidates: [URL] = []
        if let savedPath, !savedPath.isEmpty {
            candidates.append(URL(fileURLWithPath: savedPath))
        }
        if let environmentPath {
            candidates += environmentPath.split(separator: ":").filter {
                $0.hasPrefix("/")
            }.map {
                URL(fileURLWithPath: String($0)).appending(path: "codex")
            }
        }
        candidates += systemExecutableDirectories.map { $0.appending(path: "codex") }
        candidates.append(homeDirectory.appending(path: ".local/bin/codex"))
        for directory in [homeDirectory.appending(path: "Applications")] + systemApplicationDirectories {
            for app in ["Codex.app", "ChatGPT.app"] {
                candidates.append(directory.appending(path: "\(app)/Contents/Resources/codex"))
            }
        }
        return candidates.lazy.compactMap(validExecutable).first
    }

    private func validExecutable(_ candidate: URL) -> URL? {
        let resolved = candidate.resolvingSymlinksInPath().standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: resolved.path, isDirectory: &isDirectory),
              !isDirectory.boolValue,
              FileManager.default.isExecutableFile(atPath: resolved.path)
        else { return nil }
        return resolved
    }
}
