# Security Model

ResearchRadar assumes research interests, source lists, draft notes, and publishing credentials
are private. The repository protects credentials and public-output boundaries, but it is not an
encrypted document store.

## Secrets

Secrets are stored through the configured secret backend. The recommended local backend is macOS
Keychain via `keyring`. Secrets must not be written to repo files, scheduler metadata, logs,
prompts, or generated articles.

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

## License Hygiene

The repo is MIT-licensed, but local secrets, generated runs, source history, schedule state, token
caches, and user preferences are not publishable artifacts and remain gitignored.
