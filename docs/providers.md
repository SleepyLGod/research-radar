# Provider Configuration

ResearchRadar separates provider setup from task routing. This keeps vendor support small and
predictable: add a provider instance once, then route selected tasks to it.

## Concepts

- Provider instance: a named backend such as `deepseek`, `kimi`, `qwen`, `local-llama`, or
  `claude-code`.
- Provider kind: the wire format used by that backend, such as `openai_compatible`,
  `anthropic_messages`, `codex_cli`, `claude_code_cli`, or `local`.
- Task route: the model used for a task, for example `deep_reading -> deepseek/deepseek-v4-flash`.

The default path remains DeepSeek reader plus Codex verifier. Extra vendors should be configured in
local `config.yaml`, not added to the public `config.example.yaml`.

## Three-Step Provider Setup

1. Define a provider instance in local `config.yaml`.
2. Store the provider secret with `secrets set-named`.
3. Run `provider probe`, then route a task to that provider.

Inspect configured providers without printing secret values:

```bash
uv run research-radar provider list --config config.yaml
```

Inspect the resolved task routes before running a paper or daily job:

```bash
uv run research-radar provider routes --config config.yaml --mode daily
```

## Secrets

Use Keychain for daily runs:

```bash
uv run research-radar secrets set-named kimi.api_key
uv run research-radar secrets status --name kimi.api_key
```

For temporary `.env` experiments, arbitrary named secrets use this form:

```bash
RESEARCH_RADAR_SECRET_KIMI_API_KEY=...
RESEARCH_RADAR_SECRET_QWEN_API_KEY=...
```

Existing shorthand variables such as `DEEPSEEK_API_KEY`, `XIAOMI_API_KEY`, `OPENAI_API_KEY`, and
`WEB_SEARCH_API_KEY` still work.

## OpenAI-Compatible APIs

Use `openai_compatible` for providers that expose Chat Completions compatible endpoints: OpenAI,
DeepSeek, Xiaomi, Kimi, Qwen, Minimax, and many local servers or gateways.

```yaml
model_providers:
  kimi:
    kind: openai_compatible
    base_url: https://<provider-host>/v1/chat/completions
    api_key_secret: kimi.api_key

models:
  task_routes:
    deep_reading:
      provider: kimi
      model: <provider-model-id>
```

Kimi, Qwen, Minimax, and similar vendors fit this template when they expose an OpenAI-compatible
endpoint. Use the vendor's current model id and endpoint from their own dashboard or docs.

OpenAI-compatible providers may also declare explicit thinking controls when their endpoint supports
the same request fields:

```yaml
model_providers:
  deepseek:
    kind: openai_compatible
    base_url: https://api.deepseek.com/chat/completions
    api_key_secret: deepseek.api_key
    thinking: enabled
    reasoning_effort: high
```

`thinking` accepts `enabled` or `disabled`. The configuration layer accepts the common
OpenAI-compatible `reasoning_effort` values `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and
`max`; each endpoint may support only a subset. Leave both fields unset unless the provider documents
them. Configured values are included in provider diagnostics and model-cache identity.

Probe before routing research work:

```bash
uv run research-radar provider probe \
  --config config.yaml \
  --provider kimi \
  --model <provider-model-id> \
  --probe json
```

For a local OpenAI-compatible server:

```yaml
model_providers:
  local-llama:
    kind: openai_compatible
    base_url: http://127.0.0.1:8000/v1/chat/completions
    api_key_secret: local_llm.api_key
```

If the local server ignores auth, store a dummy local secret:

```bash
uv run research-radar secrets set-named local_llm.api_key
```

## Anthropic Messages API

Use `anthropic_messages` only for Anthropic's native Messages API wire format:

```yaml
model_providers:
  anthropic:
    kind: anthropic_messages
    base_url: https://api.anthropic.com/v1/messages
    api_key_secret: anthropic.api_key

models:
  task_routes:
    verifier:
      provider: anthropic
      model: <anthropic-model-id>
```

## CLI Agent Providers

Use command-backed providers when the model is reached through an agent runtime rather than a direct
HTTP API.

Codex CLI verifier:

```yaml
model_providers:
  codex:
    kind: codex_cli
    command: /Applications/ChatGPT.app/Contents/Resources/codex
    timeout_seconds: 900
    reasoning_effort: high

models:
  task_routes:
    verifier:
      provider: codex
      model: gpt-5.6-terra
```

`reasoning_effort` accepts `medium`, `high`, or `xhigh`. To use a different effort for a
specific route, define another named `codex_cli` provider instance and route that task to it.

Claude Code compatible CLI:

```yaml
model_providers:
  claude-code:
    kind: claude_code_cli
    command: claude
    timeout_seconds: 900

models:
  task_routes:
    verifier:
      provider: claude-code
      model: sonnet
```

## Switching Models

Probe a provider before routing real research work to it:

```bash
uv run research-radar provider probe \
  --provider kimi \
  --model <provider-model-id> \
  --probe json
```

Common switches:

```bash
# Only switch the paper reader.
uv run research-radar run paper ... --reader-provider kimi --reader-model <model>

# Let Xiaomi handle tasks that are configured for DeepSeek.
uv run research-radar run daily ... --deepseek-provider xiaomi

# Global experiment: route every model task through one provider/model.
uv run research-radar run daily ... --provider qwen --model <model>
```

Task-specific overrides win over `--deepseek-provider`, and both win over the configured default
routes.

Preview the effect before running:

```bash
uv run research-radar provider routes \
  --config config.yaml \
  --mode daily \
  --deepseek-provider xiaomi
```
