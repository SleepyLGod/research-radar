import SwiftUI

struct PaperProgressView: View {
    let rows: [PaperProgressRow]
    let compact: Bool
    let localization: LocalizationStore
    @State private var showsExplanation = false

    var body: some View {
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 6) {
                    Text(localization.text("paper_progress.heading"))
                        .font(.system(size: 12, weight: .medium)).foregroundStyle(.secondary)
                    Button { showsExplanation.toggle() } label: {
                        Image(systemName: "info.circle")
                    }
                    .buttonStyle(.borderless)
                    .help(localization.text("paper_progress.about"))
                    .accessibilityLabel(localization.text("paper_progress.about"))
                    .popover(isPresented: $showsExplanation) {
                        Text(localization.text("paper_progress.boundary"))
                            .font(.system(size: 13))
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(16).frame(width: 300, alignment: .leading)
                    }
                }
                ForEach(rows) { row in
                    Divider()
                    VStack(alignment: .leading, spacing: 7) {
                        Text(row.title).font(.system(size: 13, weight: .medium))
                            .lineLimit(compact ? 2 : 3).help(row.title)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Label(localization.text(row.statusKey), systemImage: row.symbol)
                            .font(.system(size: 12))
                            .foregroundStyle(row.isWarning ? Color.orange : row.isActive ? Color.teal : Color.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(row.title + ". " + localization.text(row.statusKey))
                }
            }
            .accessibilityIdentifier("research-paper-progress")
        }
    }
}
