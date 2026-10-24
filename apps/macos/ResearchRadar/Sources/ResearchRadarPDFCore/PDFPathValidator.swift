import Foundation

public enum PDFPathError: Error, Equatable {
    case invalidAllowedRoot
    case outsideAllowedRoot
    case symbolicLink
    case missingFile
    case notRegularFile
    case invalidOutputParent
}

public enum PDFPathValidator {
    public static func existingFile(_ path: URL, allowedRoot: URL) throws -> URL {
        let root = try validatedRoot(allowedRoot)
        let standardized = try normalizedPath(path, root: root)
        let lexicalRoot = root
        try requireContained(standardized, in: lexicalRoot)
        try rejectSymbolicLinks(from: lexicalRoot, through: standardized, includeLeaf: true)
        let resolved = standardized.resolvingSymlinksInPath()
        try requireContained(resolved, in: root)

        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: standardized.path, isDirectory: &isDirectory)
        else {
            throw PDFPathError.missingFile
        }
        guard !isDirectory.boolValue else {
            throw PDFPathError.notRegularFile
        }
        let values = try standardized.resourceValues(forKeys: [.isRegularFileKey])
        guard values.isRegularFile == true else {
            throw PDFPathError.notRegularFile
        }
        return resolved
    }

    public static func outputFile(_ path: URL, allowedRoot: URL) throws -> URL {
        let root = try validatedRoot(allowedRoot)
        let standardized = try normalizedPath(path, root: root)
        let lexicalRoot = root
        try requireContained(standardized, in: lexicalRoot)
        let parent = standardized.deletingLastPathComponent()
        try rejectSymbolicLinks(from: lexicalRoot, through: parent, includeLeaf: true)
        let resolvedParent = parent.resolvingSymlinksInPath()
        try requireContained(resolvedParent, in: root)

        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: parent.path, isDirectory: &isDirectory),
              isDirectory.boolValue
        else {
            throw PDFPathError.invalidOutputParent
        }
        if FileManager.default.fileExists(atPath: standardized.path) {
            try rejectSymbolicLinks(
                from: lexicalRoot,
                through: standardized,
                includeLeaf: true
            )
            let values = try standardized.resourceValues(forKeys: [.isRegularFileKey])
            guard values.isRegularFile == true else {
                throw PDFPathError.notRegularFile
            }
        }
        return resolvedParent.appending(path: standardized.lastPathComponent)
    }

    private static func validatedRoot(_ root: URL) throws -> URL {
        let resolved = root.resolvingSymlinksInPath()
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: resolved.path, isDirectory: &isDirectory),
              isDirectory.boolValue
        else {
            throw PDFPathError.invalidAllowedRoot
        }
        return resolved
    }

    // Resolve aliases above the allowed root, never symbolic links below it.
    // Foundation can normalize existing /private/tmp paths differently from new files.
    private static func normalizedPath(_ path: URL, root: URL) throws -> URL {
        var current = URL(fileURLWithPath: "/", isDirectory: true)
        var suffix: [String] = []
        var reachedRoot = false
        for component in path.pathComponents.dropFirst() {
            guard component != "..", component != "." else {
                throw PDFPathError.outsideAllowedRoot
            }
            current.append(path: component)
            if reachedRoot {
                var info = stat()
                if lstat(current.path, &info) == 0 && (info.st_mode & S_IFMT) == S_IFLNK {
                    throw PDFPathError.symbolicLink
                }
                suffix.append(component)
            } else if current.resolvingSymlinksInPath().path == root.path {
                reachedRoot = true
            }
        }
        guard reachedRoot else { throw PDFPathError.outsideAllowedRoot }
        return suffix.reduce(root) { $0.appending(path: $1) }
    }

    private static func requireContained(_ path: URL, in root: URL) throws {
        let rootPath = root.path.hasSuffix("/") ? root.path : root.path + "/"
        guard path.path == root.path || path.path.hasPrefix(rootPath) else {
            throw PDFPathError.outsideAllowedRoot
        }
    }

    private static func rejectSymbolicLinks(
        from root: URL,
        through path: URL,
        includeLeaf: Bool
    ) throws {
        try requireContained(path, in: root)
        let relative = String(path.path.dropFirst(root.path.count)).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        var current = root
        let components = relative.isEmpty ? [] : relative.split(separator: "/").map(String.init)
        let checked = includeLeaf ? components : Array(components.dropLast())
        for component in checked {
            current.append(path: component)
            var info = stat()
            if lstat(current.path, &info) == 0 && (info.st_mode & S_IFMT) == S_IFLNK {
                throw PDFPathError.symbolicLink
            }
        }
    }
}
