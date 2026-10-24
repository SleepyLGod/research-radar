import Foundation

/// Deterministic JSON encoding shared by durable App state.
public enum JSONCoding {
    /// Encodes a value with stable key ordering and date formatting.
    public static func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(value)
    }

    /// Decodes a value using the matching durable-state date format.
    public static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        decoder.keyDecodingStrategy = .custom { path in
            let raw = path.last?.stringValue ?? ""
            let parts = raw.split(separator: "_").map(String.init)
            let first = parts.first ?? raw
            let rest = parts.dropFirst().map { part in
                switch part {
                case "id": "ID"
                case "url": "URL"
                case "html": "HTML"
                default: part.prefix(1).uppercased() + String(part.dropFirst())
                }
            }
            return JSONKey(stringValue: ([first] + rest).joined())!
        }
        return try decoder.decode(type, from: data)
    }
}

private struct JSONKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil

    init?(stringValue: String) {
        self.stringValue = stringValue
    }

    init?(intValue: Int) {
        return nil
    }
}

/// Typed failures from owner-only JSON persistence.
public enum AtomicJSONStoreError: Error, Equatable, Sendable {
    case invalidRelativePath(String)
    case pathOutsideRoot(URL)
    case symbolicLink(URL)
    case notRegularFile(URL)
    case corruptFile(URL)
    case unsupportedSchema(URL, Int)
    case ioFailure(URL)
}

/// A durable top-level JSON document with an explicit migration boundary.
public protocol VersionedDurableState {
    var schemaVersion: Int { get }
}

/// A durable document whose decoded values must satisfy semantic invariants.
public protocol ValidatableDurableState: VersionedDurableState {
    func validate() throws
}

/// Persists Codable values beneath one trusted App Support root.
public struct AtomicJSONStore: Sendable {
    private let root: URL

    /// Creates a store rooted at the configured App Support directory.
    public init(root: URL) {
        self.root = root.standardizedFileURL
    }

    /// Atomically writes a value to a relative path below the store root.
    public func write<T: Encodable>(_ value: T, to relativePath: String) throws {
        let fileManager = FileManager.default
        let canonicalRoot = try prepareRoot(fileManager: fileManager)
        let destination = try prepareDestination(
            relativePath,
            canonicalRoot: canonicalRoot,
            fileManager: fileManager
        )
        let data = try JSONCoding.encode(value)
        try replaceAtomically(data, at: destination, fileManager: fileManager)
    }

    /// Reads a value without modifying bytes when decoding fails.
    public func read<T: Decodable>(_ type: T.Type, from relativePath: String) throws -> T {
        let fileManager = FileManager.default
        let canonicalRoot = try prepareRoot(fileManager: fileManager)
        let source = try existingFile(
            relativePath,
            canonicalRoot: canonicalRoot,
            fileManager: fileManager
        )
        let data: Data
        do {
            data = try Data(contentsOf: source)
        } catch {
            throw AtomicJSONStoreError.ioFailure(source)
        }
        do {
            let value = try JSONCoding.decode(type, from: data)
            if let versioned = value as? any VersionedDurableState,
               versioned.schemaVersion != 1
            {
                throw AtomicJSONStoreError.unsupportedSchema(source, versioned.schemaVersion)
            }
            if let validatable = value as? any ValidatableDurableState {
                try validatable.validate()
            }
            return value
        } catch let error as AtomicJSONStoreError {
            throw error
        } catch {
            throw AtomicJSONStoreError.corruptFile(source)
        }
    }

    private func prepareRoot(fileManager: FileManager) throws -> URL {
        if isSymbolicLink(root, fileManager: fileManager) {
            throw AtomicJSONStoreError.symbolicLink(root)
        }
        do {
            try fileManager.createDirectory(
                at: root,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: root.path)
        } catch {
            throw AtomicJSONStoreError.ioFailure(root)
        }
        if isSymbolicLink(root, fileManager: fileManager) {
            throw AtomicJSONStoreError.symbolicLink(root)
        }
        return root.resolvingSymlinksInPath().standardizedFileURL
    }

    private func prepareDestination(
        _ relativePath: String,
        canonicalRoot: URL,
        fileManager: FileManager
    ) throws -> URL {
        let components = try pathComponents(relativePath)
        var parent = canonicalRoot
        for component in components.dropLast() {
            parent.append(path: component, directoryHint: .isDirectory)
            try prepareDirectory(parent, canonicalRoot: canonicalRoot, fileManager: fileManager)
        }
        let destination = parent.appending(path: components.last!)
        try requireContained(destination, in: canonicalRoot)
        if isSymbolicLink(destination, fileManager: fileManager) {
            throw AtomicJSONStoreError.symbolicLink(destination)
        }
        if fileManager.fileExists(atPath: destination.path), !isRegularFile(destination, fileManager: fileManager) {
            throw AtomicJSONStoreError.notRegularFile(destination)
        }
        return destination
    }

    private func existingFile(
        _ relativePath: String,
        canonicalRoot: URL,
        fileManager: FileManager
    ) throws -> URL {
        let components = try pathComponents(relativePath)
        var candidate = canonicalRoot
        for component in components {
            candidate.append(path: component)
            try requireContained(candidate, in: canonicalRoot)
            if isSymbolicLink(candidate, fileManager: fileManager) {
                throw AtomicJSONStoreError.symbolicLink(candidate)
            }
        }
        guard isRegularFile(candidate, fileManager: fileManager) else {
            throw AtomicJSONStoreError.notRegularFile(candidate)
        }
        do {
            try fileManager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: candidate.path)
        } catch {
            throw AtomicJSONStoreError.ioFailure(candidate)
        }
        return candidate
    }

    private func prepareDirectory(
        _ directory: URL,
        canonicalRoot: URL,
        fileManager: FileManager
    ) throws {
        try requireContained(directory, in: canonicalRoot)
        if isSymbolicLink(directory, fileManager: fileManager) {
            throw AtomicJSONStoreError.symbolicLink(directory)
        }
        do {
            var isDirectory: ObjCBool = false
            if fileManager.fileExists(atPath: directory.path, isDirectory: &isDirectory) {
                guard isDirectory.boolValue else {
                    throw AtomicJSONStoreError.notRegularFile(directory)
                }
            } else {
                try fileManager.createDirectory(
                    at: directory,
                    withIntermediateDirectories: false,
                    attributes: [.posixPermissions: 0o700]
                )
            }
            try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
        } catch let error as AtomicJSONStoreError {
            throw error
        } catch {
            throw AtomicJSONStoreError.ioFailure(directory)
        }
        if isSymbolicLink(directory, fileManager: fileManager) {
            throw AtomicJSONStoreError.symbolicLink(directory)
        }
    }

    private func replaceAtomically(
        _ data: Data,
        at destination: URL,
        fileManager: FileManager
    ) throws {
        let temporary = destination.deletingLastPathComponent()
            .appending(path: ".\(destination.lastPathComponent).\(UUID().uuidString).tmp")
        guard fileManager.createFile(
            atPath: temporary.path,
            contents: nil,
            attributes: [.posixPermissions: 0o600]
        ) else {
            throw AtomicJSONStoreError.ioFailure(temporary)
        }
        do {
            let handle = try FileHandle(forWritingTo: temporary)
            try handle.write(contentsOf: data)
            try handle.synchronize()
            try handle.close()
            try fileManager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
            if fileManager.fileExists(atPath: destination.path) {
                _ = try fileManager.replaceItemAt(destination, withItemAt: temporary)
            } else {
                try fileManager.moveItem(at: temporary, to: destination)
            }
            try fileManager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
        } catch {
            throw AtomicJSONStoreError.ioFailure(destination)
        }
    }

    private func pathComponents(_ relativePath: String) throws -> [String] {
        guard !relativePath.isEmpty, !relativePath.hasPrefix("/") else {
            throw AtomicJSONStoreError.invalidRelativePath(relativePath)
        }
        let components = relativePath.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw AtomicJSONStoreError.invalidRelativePath(relativePath)
        }
        return components
    }

    private func requireContained(_ url: URL, in root: URL) throws {
        let path = url.standardizedFileURL.path
        guard path.hasPrefix(root.path + "/") else {
            throw AtomicJSONStoreError.pathOutsideRoot(url)
        }
    }

    private func isSymbolicLink(_ url: URL, fileManager: FileManager) -> Bool {
        (try? fileManager.destinationOfSymbolicLink(atPath: url.path)) != nil
    }

    private func isRegularFile(_ url: URL, fileManager: FileManager) -> Bool {
        guard let attributes = try? fileManager.attributesOfItem(atPath: url.path) else {
            return false
        }
        return attributes[.type] as? FileAttributeType == .typeRegular
    }
}
