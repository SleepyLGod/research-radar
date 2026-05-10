# Security Model

ResearchRadar assumes research interests, source lists, draft notes, and publishing credentials
are private.

## Secrets

Secrets are stored through the configured secret backend. The local backend is macOS Keychain via
`keyring`. Secrets must not be written to repo files, logs, prompts, or generated articles.

## Encrypted Runtime State

Sensitive runtime state is encrypted with envelope encryption:

- A master key is stored in Keychain or a cloud secret manager.
- Each encrypted payload gets a random data key.
- The data key is wrapped with the master key.
- Payload data is encrypted with AES-GCM.

## Redaction

Logs are passed through the redactor before display. The privacy scanner fails on common secret
patterns, local absolute paths, access tokens, and private identifiers.

## Publishing Safety

The planned v1 publishing boundary only creates WeChat drafts. Auto-publish is deliberately out
of scope.

## License Hygiene

The repo is MIT-licensed, but local secrets, generated runs, encrypted state, and user preference
data are not publishable artifacts and remain gitignored.
