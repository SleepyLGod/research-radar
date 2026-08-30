import AppKit
import Foundation
import PDFKit
import ResearchRadarPDFCore

public enum PDFDocumentServiceError: Error {
    case unreadableDocument
    case invalidPage
    case invalidCrop
    case renderFailed
}

public struct PDFDocumentService {
    public init() {}

    public func pageText(input: URL, pageIndex: Int) throws -> PDFPageTextV1 {
        let page = try loadPage(input: input, pageIndex: pageIndex)
        let pageBounds = page.bounds(for: .mediaBox)
        let pageBox = PDFBoxV1(x: 0, y: 0, width: pageBounds.width, height: pageBounds.height)
        guard let text = page.string else {
            return PDFPageTextV1(pageIndex: pageIndex, pageBox: pageBox, words: [])
        }

        let source = text as NSString
        let expression = try NSRegularExpression(pattern: #"\S+"#)
        let words = expression.matches(
            in: text,
            range: NSRange(location: 0, length: source.length)
        ).compactMap { match -> PDFWordV1? in
            guard let selection = page.selection(for: match.range) else { return nil }
            let bounds = selection.bounds(for: page)
            guard !bounds.isNull, !bounds.isEmpty else { return nil }
            return PDFWordV1(
                text: source.substring(with: match.range),
                box: PDFBoxV1(
                    x: bounds.minX - pageBounds.minX,
                    y: pageBounds.maxY - bounds.maxY,
                    width: bounds.width,
                    height: bounds.height
                )
            )
        }
        return PDFPageTextV1(pageIndex: pageIndex, pageBox: pageBox, words: words)
    }

    public func renderCrop(
        input: URL,
        output: URL,
        pageIndex: Int,
        crop: PDFBoxV1,
        scale: Double
    ) throws {
        let page = try loadPage(input: input, pageIndex: pageIndex)
        let pageBounds = page.bounds(for: .mediaBox)
        let pageBox = PDFBoxV1(x: 0, y: 0, width: pageBounds.width, height: pageBounds.height)
        guard crop.isContained(in: pageBox), scale > 0, scale <= 4 else {
            throw PDFDocumentServiceError.invalidCrop
        }
        let width = Int((crop.width * scale).rounded())
        let height = Int((crop.height * scale).rounded())
        guard width > 0, height > 0,
              let context = CGContext(
                  data: nil,
                  width: width,
                  height: height,
                  bitsPerComponent: 8,
                  bytesPerRow: 0,
                  space: CGColorSpaceCreateDeviceRGB(),
                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
              )
        else {
            throw PDFDocumentServiceError.renderFailed
        }

        context.setFillColor(NSColor.white.cgColor)
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let pdfCrop = crop.pdfCoordinates(in: pageBox)
        context.scaleBy(x: scale, y: scale)
        context.translateBy(x: -pdfCrop.x, y: -pdfCrop.y)
        page.draw(with: .mediaBox, to: context)
        guard let image = context.makeImage(),
              let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])
        else {
            throw PDFDocumentServiceError.renderFailed
        }
        try png.write(to: output, options: .atomic)
    }

    private func loadPage(input: URL, pageIndex: Int) throws -> PDFPage {
        guard let document = PDFDocument(url: input) else {
            throw PDFDocumentServiceError.unreadableDocument
        }
        guard pageIndex >= 0, pageIndex < document.pageCount,
              let page = document.page(at: pageIndex)
        else {
            throw PDFDocumentServiceError.invalidPage
        }
        return page
    }
}
