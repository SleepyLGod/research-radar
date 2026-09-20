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
        Group {
            if store.requiresOnboarding {
                TopicOnboardingView(store: store, localization: localization)
            } else {
                ZStack {
                    // Keep editable view state while compact or dismissed, but release its reader.
                    if workspaceOpened || store.runtime.windowMode == .full {
                        FullWorkspaceView(store: store, localization: localization, presentation: presentation)
                            .opacity(store.runtime.windowMode == .full ? 1 : 0)
                            .allowsHitTesting(store.runtime.windowMode == .full)
                            .accessibilityHidden(store.runtime.windowMode != .full)
                    }
                    if store.runtime.windowMode == .compact {
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
        .onAppear { if store.runtime.windowMode == .full { workspaceOpened = true } }
        .onChange(of: store.runtime.windowMode) { _, mode in
            if mode == .full { workspaceOpened = true }
        }
    }
}
