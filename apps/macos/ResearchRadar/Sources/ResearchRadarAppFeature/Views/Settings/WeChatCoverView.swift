import AppKit
import ResearchRadarCore
import SwiftUI
import UniformTypeIdentifiers

struct WeChatCoverView: View {
    let store: AppStore
    let localization: LocalizationStore
    @State private var choosing = false
    @State private var confirmation: WeChatCoverConfirmation?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if store.isUploadingWeChatCover {
                ProgressView(localization.text("stage.wechat_cover")).controlSize(.small)
            }
            HStack {
                Button(localization.text("cover.choose"), systemImage: "photo.badge.plus") { choosing = true }
                    .accessibilityIdentifier("cover.choose")
                if store.selectedWeChatCover != nil {
                    Button(localization.text("cover.upload"), systemImage: "arrow.up.doc") {
                        do { confirmation = try store.prepareWeChatCoverUpload() }
                        catch { store.showWeChatCoverError(error) }
                    }.accessibilityIdentifier("cover.upload")
                }
            }
            if let image = store.selectedWeChatCover {
                CoverPreview(image: image)
            }
            Text(localization.text("cover.requirements"))
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let receipt = store.coverUploadReceipt {
                let saved = store.configuration.delivery.wechat.thumbMediaID == receipt.mediaID
                Label(localization.text(saved ? "cover.saved" : "cover.save_failed"),
                    systemImage: saved ? "checkmark.circle" : "exclamationmark.triangle")
                Text(receipt.mediaID).font(.system(size: 12, design: .monospaced))
                    .textSelection(.enabled).lineLimit(3)
                if !saved {
                    Button(localization.text("cover.save_only"), systemImage: "square.and.arrow.down") {
                        do { try store.saveUploadedWeChatCover() }
                        catch { store.showWeChatCoverError(error, fallback: "wechat_cover_save_failed") }
                    }
                }
            } else if store.coverUploadUncertain {
                Text(localization.text("cover.unknown")).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .disabled(store.behaviorChangesBlocked)
        .fileImporter(isPresented: $choosing, allowedContentTypes: [.png, .jpeg]) { result in
            switch result {
            case .success(let url):
                do { try store.selectWeChatCover(from: url) }
                catch { store.showWeChatCoverError(error) }
            case .failure(let error):
                if (error as? CocoaError)?.code != .userCancelled { store.showWeChatCoverError(error) }
            }
        }
        .sheet(item: $confirmation) { value in
            WeChatCoverConfirmationView(confirmation: value, localization: localization,
                cancel: { confirmation = nil }, upload: {
                    confirmation = nil
                    Task { await store.uploadWeChatCover(value) }
                })
        }
    }
}

private struct CoverPreview: View {
    let image: WeChatCoverImage
    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            if let preview = NSImage(data: image.previewData) {
                Image(nsImage: preview).resizable().scaledToFit().frame(width: 150, height: 96)
                    .accessibilityLabel(image.filename)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(image.filename).lineLimit(2)
                Text("\(image.width) × \(image.height) · \(ByteCountFormatter.string(fromByteCount: Int64(image.data.count), countStyle: .file))")
                    .font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct WeChatCoverConfirmationView: View {
    let confirmation: WeChatCoverConfirmation
    let localization: LocalizationStore
    let cancel: () -> Void
    let upload: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(localization.text("cover.confirm_title"), systemImage: "photo.badge.arrow.down")
                .font(.headline)
            CoverPreview(image: confirmation.image)
            Text(localization.text("cover.confirm_detail")).fixedSize(horizontal: false, vertical: true)
            if confirmation.uncertainPriorUpload {
                Label(localization.text("cover.unknown"), systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                Button(localization.text("action.cancel"), action: cancel).keyboardShortcut(.cancelAction)
                Button(localization.text("cover.upload"), action: upload)
                    .keyboardShortcut(.defaultAction).accessibilityIdentifier("cover.confirm_upload")
            }
        }.font(.system(size: 13)).padding(20).frame(width: 420)
    }
}
