import AppKit
import ResearchRadarCore
import WebKit

@MainActor
final class ReportReaderHost: NSView, WKNavigationDelegate, WKUIDelegate {
    private(set) var webView: WKWebView?
    private(set) var errorKey: String?
    var onError: ((String?) -> Void)?
    private var policy: ReportReaderPolicy?
    private var identity: [String]?
    private var generation = UUID()
    private var preparation: Task<Void, Never>?
    private var memoryPressure: (any DispatchSourceMemoryPressure)?
    private let openExternal: (URL) -> Void

    init(openExternal: @escaping (URL) -> Void = { NSWorkspace.shared.open($0) }) {
        self.openExternal = openExternal
        super.init(frame: .zero)
    }
    required init?(coder: NSCoder) { nil }

    func requestDisplay(_ report: ReportRecordV1, workspaceRoot: URL) {
        let next = [workspaceRoot.absoluteString, report.runDirectory, report.reportHTMLPath]
        guard next != identity else { return }
        preparation?.cancel()
        preparation = Task { [weak self] in await self?.display(report, workspaceRoot: workspaceRoot) }
    }

    func display(_ report: ReportRecordV1, workspaceRoot: URL) async {
        guard !Task.isCancelled else { return }
        let next = [workspaceRoot.absoluteString, report.runDirectory, report.reportHTMLPath]
        guard next != identity else { return }
        releaseReader(cancelPreparation: false)
        identity = next
        setError(nil)
        let token = generation
        do {
            let validated = try ReportReaderPolicy(report: report, workspaceRoot: workspaceRoot)
            // Install a default-deny rule before creating/loading any document.
            // Only the private, validated scheme may fetch subresources.
            // The default rule store may persist this compiled filter, not page
            // data. The WebView itself always uses a nonpersistent data store.
            let rules = try await WKContentRuleListStore.default().compileContentRuleList(
                forIdentifier: "ResearchRadar.RestrictedReader.v1",
                encodedContentRuleList: """
                [{"trigger":{"url-filter":".*"},"action":{"type":"block"}},
                 {"trigger":{"url-filter":"^radar-report://run/"},"action":{"type":"ignore-previous-rules"}}]
                """
            )
            guard generation == token, !Task.isCancelled else { return }
            guard let rules else { throw ReportReaderPolicy.Failure.deniedResource }
            let configuration = WKWebViewConfiguration()
            configuration.websiteDataStore = .nonPersistent()
            configuration.defaultWebpagePreferences.allowsContentJavaScript = false
            configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
            configuration.mediaTypesRequiringUserActionForPlayback = .all
            configuration.userContentController.add(rules)
            configuration.setURLSchemeHandler(ReportReaderSchemeHandler(policy: validated) { [weak self] in
                self?.setError("reader.resourceUnavailable")
            }, forURLScheme: ReportReaderPolicy.scheme)
            let web = WKWebView(frame: bounds, configuration: configuration)
            web.autoresizingMask = [.width, .height]
            web.navigationDelegate = self
            web.uiDelegate = self
            web.allowsLinkPreview = false
            policy = validated
            webView = web
            addSubview(web)
            let pressure = DispatchSource.makeMemoryPressureSource(eventMask: [.warning, .critical], queue: .main)
            pressure.setEventHandler { [weak self] in
                MainActor.assumeIsolated { self?.handleMemoryPressure() }
            }
            memoryPressure = pressure
            pressure.resume()
            web.load(URLRequest(url: validated.entryURL))
        } catch {
            guard generation == token, !Task.isCancelled else { return }
            setError(error is ReportReaderPolicy.Failure ? "reader.invalidReport" : "reader.loadFailed")
        }
    }

    func releaseReader(cancelPreparation: Bool = true) {
        generation = UUID()
        if cancelPreparation {
            preparation?.cancel()
            preparation = nil
        }
        memoryPressure?.cancel()
        memoryPressure = nil
        webView?.stopLoading()
        webView?.navigationDelegate = nil
        webView?.uiDelegate = nil
        webView?.removeFromSuperview()
        webView = nil
        policy = nil
        identity = nil
    }

    func handleMemoryPressure() {
        let previous = identity
        releaseReader()
        // Stay unloaded until the parent remounts or selects another report.
        identity = previous
        setError("reader.memoryPressure")
    }

    private func setError(_ key: String?) {
        errorKey = key
        onError?(key)
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 preferences: WKWebpagePreferences,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy, WKWebpagePreferences) -> Void) {
        preferences.allowsContentJavaScript = false
        guard let url = action.request.url, let policy, !action.shouldPerformDownload else {
            decisionHandler(.cancel, preferences)
            return
        }
        let decision = policy.navigation(to: url, userActivated: action.navigationType == .linkActivated,
                                         mainFrame: action.sourceFrame.isMainFrame && (action.targetFrame?.isMainFrame ?? true))
        if decision == .external { openExternal(url) }
        decisionHandler(decision == .allow ? .allow : .cancel, preferences)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationResponsePolicy) -> Void) {
        guard response.isForMainFrame, response.canShowMIMEType, let url = response.response.url else {
            decisionHandler(.cancel)
            return
        }
        decisionHandler(policy?.navigation(to: url, userActivated: false, mainFrame: true) == .allow ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { setError("reader.loadFailed") }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        self.webView(webView, didFail: navigation, withError: error)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        let previous = identity
        releaseReader()
        identity = previous
        setError("reader.loadFailed")
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? { nil }

    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping @MainActor @Sendable (WKPermissionDecision) -> Void) { decisionHandler(.deny) }
}

@MainActor
private final class ReportReaderSchemeHandler: NSObject, WKURLSchemeHandler {
    let policy: ReportReaderPolicy
    let onFailure: () -> Void

    init(policy: ReportReaderPolicy, onFailure: @escaping () -> Void) {
        self.policy = policy
        self.onFailure = onFailure
    }

    func webView(_ webView: WKWebView, start task: any WKURLSchemeTask) {
        do {
            guard let url = task.request.url, task.request.httpMethod == "GET" else {
                throw ReportReaderPolicy.Failure.deniedResource
            }
            let resource = try policy.resource(at: url)
            guard let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: [
                "Content-Type": resource.mimeType == "text/html" ? "text/html; charset=utf-8" : resource.mimeType,
                "Content-Security-Policy": "default-src 'none'; img-src radar-report:; style-src 'unsafe-inline' radar-report:; font-src radar-report:; base-uri 'none'; form-action 'none'; frame-src 'none'; script-src 'none'",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store"
            ]) else { throw ReportReaderPolicy.Failure.deniedResource }
            task.didReceive(response)
            task.didReceive(resource.data)
            task.didFinish()
        } catch {
            task.didFailWithError(error)
            onFailure()
        }
    }

    func webView(_ webView: WKWebView, stop task: any WKURLSchemeTask) {}
}
