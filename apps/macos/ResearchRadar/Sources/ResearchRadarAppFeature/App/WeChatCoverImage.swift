import AppKit
import CryptoKit
import Darwin
import ImageIO
import ResearchRadarCore
import UniformTypeIdentifiers

/// Immutable selection; the preview and uploaded bytes always describe the same image.
struct WeChatCoverImage: Equatable, Sendable, Identifiable {
    let id = UUID()
    let data: Data
    let previewData: Data
    let filename: String
    let fileExtension: String
    let width: Int
    let height: Int
    var sha256: String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

    init(data: Data, filename: String) throws {
        guard !data.isEmpty, data.count <= 2 * 1024 * 1024,
              let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              CGImageSourceGetStatus(source) == .statusComplete,
              let kind = CGImageSourceGetType(source) as String?,
              [UTType.png.identifier, UTType.jpeg.identifier].contains(kind),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let w = properties[kCGImagePropertyPixelWidth] as? Int,
              let h = properties[kCGImagePropertyPixelHeight] as? Int,
              w > 0, h > 0, w <= 40_000_000 / h,
              let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceThumbnailMaxPixelSize: 512,
                kCGImageSourceCreateThumbnailWithTransform: true,
              ] as CFDictionary),
              let preview = NSBitmapImageRep(cgImage: thumbnail).representation(using: .png, properties: [:]) else {
            throw WeChatDraftActionError.blocked("wechat_cover_invalid")
        }
        self.data = data; self.previewData = preview; self.filename = filename
        self.fileExtension = kind == UTType.png.identifier ? "png" : "jpg"
        self.width = w; self.height = h
    }

    static func load(_ url: URL) throws -> Self {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard descriptor >= 0 else { throw WeChatDraftActionError.blocked("wechat_cover_invalid") }
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_size > 0, info.st_size <= 2 * 1024 * 1024 else {
            throw WeChatDraftActionError.blocked("wechat_cover_invalid")
        }
        return try Self(data: file.read(upToCount: 2 * 1024 * 1024 + 1) ?? Data(), filename: url.lastPathComponent)
    }
}

struct WeChatCoverConfirmation: Identifiable, Equatable {
    let image: WeChatCoverImage
    let settings: WeChatDeliverySettingsV1
    let credentialRevision: UUID
    let attemptID: UUID
    let uncertainPriorUpload: Bool
    var id: UUID { image.id }
}
