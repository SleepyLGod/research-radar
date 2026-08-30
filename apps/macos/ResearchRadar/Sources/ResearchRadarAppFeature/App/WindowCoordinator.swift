import AppKit
import SwiftUI

@MainActor
public final class WindowCoordinator: NSObject, NSWindowDelegate {
    public let window: NSWindow

    public init(content: () -> AnyView) {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 360),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "ResearchRadar"
        window.isReleasedWhenClosed = false
        window.center()
        window.contentView = NSHostingView(rootView: content())
        self.window = window
        super.init()
        window.delegate = self
    }

    public func show() {
        NSApp.activate()
        window.makeKeyAndOrderFront(nil)
    }

    public func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }
}
