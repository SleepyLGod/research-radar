import Foundation
import Testing
@testable import ResearchRadarPDFCore

@Suite struct PDFProtocolTests {
    @Test func topLeftCropConvertsToPDFCoordinates() {
        let page = PDFBoxV1(x: 0, y: 0, width: 600, height: 800)
        let crop = PDFBoxV1(x: 40, y: 100, width: 300, height: 200)

        #expect(crop.pdfCoordinates(in: page) == PDFBoxV1(x: 40, y: 500, width: 300, height: 200))
    }

    @Test func allowedRootRejectsEscapesAndSymlinks() throws {
        let root = try TemporaryDirectory()
        let inside = root.url.appending(path: "paper.pdf")
        try Data("pdf".utf8).write(to: inside)
        let outside = root.url.deletingLastPathComponent().appending(path: "outside.pdf")
        try Data("pdf".utf8).write(to: outside)
        defer { try? trash(outside) }

        #expect(throws: PDFPathError.outsideAllowedRoot) {
            try PDFPathValidator.existingFile(outside, allowedRoot: root.url)
        }

        let link = root.url.appending(path: "linked.pdf")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: inside)
        #expect(throws: PDFPathError.symbolicLink) {
            try PDFPathValidator.existingFile(link, allowedRoot: root.url)
        }
    }

    @Test func requestDecoderRejectsUnknownFields() throws {
        let request = Data(#"{"schema_version":1,"operation":"page_text","allowed_root":"/tmp/radar","input_path":"/tmp/radar/paper.pdf","page_index":0,"unexpected":true}"#.utf8)

        #expect(throws: PDFProtocolError.unexpectedFields) {
            try PDFProtocolCodec.decodeRequest(request)
        }
    }
}

private final class TemporaryDirectory {
    let url: URL

    init() throws {
        url = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
    }

    deinit { try? trash(url) }
}

private func trash(_ url: URL) throws {
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/trash")
    process.arguments = [url.path]
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        throw CocoaError(.fileWriteUnknown)
    }
}
