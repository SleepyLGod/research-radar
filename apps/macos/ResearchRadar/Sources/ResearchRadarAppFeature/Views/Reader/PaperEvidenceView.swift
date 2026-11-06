import SwiftUI

struct PaperEvidenceView: View {
    let claim: ReportContents.Claim
    let localization: LocalizationStore

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(claim.text).font(.system(size: 15)).lineSpacing(5).textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
            if !claim.evidence.isEmpty {
                DisclosureGroup(localization.text("paper.evidence")) {
                    VStack(alignment: .leading, spacing: 14) {
                        ForEach(claim.evidence.indices, id: \.self) { index in
                            let evidence = claim.evidence[index]
                            VStack(alignment: .leading, spacing: 8) {
                                if let location = evidence.location {
                                    Text(location).font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
                                }
                                Text(evidence.quote).font(.system(size: 14)).lineSpacing(5)
                                    .foregroundStyle(.primary).textSelection(.enabled)
                                    .fixedSize(horizontal: false, vertical: true)
                                if let url = evidence.url {
                                    Link(destination: url) {
                                        Label(localization.text("paper.original"), systemImage: "arrow.up.right")
                                    }.font(.system(size: 13)).foregroundStyle(.tint)
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .padding(.leading, 12).padding(.vertical, 10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .overlay(alignment: .leading) { Rectangle().fill(.quaternary).frame(width: 2) }
                }
                .font(.system(size: 13))
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
