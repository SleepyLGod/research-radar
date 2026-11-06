import ResearchRadarCore
import SwiftUI

/// Unframed classification sections; each repeated card opens the same paper and evidence.
struct KnowledgeClassificationCanvas: View {
    let sections: [KnowledgeClassificationLayout.Section]
    let localization: LocalizationStore
    @Binding var position: KnowledgeClassificationLayout.Position?
    let selectGroup: (String) -> Void
    let selectPaper: (String) -> Void

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 24) {
                ForEach(sections) { section in
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            if let group = section.group {
                                Button(group.label) { selectGroup(group.id) }
                                    .buttonStyle(.plain).help(localization.text("graph.filter_group"))
                            } else { Text(localization.text("graph.unclassified")) }
                            Text("\(section.papers.count)").font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                            Spacer()
                        }.font(.system(size: 15, weight: .medium))
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 12)], spacing: 12) {
                            ForEach(section.papers) { paper in
                                paperNode(paper)
                                    .id(KnowledgeClassificationLayout.Position(sectionID: section.id, paperKey: paper.id))
                            }
                        }.scrollTargetLayout()
                    }
                }
            }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
        }.scrollPosition(id: $position, anchor: .top)
    }

    private func paperNode(_ paper: KnowledgePaperV1) -> some View {
        Button { selectPaper(paper.id) } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    if let version = paper.version { Text(version).monospaced() }
                    Spacer()
                    Image(systemName: "chevron.right")
                }.font(.system(size: 12)).foregroundStyle(.secondary)
                Text(paper.title).font(.system(size: 14, weight: .medium)).lineLimit(3)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if !paper.keywords.isEmpty {
                    Text(paper.keywords.prefix(4).map(\.label).joined(separator: " · "))
                        .font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
                }
            }.padding(14).frame(maxWidth: .infinity, minHeight: 128, alignment: .topLeading)
                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.15)))
                .contentShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain).help(paper.title).accessibilityLabel(paper.title)
    }
}
