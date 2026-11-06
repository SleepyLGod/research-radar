import SwiftUI

struct PaperReadingControls: View {
    let papers: [ReportContents.Paper]
    let selected: ReportContents.Paper
    let sections: [PaperReadingSection]
    let localization: LocalizationStore
    let select: (Int) -> Void
    let jump: (PaperReadingSection.ID) -> Void

    var body: some View {
        HStack(spacing: 12) {
            Text(localization.text("paper.switch")).foregroundStyle(.secondary)
            Picker(localization.text("paper.switch"), selection: Binding(
                get: { selected.id }, set: { select($0) }
            )) {
                ForEach(papers) { paper in Text(paper.title).lineLimit(1).tag(paper.id) }
            }
            .labelsHidden().pickerStyle(.menu)
            .frame(maxWidth: .infinity, alignment: .leading)
            .help(selected.title)
            .accessibilityIdentifier("paper.switch")
            Menu {
                ForEach(sections) { section in
                    Button(localization.text(section.titleKey)) { jump(section.id) }
                }
            } label: {
                Label(localization.text("paper.jump"), systemImage: "list.bullet")
            }
            .fixedSize()
            .accessibilityIdentifier("paper.jump")
        }
        .font(.system(size: 13)).controlSize(.small)
        .frame(minWidth: 320)
        .padding(.horizontal, 20).padding(.vertical, 10)
    }
}
