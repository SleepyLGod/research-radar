# ResearchRadar Architecture

ResearchRadar is split into narrow subsystems so each risky boundary is explicit. The current
repo is the v0.0.0 foundation: a local-first system with testable research runs, privacy
guardrails, typed models, evidence-gated deep reading, and draft-only publishing.

## Subsystems

- `scheduler`: local and Codex automation entrypoints.
- `discovery`: source connectors for papers, repositories, RSS/blogs, and web search adapters.
- `ingestion`: source-aware PDF, HTML, and repository extraction with provenance and full-paper
  completeness checks.
- `analysis`: task-level model routes plus concrete OpenAI-compatible, Anthropic, Codex CLI,
  Claude Code CLI, and local/static provider instances.
- `evidence`: claim ledger and unsupported-claim policy.
- `compose`: platform-neutral article drafts plus Markdown, WeChat, and future channel renderers.
- `publishers.wechat`: WeChat Official Account draft API client.
- `publishers.zhihu`: placeholder boundary for future Zhihu integration.
- `storage`: run directories, manifests, and encrypted state.
- `security`: secrets, encryption, redaction, and privacy scanning.

WeChat and Zhihu are downstream publishing channels. They should not define the core research
model; platform-neutral evidence and article drafts come first.

## Canonical E2E Flow

1. Topic setup defines topic id, queries, priority sources, and cadence.
2. Planner expands the topic into neutral scope, research questions, source priorities, and risks.
3. Discovery produces normalized `SourceCandidate` records from papers, repositories, RSS/blogs,
   and later open web sources.
4. Wide scan clusters and ranks candidates, then selects sources for deep reading.
5. Ingestion stores PDFs, HTML pages, and repository metadata as artifacts with provenance; research
   briefs reject abstract-only HTML as successful deep reads.
6. Deep research reading applies the ResearchRadar skill to area context, problem/solution,
   related work, limitations, critique, examples, and essence.
7. Evidence ledger converts claims into source-anchored records and rejects unsupported claims.
8. Review checks hallucination risk, overclaiming, weak evidence, and unsupported critique.
9. Synthesis outline / prewriting asks perspective-guided questions and outlines before drafting.
10. `ArticleDraft` assembles verified claims into a platform-neutral draft.
11. Rendering transforms the same draft into Markdown, WeChat HTML, or future channel formats.
12. Manual publishing creates a WeChat draft only after review; auto-publish is out of scope.
13. Audit artifacts preserve manifests, sources, artifacts, claims, evidence, rendered output, and
   review reports under `runs/`.

## Extension Points

Add a new source by implementing `DiscoveryConnector`.
Add a new model by implementing `LLMProvider`.
Add a new publisher by implementing a package under `publishers`.

## Research Skill

The project skill at `docs/skills/research-radar/SKILL.md` defines the required research behavior
contract: planner, wide scan, deep reading, prewriting, and publishing discipline. It should be
used before changing analysis prompts or adding new research workflows.

## Figure Policy

Public article figures should default to self-drawn explanatory diagrams derived from verified
claims. Original paper figures may be used only when license/source metadata supports reuse or a
human reviewer explicitly approves it for the target channel. Every reused figure must keep
attribution to the paper, authors when available, source URL or arXiv id, and known license.

arXiv source files can include TeX/LaTeX and figures, and arXiv OAI metadata can expose license
information. This does not mean every arXiv figure is automatically safe for public reuse: the
default arXiv license gives arXiv distribution rights, while third-party reuse depends on the
paper's selected license and attribution requirements.

For PDF-only papers, figure extraction is conservative. ResearchRadar may crop a figure region only
when it can bind a caption to the same paper and compute a credible crop; it must not publish a full
PDF page as if it were a figure. If a safe crop is unavailable, the public draft simply omits the
figure section and keeps diagnostics in audit artifacts.
