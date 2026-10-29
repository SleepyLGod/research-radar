import ResearchRadarCore
import SwiftUI

/// Draws only supplied semantic relations; layout work occurs on view/state changes, not a timer.
struct KnowledgeRelationCanvas: View {
    let papers: [KnowledgePaperV1]
    let relations: [KnowledgeRelationV1]
    @Binding var camera: KnowledgeRelationCamera
    let selectedRelationID: String?
    let focusedPaperKey: String?
    let localization: LocalizationStore
    let selectPaper: (String) -> Void
    let selectRelation: (String) -> Void
    @GestureState private var drag = CGSize.zero
    @State private var hoveredRelationID: String?

    var body: some View {
        GeometryReader { geometry in
            let liveCamera = KnowledgeRelationCamera(zoom: camera.zoom,
                offset: .init(x: camera.offset.x + drag.width, y: camera.offset.y + drag.height))
            let layout = KnowledgeRelationLayout(papers: papers, size: geometry.size, camera: liveCamera)
            ZStack {
                Color(nsColor: .textBackgroundColor).contentShape(Rectangle())
                    .gesture(DragGesture().updating($drag) { value, state, _ in state = value.translation }
                        .onEnded { value in
                            camera.offset.x += value.translation.width; camera.offset.y += value.translation.height
                        })
                ForEach(relations) { relation in
                    if let source = layout.positions[relation.source], let target = layout.positions[relation.target] {
                        relationEdge(relation, source: source, target: target)
                    }
                }
                ForEach(papers) { paper in
                    if let point = layout.positions[paper.id] {
                        Button { selectPaper(paper.id) } label: {
                            VStack(spacing: 7) {
                                Circle().strokeBorder(.tint, lineWidth: 2).background(Circle().fill(.background))
                                    .overlay { Circle().fill(.tint).frame(width: 9, height: 9) }
                                    .frame(width: 22, height: 22)
                                Text(shortTitle(paper.title)).font(.system(size: 13, weight: .medium))
                                    .lineLimit(2).multilineTextAlignment(.center)
                                    .background(Color(nsColor: .textBackgroundColor))
                            }.frame(width: 138, height: 66, alignment: .top)
                        }.buttonStyle(.plain).help(paper.title).accessibilityLabel(paper.title)
                            .opacity(isRelated(paper.id) ? 1 : 0.25)
                            .position(x: point.x, y: point.y + 22)
                    }
                }
            }
            .overlay(alignment: .topLeading) {
                if relations.isEmpty {
                    Text(localization.text("graph.no_relations"))
                        .font(.system(size: 12)).foregroundStyle(.secondary).padding(16)
                }
            }
            .overlay(alignment: .bottomTrailing) {
                HStack(spacing: 4) {
                    Button { camera.zoom -= 0.15 } label: { Image(systemName: "minus") }
                        .help(localization.text("graph.zoom_out")).accessibilityLabel(localization.text("graph.zoom_out"))
                        .disabled(camera.zoom <= 0.6)
                    Text("\(Int((camera.zoom * 100).rounded()))%").font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(.secondary).frame(width: 42)
                    Button { camera.zoom += 0.15 } label: { Image(systemName: "plus") }
                        .help(localization.text("graph.zoom_in")).accessibilityLabel(localization.text("graph.zoom_in"))
                        .disabled(camera.zoom >= 2.5)
                    Button { camera = .init() } label: { Image(systemName: "viewfinder") }
                        .help(localization.text("graph.fit")).accessibilityLabel(localization.text("graph.fit"))
                }.controlSize(.small).buttonStyle(.borderless).padding(7).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 6))
                    .padding(12)
            }
            .clipped()
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func relationEdge(_ relation: KnowledgeRelationV1, source: CGPoint, target: CGPoint) -> some View {
        let parallel = relations.filter { Set([$0.source, $0.target]) == Set([relation.source, relation.target]) }.sorted { $0.id < $1.id }
        let index = parallel.firstIndex(where: { $0.id == relation.id }) ?? 0
        let lane = (CGFloat(index) - CGFloat(parallel.count - 1) / 2) * 50
        let control = KnowledgeRelationLayout.controlPoint(from: source, to: target, lane: lane)
        let path = Path { path in path.move(to: source); path.addQuadCurve(to: target, control: control) }
        let selected = selectedRelationID == relation.id, hovered = hoveredRelationID == relation.id
        let connected = focusedPaperKey == nil || [relation.source, relation.target].contains(focusedPaperKey ?? "")
        let label = localization.text("graph.relation_kind.\(relation.kind.rawValue)")
        let midpoint = CGPoint(x: (source.x + target.x + 2 * control.x) / 4, y: (source.y + target.y + 2 * control.y) / 4)
        return ZStack {
            path.stroke(relation.kind.tint.opacity(selected || hovered ? 1 : connected ? 0.55 : 0.12),
                style: StrokeStyle(lineWidth: selected || hovered ? 2.5 : 1.5,
                    dash: relation.basis == .synthesis ? [5, 4] : []))
            Button { selectRelation(relation.id) } label: {
                path.stroke(.clear, lineWidth: 18)
                    .contentShape(path.strokedPath(.init(lineWidth: 18)))
            }.buttonStyle(.plain).help(label)
                .accessibilityLabel(accessibleLabel(relation, label: label))
                .onHover { hoveredRelationID = $0 ? relation.id : nil }
            if selected || hovered || relations.count == 1 {
                Button { selectRelation(relation.id) } label: {
                    Text(label).font(.system(size: 12)).foregroundStyle(relation.kind.tint)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 4))
                }.buttonStyle(.plain).position(midpoint)
            }
        }
    }

    private func isRelated(_ id: String) -> Bool {
        if let selected = relations.first(where: { $0.id == selectedRelationID }) {
            return [selected.source, selected.target].contains(id)
        }
        guard let focus = focusedPaperKey else { return true }
        return focus == id || relations.contains { [$0.source, $0.target].contains(id) && [$0.source, $0.target].contains(focus) }
    }
    private func shortTitle(_ title: String) -> String {
        let prefix = String(title.split(separator: ":", maxSplits: 1).first ?? Substring(title))
        return prefix.count >= 4 && prefix.count <= 40 ? prefix : title
    }
    private func accessibleLabel(_ relation: KnowledgeRelationV1, label: String) -> String {
        let titles = [relation.source, relation.target].compactMap { key in papers.first { $0.id == key }?.title }
        return (titles + [label]).joined(separator: " · ")
    }
}
