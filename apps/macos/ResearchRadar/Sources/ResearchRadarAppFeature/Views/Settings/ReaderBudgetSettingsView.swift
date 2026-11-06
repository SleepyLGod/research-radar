import ResearchRadarCore
import SwiftUI

struct ReaderBudgetSettingsView: View {
    let store: AppStore
    let localization: LocalizationStore

    var body: some View {
        DisclosureGroup(localization.text("setting.reader_budget")) {
            ForEach(routes, id: \.task) { route in
                ReaderBudgetEditor(store: store, localization: localization, route: route)
                    .id("\(route.providerID):\(route.model):\(route.task)")
            }
            Text(localization.text("setting.reader_budget_help"))
                .font(.callout).foregroundStyle(.secondary)
        }
    }

    private var routes: [RouteRecordV1] {
        store.configuration.routes.filter { ["deep_reading", "verifier"].contains($0.task) }
    }
}

private struct ReaderBudgetEditor: View {
    let store: AppStore
    let localization: LocalizationStore
    let route: RouteRecordV1
    @State private var context = ""
    @State private var output = ""
    @State private var overhead = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            LabeledContent(localization.text("check.name.\(route.task)")) {
                Text(route.model).font(.system(.callout, design: .monospaced))
            }
            TextField(localization.text("setting.context_window"), text: $context)
            TextField(localization.text("setting.output_reserve"), text: $output)
            TextField(localization.text("setting.overhead_reserve"), text: $overhead)
            Button(localization.text("action.save")) {
                store.performAction {
                    guard let context = Int(context), let output = Int(output), let overhead = Int(overhead) else {
                        throw AppStoreError.researchConfiguration("reader_context_invalid")
                    }
                    let budget = ReaderContextBudgetV1(contextWindowTokens: context,
                        outputReserveTokens: output, overheadReserveTokens: overhead)
                    do { try budget.validate() }
                    catch { throw AppStoreError.researchConfiguration("reader_context_invalid") }
                    try store.setReaderContextBudget(providerID: route.providerID, model: route.model, budget: budget)
                }
            }
        }
        .disabled(store.behaviorChangesBlocked)
        .onAppear {
            if let budget = store.configuration.providers.first(where: { $0.id == route.providerID })?.readerContexts?[route.model] {
                context = String(budget.contextWindowTokens)
                output = String(budget.outputReserveTokens)
                overhead = String(budget.overheadReserveTokens)
            }
        }
    }
}
