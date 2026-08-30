import Foundation

public struct PDFBoxV1: Codable, Equatable, Sendable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double

    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }

    public func pdfCoordinates(in page: PDFBoxV1) -> PDFBoxV1 {
        PDFBoxV1(
            x: page.x + x,
            y: page.y + page.height - y - height,
            width: width,
            height: height
        )
    }

    public func isContained(in page: PDFBoxV1) -> Bool {
        width > 0 && height > 0 && x >= 0 && y >= 0
            && x + width <= page.width && y + height <= page.height
    }
}

public struct PDFWordV1: Codable, Equatable, Sendable {
    public let text: String
    public let box: PDFBoxV1

    public init(text: String, box: PDFBoxV1) {
        self.text = text
        self.box = box
    }
}

public struct PDFPageTextV1: Codable, Equatable, Sendable {
    public let pageIndex: Int
    public let pageBox: PDFBoxV1
    public let words: [PDFWordV1]

    public init(pageIndex: Int, pageBox: PDFBoxV1, words: [PDFWordV1]) {
        self.pageIndex = pageIndex
        self.pageBox = pageBox
        self.words = words
    }

    enum CodingKeys: String, CodingKey {
        case pageIndex = "page_index"
        case pageBox = "page_box"
        case words
    }
}

public enum PDFOperationV1: String, Codable, Sendable {
    case pageText = "page_text"
    case renderCrop = "render_crop"
}

public enum PDFHelperRequestV1: Equatable, Sendable {
    case pageText(allowedRoot: String, inputPath: String, pageIndex: Int)
    case renderCrop(
        allowedRoot: String,
        inputPath: String,
        outputPath: String,
        pageIndex: Int,
        crop: PDFBoxV1,
        scale: Double
    )
}

public enum PDFProtocolError: Error, Equatable {
    case invalidJSON
    case invalidValue
    case unexpectedFields
}

public enum PDFProtocolCodec {
    public static func decodeRequest(_ data: Data) throws -> PDFHelperRequestV1 {
        guard let object = try? JSONSerialization.jsonObject(with: data),
              let dictionary = object as? [String: Any]
        else {
            throw PDFProtocolError.invalidJSON
        }
        guard dictionary["schema_version"] as? Int == 1,
              let rawOperation = dictionary["operation"] as? String,
              let operation = PDFOperationV1(rawValue: rawOperation),
              let allowedRoot = dictionary["allowed_root"] as? String,
              let inputPath = dictionary["input_path"] as? String,
              let pageIndex = dictionary["page_index"] as? Int,
              pageIndex >= 0
        else {
            throw PDFProtocolError.invalidValue
        }

        switch operation {
        case .pageText:
            try requireExactKeys(
                dictionary,
                expected: ["schema_version", "operation", "allowed_root", "input_path", "page_index"]
            )
            return .pageText(
                allowedRoot: allowedRoot,
                inputPath: inputPath,
                pageIndex: pageIndex
            )
        case .renderCrop:
            try requireExactKeys(
                dictionary,
                expected: [
                    "schema_version", "operation", "allowed_root", "input_path",
                    "output_path", "page_index", "crop", "scale",
                ]
            )
            guard let outputPath = dictionary["output_path"] as? String,
                  let cropObject = dictionary["crop"],
                  let cropData = try? JSONSerialization.data(withJSONObject: cropObject),
                  let crop = try? decoder.decode(PDFBoxV1.self, from: cropData),
                  let scale = dictionary["scale"] as? Double,
                  scale > 0, scale <= 4
            else {
                throw PDFProtocolError.invalidValue
            }
            return .renderCrop(
                allowedRoot: allowedRoot,
                inputPath: inputPath,
                outputPath: outputPath,
                pageIndex: pageIndex,
                crop: crop,
                scale: scale
            )
        }
    }

    public static func encode<T: Encodable>(_ value: T) throws -> Data {
        try encoder.encode(value)
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }()

    private static func requireExactKeys(
        _ dictionary: [String: Any],
        expected: Set<String>
    ) throws {
        guard Set(dictionary.keys) == expected else {
            throw PDFProtocolError.unexpectedFields
        }
    }
}

public struct PDFPageTextResponseV1: Encodable, Sendable {
    public let schemaVersion = 1
    public let operation = PDFOperationV1.pageText
    public let page: PDFPageTextV1

    public init(page: PDFPageTextV1) {
        self.page = page
    }
}

public struct PDFRenderCropResponseV1: Encodable, Sendable {
    public let schemaVersion = 1
    public let operation = PDFOperationV1.renderCrop
    public let outputPath: String

    public init(outputPath: String) {
        self.outputPath = outputPath
    }
}

public struct PDFHelperErrorV1: Encodable, Sendable {
    public let schemaVersion = 1
    public let code: String
    public let message: String

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }
}
