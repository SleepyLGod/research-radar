import AppKit
import ResearchRadarCore
import SwiftUI

extension AppAppearancePreference {
    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }

    var appKitAppearance: NSAppearance? {
        switch self {
        case .system: nil
        case .light: NSAppearance(named: .aqua)
        case .dark: NSAppearance(named: .darkAqua)
        }
    }
}

struct AppAppearancePicker: View {
    let store: AppStore
    let localization: LocalizationStore

    var body: some View {
        Picker(localization.text("appearance.label"), selection: Binding(
            get: { store.configuration.uiAppearance },
            set: { value in store.performAction { try store.setUIAppearance(value) } }
        )) {
            ForEach(AppAppearancePreference.allCases, id: \.self) { appearance in
                Text(localization.text("appearance.\(appearance.rawValue)")).tag(appearance)
            }
        }.pickerStyle(.segmented)
    }
}
