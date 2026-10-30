import SwiftUI

/// Empty results occupy the content area without moving the workspace toolbar.
struct WorkspaceEmptyState: View {
    let title: String
    let symbol: String
    var clearTitle: String?
    var clearFilters: (() -> Void)?

    var body: some View {
        VStack(spacing: 12) {
            Label(title, systemImage: symbol)
                .font(.system(size: 14)).foregroundStyle(.secondary)
            if let clearTitle, let clearFilters {
                Button(clearTitle, action: clearFilters).controlSize(.small)
            }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
