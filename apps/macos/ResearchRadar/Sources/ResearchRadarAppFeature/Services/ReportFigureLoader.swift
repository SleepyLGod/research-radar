import Foundation
import ImageIO
import ResearchRadarCore
import UniformTypeIdentifiers

/// Decode only a bounded run-local raster into a display-sized, single-frame image.
enum ReportFigureLoader {
    static func thumbnailData(path: String, report: ReportRecordV1, workspace: URL) throws -> Data {
        let policy = try ReportReaderPolicy(report: report, workspaceRoot: workspace)
        var url = URLComponents()
        url.scheme = ReportReaderPolicy.scheme; url.host = "run"; url.path = "/" + path
        guard let resourceURL = url.url else { throw ReportReaderPolicy.Failure.deniedResource }
        let resource = try policy.resource(at: resourceURL)
        guard ["image/png", "image/jpeg", "image/gif", "image/webp"].contains(resource.mimeType),
              let source = CGImageSourceCreateWithData(resource.data as CFData, nil),
              let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceThumbnailMaxPixelSize: 1600,
                kCGImageSourceCreateThumbnailWithTransform: true
              ] as CFDictionary) else { throw ReportReaderPolicy.Failure.deniedResource }
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else {
            throw ReportReaderPolicy.Failure.unreadableResource
        }
        CGImageDestinationAddImage(destination, thumbnail, nil)
        guard CGImageDestinationFinalize(destination) else { throw ReportReaderPolicy.Failure.unreadableResource }
        return data as Data
    }
}
