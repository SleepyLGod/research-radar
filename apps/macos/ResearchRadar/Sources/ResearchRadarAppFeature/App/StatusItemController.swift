import AppKit

@MainActor
final class StatusItemController: NSObject {
    private let localization: LocalizationStore
    private let showWindow: () -> Void
    private let runNow: () -> Void
    private let pauseSchedules: () -> Void
    private let schedulesPaused: () -> Bool
    private let quit: () -> Void
    private let statusItem: NSStatusItem

    init(
        localization: LocalizationStore,
        showWindow: @escaping () -> Void,
        runNow: @escaping () -> Void = {},
        pauseSchedules: @escaping () -> Void = {},
        schedulesPaused: @escaping () -> Bool = { false },
        quit: @escaping () -> Void
    ) {
        self.localization = localization
        self.showWindow = showWindow
        self.runNow = runNow
        self.pauseSchedules = pauseSchedules
        self.schedulesPaused = schedulesPaused
        self.quit = quit
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()
        guard let button = statusItem.button else { return }
        button.image = NSImage(
            systemSymbolName: "dot.radiowaves.left.and.right",
            accessibilityDescription: "ResearchRadar"
        )
        button.target = self
        button.action = #selector(handleClick)
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        refresh()
    }

    func refresh() {
        statusItem.button?.toolTip = "ResearchRadar · \(localization.text("status.ready"))"
    }

    @objc private func handleClick() {
        if NSApp.currentEvent?.type == .rightMouseUp {
            statusItem.menu = makeMenu()
            statusItem.button?.performClick(nil)
            statusItem.menu = nil
        } else {
            showWindow()
        }
    }

    private func makeMenu() -> NSMenu {
        let menu = NSMenu()
        let open = NSMenuItem(
            title: localization.text("action.open"),
            action: #selector(openWindow),
            keyEquivalent: ""
        )
        open.target = self
        menu.addItem(open)
        let run = NSMenuItem(
            title: localization.text("action.run_now"), action: #selector(runSelectedTopic), keyEquivalent: "r"
        )
        run.target = self; menu.addItem(run)
        let pause = NSMenuItem(
            title: localization.text(
                schedulesPaused() ? "action.resume_schedules" : "action.pause_schedules"
            ),
            action: #selector(toggleSchedules),
            keyEquivalent: ""
        )
        pause.target = self; menu.addItem(pause)
        menu.addItem(.separator())
        let quit = NSMenuItem(
            title: localization.text("action.quit"),
            action: #selector(quitApplication),
            keyEquivalent: "q"
        )
        quit.target = self
        menu.addItem(quit)
        return menu
    }

    @objc private func openWindow() { showWindow() }
    @objc private func runSelectedTopic() { runNow() }
    @objc private func toggleSchedules() { pauseSchedules() }
    @objc private func quitApplication() { quit() }
}
