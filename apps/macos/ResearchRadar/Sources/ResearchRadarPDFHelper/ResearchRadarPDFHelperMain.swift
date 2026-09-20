import Foundation
import ResearchRadarPDFCore

@main
struct ResearchRadarPDFHelperMain {
    static func main() {
        do {
            let data = FileHandle.standardInput.readDataToEndOfFile()
            let request = try PDFProtocolCodec.decodeRequest(data)
            let service = PDFDocumentService()
            let response: Data

            switch request {
            case let .pageText(allowedRoot, inputPath, pageIndex):
                let root = URL(fileURLWithPath: allowedRoot)
                let input = try PDFPathValidator.existingFile(
                    URL(fileURLWithPath: inputPath),
                    allowedRoot: root
                )
                let page = try service.pageText(input: input, pageIndex: pageIndex)
                response = try PDFProtocolCodec.encode(PDFPageTextResponseV1(page: page))
            case let .renderCrop(allowedRoot, inputPath, outputPath, pageIndex, crop, scale):
                let root = URL(fileURLWithPath: allowedRoot)
                let input = try PDFPathValidator.existingFile(
                    URL(fileURLWithPath: inputPath),
                    allowedRoot: root
                )
                let output = try PDFPathValidator.outputFile(
                    URL(fileURLWithPath: outputPath),
                    allowedRoot: root
                )
                try service.renderCrop(
                    input: input,
                    output: output,
                    pageIndex: pageIndex,
                    crop: crop,
                    scale: scale
                )
                response = try PDFProtocolCodec.encode(
                    PDFRenderCropResponseV1(outputPath: output.path)
                )
            }
            FileHandle.standardOutput.write(response)
        } catch {
            let payload = PDFHelperErrorV1(
                code: "pdf_helper_failed",
                message: "The PDF operation could not be completed."
            )
            if let data = try? PDFProtocolCodec.encode(payload) {
                FileHandle.standardError.write(data)
            }
            Foundation.exit(2)
        }
    }
}
