import AppKit
import SwiftUI
import ResearchRadarCore
import Observation

@MainActor @Observable
public final class WindowPresentationState {
    public var isVisible = true
    var requestedSection: WorkspaceSection?
    var requestedReportID: UUID?
    public init() {}
}

@MainActor
public final class WindowCoordinator: NSObject, NSPopoverDelegate {
    public let popover = NSPopover()
    public var contentView: NSView { popover.contentViewController!.view }
    public var window: NSWindow? { contentView.window }
    public var onVisibilityChange: ((Bool) -> Void)?
    private var mode: WindowMode = .compact
    private weak var anchor: NSView?
    private var escapeMonitor: Any?

    public init(content: () -> AnyView) {
        let hosting = NSHostingView(rootView: content())
        hosting.sizingOptions = []
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 400, height: 480))
        hosting.frame = container.bounds
        hosting.autoresizingMask = [.width, .height]
        container.addSubview(hosting)
        let controller = NSViewController()
        controller.view = container
        popover.contentViewController = controller
        popover.contentSize = container.frame.size
        popover.behavior = .transient
        super.init()
        popover.delegate = self
    }

    public func attach(to anchor: NSView) { self.anchor = anchor }

    public func setAppearance(_ preference: AppAppearancePreference) {
        let appearance = preference.appKitAppearance
        NSApplication.shared.appearance = appearance
        popover.appearance = appearance
        contentView.appearance = appearance
        window?.appearance = appearance
    }

    public func show() {
        guard let anchor, anchor.window != nil else { return }
        present(mode: mode, animated: false)
        NSApp.activate()
        if !popover.isShown {
            popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minY)
        }
        window?.makeKey()
        onVisibilityChange?(true)
        if escapeMonitor == nil {
            escapeMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self, event.keyCode == 53, event.window === self.window,
                      self.window?.attachedSheet == nil else { return event }
                self.close()
                return nil
            }
        }
    }

    public func toggle() { popover.isShown ? close() : show() }

    public func close() {
        onVisibilityChange?(false)
        popover.performClose(nil)
        removeMonitor()
    }

    public static func contentSize(for mode: WindowMode, available: NSSize) -> NSSize {
        let preferred = mode == .compact ? NSSize(width: 400, height: 480) : NSSize(width: 900, height: 660)
        return NSSize(width: min(preferred.width, max(1, available.width - 24)),
                      height: min(preferred.height, max(1, available.height - 32)))
    }

    public func present(mode: WindowMode, animated: Bool = true) {
        self.mode = mode
        let available = anchor?.window?.screen?.visibleFrame.size ?? NSSize(width: 1024, height: 768)
        popover.animates = animated && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        let size = Self.contentSize(for: mode, available: available)
        if popover.contentSize != size { popover.contentSize = size }
    }

    public func popoverShouldDetach(_ popover: NSPopover) -> Bool { false }

    public func popoverDidClose(_ notification: Notification) {
        onVisibilityChange?(false)
        removeMonitor()
    }

    private func removeMonitor() {
        if let escapeMonitor { NSEvent.removeMonitor(escapeMonitor) }
        escapeMonitor = nil
    }
}
