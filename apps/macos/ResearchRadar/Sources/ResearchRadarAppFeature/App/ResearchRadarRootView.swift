import AppKit
import ResearchRadarCore
import SwiftUI

public struct ResearchRadarRootView: View {
    @Bindable private var store: AppStore
    @Bindable private var localization: LocalizationStore
    @Bindable private var presentation: WindowPresentationState
    @State private var workspaceOpened = false

    public init(store: AppStore, localization: LocalizationStore, presentation: WindowPresentationState = WindowPresentationState()) {
        self.store = store
        self.localization = localization
        self.presentation = presentation
    }

    public var body: some View {
        let mode = presentation.windowMode(saved: store.runtime.windowMode)
        Group {
            if store.requiresOnboarding {
                TopicOnboardingView(store: store, localization: localization)
            } else {
                ZStack {
                    // Keep editable view state while compact or dismissed, but release its reader.
                    if workspaceOpened || mode == .full {
                        RetainedWorkspaceView(store: store, localization: localization,
                            presentation: presentation, isVisible: mode == .full)
                    }
                    if mode == .compact {
                        CompactTodayView(store: store, localization: localization, presentation: presentation)
                    }
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            AppActionErrorView(store: store, localization: localization).padding(.horizontal, 16)
        }
        .font(.system(size: 13))
        .controlSize(.regular)
        .preferredColorScheme(store.configuration.uiAppearance.colorScheme)
        .clipped()
        .onAppear { if mode == .full { workspaceOpened = true } }
        .onChange(of: mode) { _, mode in
            if mode == .full { workspaceOpened = true }
        }
    }
}

private struct RetainedWorkspaceView: NSViewRepresentable {
    let store: AppStore
    let localization: LocalizationStore
    let presentation: WindowPresentationState
    let isVisible: Bool

    func makeNSView(context: Context) -> NSView {
        let host = NSHostingView(rootView:
            FullWorkspaceView(store: store, localization: localization, presentation: presentation)
                .font(context.environment.font)
                .controlSize(context.environment.controlSize)
        )
        host.sizingOptions = []
        host.autoresizingMask = [.width, .height]
        let container = NSView()
        container.addSubview(host)
        return container
    }

    func updateNSView(_ container: NSView, context: Context) {
        // The hosted view observes its long-lived stores without replacing its root.
        // Opacity and hit testing do not remove native lists from the key-view loop.
        container.isHidden = !isVisible
    }
}
