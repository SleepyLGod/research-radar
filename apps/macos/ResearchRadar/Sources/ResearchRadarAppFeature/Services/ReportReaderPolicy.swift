import Darwin
import Foundation
import ResearchRadarCore

/// Read-only access to one run. No file URL is exposed to WebKit.
/// Unlike loadFileURL, the private scheme validates every relative asset request
/// at read time. HTML bytes and source artifacts are never rewritten. Direct
/// file URLs and non-entry HTML navigation are deliberately unsupported.
struct ReportReaderPolicy: Sendable {
    enum Failure: Error { case invalidReport, deniedResource, unreadableResource }
    enum Navigation { case allow, external, cancel }
    struct Resource {
        let data: Data
        let mimeType: String
    }

    static let scheme = "radar-report"
    let entryURL: URL
    private let workspace: FileHandle
    private let runComponents: [String]
    private let entryPath: String

    init(report: ReportRecordV1, workspaceRoot: URL) throws {
        guard workspaceRoot.isFileURL else {
            throw Failure.invalidReport
        }
        let lexicalWorkspace = try Self.lexicalPath(workspaceRoot.path)
        let run = try Self.lexicalPath(report.runDirectory)
        let entry = try Self.lexicalPath(report.reportHTMLPath)
        let prefix = run + "/"
        guard entry.hasPrefix(prefix), ["html", "htm"].contains((entry as NSString).pathExtension.lowercased()) else {
            throw Failure.invalidReport
        }
        // Only the caller's trusted root may resolve symlinks. Never canonicalize
        // a report-supplied run or entry: doing so would authorize an escape.
        guard let canonical = realpath(workspaceRoot.path, nil) else { throw Failure.invalidReport }
        let canonicalWorkspace = String(cString: canonical)
        free(canonical)
        guard let base = [lexicalWorkspace, canonicalWorkspace].first(where: {
            run == $0 || run.hasPrefix($0 + "/")
        }) else { throw Failure.invalidReport }
        runComponents = run.dropFirst(base.count).split(separator: "/").map(String.init)
        workspace = try Self.openWorkspace(canonicalWorkspace)
        entryPath = String(entry.dropFirst(prefix.count))
        var components = URLComponents()
        components.scheme = Self.scheme
        components.host = "run"
        components.path = "/" + entryPath
        guard let url = components.url else { throw Failure.invalidReport }
        entryURL = url
        _ = try resource(at: entryURL)
    }

    private static func lexicalPath(_ path: String) throws -> String {
        guard path.hasPrefix("/"), !path.contains("\0"), !path.contains("\\") else {
            throw Failure.invalidReport
        }
        let parts = path.split(separator: "/")
        guard parts.allSatisfy({ $0 != "." && $0 != ".." }) else { throw Failure.invalidReport }
        let normalized = "/" + parts.joined(separator: "/")
        // Accept macOS system aliases without resolving any untrusted component.
        if normalized == "/var" || normalized.hasPrefix("/var/") ||
            normalized == "/tmp" || normalized.hasPrefix("/tmp/") {
            return "/private" + normalized
        }
        return normalized
    }

    private static func openWorkspace(_ path: String) throws -> FileHandle {
        var directory = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC)
        guard directory >= 0 else { throw Failure.unreadableResource }
        for part in path.split(separator: "/") {
            let next = openat(directory, String(part), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            close(directory)
            guard next >= 0 else { throw Failure.deniedResource }
            directory = next
        }
        return FileHandle(fileDescriptor: directory, closeOnDealloc: true)
    }

    func navigation(to url: URL, userActivated: Bool, mainFrame: Bool) -> Navigation {
        guard mainFrame else { return .cancel }
        if ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
            return userActivated && url.host != nil && url.user == nil && url.password == nil ? .external : .cancel
        }
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: true) else { return .cancel }
        components.fragment = nil
        return components.url == entryURL ? .allow : .cancel
    }

    func resource(at url: URL) throws -> Resource {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: true),
              components.scheme == Self.scheme, components.host == "run",
              components.port == nil, components.user == nil, components.password == nil,
              !components.path.contains("\0"), !components.path.contains("\\") else {
            throw Failure.deniedResource
        }
        let parts = components.path.split(separator: "/", omittingEmptySubsequences: false).dropFirst().map(String.init)
        guard !parts.isEmpty, parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw Failure.deniedResource
        }
        let path = parts.joined(separator: "/")
        let mime: String
        if path == entryPath {
            mime = "text/html"
        } else {
            let types = ["png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                         "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
                         "avif": "image/avif", "css": "text/css", "woff": "font/woff",
                         "woff2": "font/woff2", "ttf": "font/ttf", "otf": "font/otf"]
            guard let type = types[URL(fileURLWithPath: path).pathExtension.lowercased()] else {
                throw Failure.deniedResource
            }
            mime = type
        }

        // Every read starts from the pinned trusted workspace, not a pathname
        // validated earlier. Run roots and their ancestors cannot follow links.
        var directory = dup(workspace.fileDescriptor)
        guard directory >= 0 else { throw Failure.unreadableResource }
        defer { close(directory) }
        for part in runComponents + parts.dropLast() {
            let next = openat(directory, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard next >= 0 else { throw Failure.deniedResource }
            close(directory)
            directory = next
        }
        let descriptor = openat(directory, parts.last!, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw Failure.unreadableResource }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        var info = stat()
        guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              info.st_size <= 32 * 1024 * 1024 else { throw Failure.deniedResource }
        let data = try handle.read(upToCount: 32 * 1024 * 1024 + 1) ?? Data()
        guard data.count <= 32 * 1024 * 1024 else { throw Failure.deniedResource }
        return Resource(data: data, mimeType: mime)
    }
}
