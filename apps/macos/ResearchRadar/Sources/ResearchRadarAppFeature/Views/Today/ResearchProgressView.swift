import SwiftUI

struct ResearchProgressView: View {
    let progress: ResearchProgressPresentation
    let compact: Bool
    let localization: LocalizationStore

    var body: some View {
        HStack(alignment: .top, spacing: compact ? 8 : 16) {
            ForEach(progress.steps) { step in
                VStack(alignment: .leading, spacing: 7) {
                    Image(systemName: step.symbol).font(.system(size: 17)).frame(height: 20)
                    Text(localization.text(compact ? "stage_short.\(step.stage.rawValue)" : step.stage.localizationKey))
                        .font(.system(size: 12, weight: step.state == .unreported ? .regular : .medium))
                        .fixedSize(horizontal: false, vertical: true)
                    if let key = step.statusKey {
                        Text(localization.text(key)).font(.system(size: 12))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .foregroundStyle(color(for: step.state))
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .overlay(alignment: .topLeading) {
                    Rectangle().fill(color(for: step.state).opacity(step.state == .unreported ? 0.15 : 0.8))
                        .frame(height: 2).accessibilityHidden(true)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .accessibilityLabel(localization.text("label.research_progress"))
    }

    private func color(for state: ResearchProgressPresentation.StepState) -> Color {
        switch state {
        case .unreported: .secondary
        case .current: .teal
        case .stopping, .stopped: .orange
        }
    }
}
