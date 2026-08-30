import Foundation

/// Resolves a user-selected or locally installed Codex executable without invoking a shell.
public struct CodexExecutableResolver: Sendable {
    public init() {}

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
        candidates += [
            URL(fileURLWithPath: "/opt/homebrew/bin/codex"),
            URL(fileURLWithPath: "/usr/local/bin/codex"),
            homeDirectory.appending(path: ".local/bin/codex"),
        ]
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
