import SwiftUI

public struct FoundationView: View {
    @Bindable private var model: FoundationViewModel
    @Bindable private var localization: LocalizationStore

    public init(model: FoundationViewModel, localization: LocalizationStore) {
        self.model = model
        self.localization = localization
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            header
            statusBand
            Spacer(minLength: 0)
            controls
        }
        .padding(28)
        .frame(minWidth: 480, minHeight: 320)
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "dot.radiowaves.left.and.right")
                .font(.system(size: 23, weight: .semibold))
                .foregroundStyle(Color.accentColor)
                .frame(width: 42, height: 42)
                .background(Color.accentColor.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 3) {
                Text(localization.text("app.name"))
                    .font(.title2.weight(.semibold))
                Text(localization.text("app.subtitle"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Picker("", selection: $localization.preference) {
                Text(localization.text("language.system")).tag(AppLanguagePreference.system)
                Text(localization.text("language.zh-Hans"))
                    .tag(AppLanguagePreference.simplifiedChinese)
                Text(localization.text("language.en")).tag(AppLanguagePreference.english)
            }
            .labelsHidden()
            .accessibilityLabel(localization.text("language.picker_label"))
            .frame(width: 150)
        }
    }

    private var statusBand: some View {
        HStack(spacing: 12) {
            statusIcon
                .font(.system(size: 17, weight: .semibold))
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 4) {
                Text(statusTitle)
                    .font(.headline)
                Text(statusDetail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            Spacer()
        }
        .padding(16)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color(nsColor: .separatorColor), lineWidth: 1)
        }
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch model.state {
        case .ready:
            Image(systemName: "checkmark.circle").foregroundStyle(.secondary)
        case .running:
            ProgressView().controlSize(.small)
        case .succeeded:
            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case .failed:
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
        }
    }

    private var statusTitle: String {
        switch model.state {
        case .ready: localization.text("status.ready")
        case .running: localization.text("status.running")
        case .succeeded: localization.text("status.succeeded")
        case let .failed(code): UserFacingErrorCatalog(localization: localization).message(for: code)
        }
    }

    private var statusDetail: String {
        switch model.state {
        case .ready: localization.text("detail.ready")
        case .running: localization.text("detail.running")
        case .succeeded:
            localization.text("detail.succeeded")
        case .failed: localization.text("detail.failed")
        }
    }

    private var controls: some View {
        HStack {
            Text(localization.text("detail.idle"))
                .font(.caption)
                .foregroundStyle(.tertiary)
            Spacer()
            if model.isRunning {
                Button {
                    Task { await model.cancel() }
                } label: {
                    Label(localization.text("action.cancel"), systemImage: "xmark")
                }
            } else {
                Button {
                    model.runPreflight()
                } label: {
                    Label(localization.text("action.run_preflight"), systemImage: "play.fill")
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }
}
