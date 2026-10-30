import Foundation
import ResearchRadarCore

struct KnowledgeRelationCamera: Equatable {
    var zoom: CGFloat = 1
    var offset: CGPoint = .zero
}

/// Transient, deterministic geometry; neither a scientific relationship nor a physics simulation.
struct KnowledgeRelationLayout {
    let positions: [String: CGPoint]

    init(papers: [KnowledgePaperV1], size: CGSize, camera: KnowledgeRelationCamera) {
        let papers = papers.sorted { $0.id < $1.id }, center = CGPoint(x: size.width / 2, y: size.height / 2 - 15)
        let radiusX = max(40, (size.width - 180) / 2), radiusY = max(30, (size.height - 170) / 2)
        positions = Dictionary(uniqueKeysWithValues: papers.enumerated().map { index, paper in
            let point: CGPoint
            if papers.count == 1 { point = .zero }
            else if papers.count == 2 { point = .init(x: index == 0 ? -radiusX : radiusX, y: 0) }
            else {
                let angle = CGFloat(index) * 2 * .pi / CGFloat(papers.count) - .pi / 2
                point = .init(x: cos(angle) * radiusX, y: sin(angle) * radiusY)
            }
            return (paper.id, CGPoint(x: center.x + point.x * camera.zoom + camera.offset.x,
                                      y: center.y + point.y * camera.zoom + camera.offset.y))
        })
    }

    static func controlPoint(from a: CGPoint, to b: CGPoint, lane: CGFloat) -> CGPoint {
        let length = max(1, hypot(b.x - a.x, b.y - a.y))
        // Undirected lane normals must not flip when the saved endpoint order changes.
        let direction: CGFloat = a.x < b.x || (a.x == b.x && a.y <= b.y) ? 1 : -1
        return .init(x: (a.x + b.x) / 2 - (b.y - a.y) / length * lane * direction,
                     y: (a.y + b.y) / 2 + (b.x - a.x) / length * lane * direction)
    }
}
