import SwiftUI

struct PaperProgressView: View {
    let rows: [PaperProgressRow]
    let compact: Bool
    let localization: LocalizationStore

    var body: some View {
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text(localization.text("paper_progress.heading"))
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(.secondary)
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
                Text(localization.text("paper_progress.boundary"))
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityIdentifier("research-paper-progress")
        }
    }
}
