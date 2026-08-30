import AppKit
import Foundation
import Testing
@testable import ResearchRadarPDFCore
@testable import ResearchRadarPDFHelper

@Suite struct PDFDocumentServiceTests {
    @Test func extractsTopLeftWordBoxesAndRendersCrop() throws {
        let fixture = try PDFFixture()
        let service = PDFDocumentService()

        let page = try service.pageText(input: fixture.pdf, pageIndex: 0)
        let hello = try #require(page.words.first { $0.text == "Hello" })
        #expect(page.pageBox.width == 300)
        #expect(page.pageBox.height == 400)
        #expect(hello.box.x >= 0)
        #expect(hello.box.y >= 0)

        let output = fixture.root.appending(path: "crop.png")
        try service.renderCrop(
            input: fixture.pdf,
            output: output,
            pageIndex: 0,
            crop: PDFBoxV1(x: 0, y: 0, width: 300, height: 200),
            scale: 2
        )

        let image = try #require(NSImage(contentsOf: output))
        #expect(image.size.width == 600)
        #expect(image.size.height == 400)
    }
}

private final class PDFFixture {
    let root: URL
    let pdf: URL

    init() throws {
        root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        pdf = root.appending(path: "fixture.pdf")

        let data = NSMutableData()
        var mediaBox = CGRect(x: 0, y: 0, width: 300, height: 400)
        let consumer = try #require(CGDataConsumer(data: data as CFMutableData))
        let context = try #require(CGContext(consumer: consumer, mediaBox: &mediaBox, nil))
        context.beginPDFPage(nil)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        NSString(string: "Hello PDF").draw(
            at: NSPoint(x: 40, y: 320),
            withAttributes: [.font: NSFont.systemFont(ofSize: 18)]
        )
        NSGraphicsContext.restoreGraphicsState()
        context.endPDFPage()
        context.closePDF()
        try (data as Data).write(to: pdf)
    }

    deinit { try? trash(root) }
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
