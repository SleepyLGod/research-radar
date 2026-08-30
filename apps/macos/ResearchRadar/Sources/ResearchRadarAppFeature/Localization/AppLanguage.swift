import Foundation
import Observation
import ResearchRadarCore

private final class NotificationObserver: @unchecked Sendable {
    let token: NSObjectProtocol

    init(_ token: NSObjectProtocol) {
        self.token = token
    }

    deinit {
        NotificationCenter.default.removeObserver(token)
    }
}

public enum AppLanguageResolver {
    public static func resolve(preferredLanguages: [String]) -> ResolvedAppLanguage {
        guard let first = preferredLanguages.first?.lowercased() else { return .english }
        return first == "zh" || first.hasPrefix("zh-") ? .simplifiedChinese : .english
    }

    public static func resolve(
        preference: AppLanguagePreference,
        preferredLanguages: [String]
    ) -> ResolvedAppLanguage {
        switch preference {
        case .system:
            resolve(preferredLanguages: preferredLanguages)
        case .simplifiedChinese:
            .simplifiedChinese
        case .english:
            .english
        }
    }
}

@MainActor
@Observable
public final class LocalizationStore {
    @ObservationIgnored
    public var onChange: (() -> Void)?

    public var preference: AppLanguagePreference {
        didSet { refresh() }
    }

    public private(set) var resolvedLanguage: ResolvedAppLanguage
    private let preferredLanguages: @MainActor () -> [String]
    private var languageBundle: Bundle
    @ObservationIgnored
    private var localeObserver: NotificationObserver?

    public init(
        preference: AppLanguagePreference = .system,
        preferredLanguages: @escaping @MainActor () -> [String] = { Locale.preferredLanguages }
    ) {
        self.preference = preference
        self.preferredLanguages = preferredLanguages
        let resolved = AppLanguageResolver.resolve(
            preference: preference,
            preferredLanguages: preferredLanguages()
        )
        self.resolvedLanguage = resolved
        self.languageBundle = Self.bundle(for: resolved)
        let token = NotificationCenter.default.addObserver(
            forName: NSLocale.currentLocaleDidChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                if self.preference == .system {
                    self.refresh()
                }
            }
        }
        self.localeObserver = NotificationObserver(token)
    }

    public func text(_ key: String) -> String {
        languageBundle.localizedString(forKey: key, value: key, table: nil)
    }

    public func refresh() {
        let resolved = AppLanguageResolver.resolve(
            preference: preference,
            preferredLanguages: preferredLanguages()
        )
        resolvedLanguage = resolved
        languageBundle = Self.bundle(for: resolved)
        onChange?()
    }

    private static func bundle(for language: ResolvedAppLanguage) -> Bundle {
        let resources = localizationResources
        guard let resourceURL = resources.resourceURL else { return resources }
        let languageURL = resourceURL.appending(
            path: "\(language.rawValue).lproj",
            directoryHint: .isDirectory
        )
        guard let bundle = Bundle(url: languageURL)
        else {
            return resources
        }
        return bundle
    }

    private static var localizationResources: Bundle {
        #if RESEARCH_RADAR_APP_BUNDLE
        guard let resourceURL = Bundle.main.resourceURL else { return Bundle.main }
        let bundleURL = resourceURL.appending(
            path: "ResearchRadar_ResearchRadarAppFeature.bundle",
            directoryHint: .isDirectory
        )
        return Bundle(url: bundleURL) ?? Bundle.main
        #else
        return Bundle.module
        #endif
    }
}
