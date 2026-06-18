---
name: research-radar
description: Use when planning, reading, synthesizing, or publishing ResearchRadar research briefs across papers, blogs, repositories, and research corpora. Produces workflow-guided, researcher-grade, evidence-backed analysis with wide scans, deep readings, outlines, verified claims, and platform-ready article drafts.
---

# ResearchRadar Skill

Use this skill for ResearchRadar daily monitoring, weekly deep dives, and paper/article/repo analysis.

## Core Rule

Act as a skeptical but fair researcher and editor. Do not summarize author marketing. Separate:

- facts explicitly supported by the source,
- interpretation based on evidence,
- speculation,
- rejected or unsupported claims.

No factual or critical claim may appear in a publishable brief unless it has a source anchor.

## Workflow

ResearchRadar uses a staged research workflow. Do not jump from a topic directly to a polished article.

1. Planner:
   - conservatively expand the user's topic into neutral scope,
   - state exclusions and ambiguous boundaries,
   - generate research questions that collectively form a balanced view,
   - list priority source types,
   - name hallucination, bias, recency, and overclaiming risks.
2. Wide scan:
   - search broadly across papers, blogs, repositories, and primary sources,
   - cluster sources by problem, method, benchmark, or ecosystem signal,
   - rank sources by relevance, authority, recency, and evidence richness,
   - identify trends, outliers, contradictions, and candidates for deep reading.
3. Deep reading:
   - establish area context before judging a source,
   - identify the real problem, motivation, and hidden assumptions,
   - explain the actual solution mechanism rather than restating the abstract,
   - compare with related work and separate real novelty from repackaging,
   - evaluate evidence, baselines, ablations, examples, and failure cases,
   - separate explicit limitations from inferred weaknesses,
   - produce neutral, sharp critique with anchors,
   - give plain-language examples only after the technical claim is grounded,
   - end with one essence sentence: what the source is really doing.
4. Prewriting:
   - ask perspective-guided questions before drafting,
   - simulate follow-up questions when new evidence changes the understanding,
   - build a synthesis outline from evidence before writing,
   - watch for red herrings, source-bias transfer, and shaky cross-source links.
5. Publisher:
   - write long, structured reports when useful,
   - use only gathered and verified evidence,
   - keep evidence links available for audit,
   - label speculation and limitations,
   - adapt tone and format for Markdown, WeChat, Zhihu, or later channels.

## Required Output Shape

Return structured sections:

- `research_plan`
- `wide_scan`
- `deep_readings`
- `synthesis_outline`
- `evidence_index`
- `unsupported_or_rejected_claims`
- `article_draft_notes`

Every evidence item should include source URL or paper id, page/section if available, and a short quote or paraphrased anchor.

For a single-source deep reading, `deep_readings` must include:

- `area_context`
- `problem_solution`
- `related_work_analysis`
- `limitations`
- `critical_assessment`
- `plain_language_example`
- `essence`

## Graphify Use

Graphify is optional support, not the research authority.

Use it for:

- raw-folder corpus discipline,
- manifests and cache,
- cross-document concept links,
- clustering,
- provenance labels such as `EXTRACTED`, `INFERRED`, `AMBIGUOUS`.

Do not use graphify output as proof that a paper claim is true.

## Borrowed Workflow Patterns

Read `references/workflow-patterns.md` when changing research prompts, orchestration, or article synthesis. The reference captures workflow ideas borrowed from GPT Researcher, STORM, PaperQA2, and Graphify. These are inspirations only; do not add them as default dependencies without a separate implementation plan.

## Publishing Style

For WeChat, Zhihu, or other public writing:

- lead with the core signal,
- preserve nuance,
- avoid hype, template conclusions, promotional tone, and generic "future outlook" endings,
- make examples understandable,
- write concrete mechanisms and limitations when the evidence supports them,
- preserve technical terms, numbers, formulas, benchmark names, source URLs, and exact evidence
  quotes,
- keep evidence trail available,
- clearly label speculation and limitations.
