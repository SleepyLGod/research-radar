# Security Model

ResearchRadar assumes research interests, source lists, draft notes, and publishing credentials
are private. The repository protects credentials and public-output boundaries, but it is not an
encrypted document store.

## Secrets

Secrets are stored through the configured secret backend. The recommended local backend is macOS
Keychain via `keyring`. Secrets must not be written to repo files, scheduler metadata, logs,
prompts, or generated articles.

The App saves credentials in Keychain and stores only secret names in its JSON configuration.
Opening Settings or switching language/appearance does not read credential values. A task caches
successful reads only for that task. Different items and requesting executables can require
separate macOS approvals. Local signing has not established reliable authorization across updates;
rebuilding may prompt again even after **Always Allow**. Do not disable Keychain protections or
store plaintext keys to avoid prompts.

## Local Artifacts

Ordinary run artifacts are plaintext local files. This includes `article_draft.json`, source and
reading records, claims, review reports, rendered previews, source history, and scheduler state.
ResearchRadar creates new run, history, and schedule directories with owner-only permissions, but
it does not encrypt every artifact individually.

Use a private root, keep generated data out of Git, and enable FileVault when disk encryption is
required. Do not place a long-running root under a shared or temporary directory.

## Limited Encrypted State

Envelope encryption is used only where the relevant subsystem explicitly opts into encrypted
state, such as a cached WeChat access token. It is not a promise that all generated research files
are encrypted.

## Redaction

Errors written to progress, scheduler state, and publish-failure artifacts are redacted and
truncated. The privacy scanner checks tracked files for common secret patterns, local absolute
paths, access tokens, and private identifiers.

## Publishing Safety

Publishing commands are explicit. WeChat creates a draft for review, Archive publishing updates a
reviewed Git checkout, Zhihu produces a manual export, and private email sends only to the
configured address. ResearchRadar does not auto-publish, mass-send, manage mailing lists, or store
browser cookies for third-party publishing sites.

In the App, delivery is disabled by default. Explicitly enabling a channel allows eligible future
research jobs to enqueue that channel without a separate send confirmation each time. A saved
schedule captures its delivery choices; review and save the schedule again when changing them.
**Email is an actual send**, not a draft. A WeChat draft is not a public publication. Channels keep
independent outcomes, and an unknown result requires checking the inbox or draft box before retrying.
An empty research outcome does not enqueue automatic delivery.

## Local macOS Beta

The App bundles Python but does not bundle Codex, credentials, reports, or user configuration.
Its JSON configuration and workspace are separate from the CLI's YAML configuration. Current local
builds use the development workspace; two copies of the same development App are not isolated user
profiles. Do not run them concurrently against that workspace.

The beta is locally signed, not notarized, and does not enable App Sandbox. Signature and package
checks do not establish downloaded/quarantined Gatekeeper acceptance. Do not disable Gatekeeper or
remove quarantine attributes to work around an unverified installer. Report reading disables
JavaScript and persistent WebView storage, restricts local resources to the selected run, and
hands user-clicked safe web links to the system browser. These controls are not a substitute for
operating-system sandboxing.

## License Hygiene

The repo is MIT-licensed, but local secrets, generated runs, source history, schedule state, token
caches, and user preferences are not publishable artifacts and remain gitignored.
