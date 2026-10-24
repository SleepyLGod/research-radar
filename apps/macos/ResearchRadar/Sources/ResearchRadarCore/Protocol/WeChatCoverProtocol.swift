import Foundation

public struct UploadWeChatCoverPayloadV1: Codable, Equatable, Sendable {
    public let imagePath: String
    public let imageSHA256: String

    public init(imagePath: String, imageSHA256: String) {
        self.imagePath = imagePath; self.imageSHA256 = imageSHA256
    }
    private enum CodingKeys: String, CodingKey {
        case imagePath = "image_path"
        case imageSHA256 = "image_sha256"
    }
}

public struct WeChatCoverResultV1: Codable, Equatable, Sendable {
    public let mediaID: String
    public let imageSHA256: String

    public init(mediaID: String, imageSHA256: String) {
        self.mediaID = mediaID; self.imageSHA256 = imageSHA256
    }
    private enum CodingKeys: String, CodingKey {
        case mediaID = "media_id"
        case imageSHA256 = "image_sha256"
    }
}
