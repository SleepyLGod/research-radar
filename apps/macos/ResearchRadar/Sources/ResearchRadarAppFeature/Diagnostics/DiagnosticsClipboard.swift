import AppKit

@MainActor
enum DiagnosticsClipboard {
    enum CopyError: Error { case unavailable }

    static func copy(from store: AppStore, to pasteboard: NSPasteboard = .general) throws {
        let text = try RedactedDiagnostics.text(for: store)
        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else { throw CopyError.unavailable }
    }
}
