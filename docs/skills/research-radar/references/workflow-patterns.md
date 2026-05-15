# ResearchRadar Workflow Patterns

This reference records external workflow ideas that ResearchRadar may borrow without making those
projects default runtime dependencies.

## GPT Researcher

Source: https://github.com/assafelovic/gpt-researcher

- Use a finite planner-executor-publisher shape instead of open-ended agent loops.
- Turn a broad user topic into concrete research questions before searching.
- Gather source-level summaries with provenance before final writing.
- Respect the requested report language through the whole synthesis path.
- Write the final report only from gathered information, not from model memory.
- Parallel execution can improve speed, but ResearchRadar treats it as optional.

## STORM

Sources:

- https://github.com/stanford-oval/storm
- https://storm-project.stanford.edu/research/storm/

- Use perspective-guided question asking to improve breadth and depth.
- Simulate follow-up questions when retrieved answers change the system's understanding.
- Generate an outline from collected references before writing long-form output.
- Watch for red herrings, source-bias transfer, and weakly connected facts.
- Treat the prewriting stage as a quality gate, not a cosmetic step.

## PaperQA2

Source: https://github.com/Future-House/paper-qa

- Prefer explicit metadata and manifests over inferred paper identity when possible.
- Gather evidence passages before answering.
- Summarize passages in relation to the query before final synthesis.
- Require citations or anchors in scientific answers.
- Treat PaperQA2 as an optional future backend, not the default ResearchRadar engine.

## LangChain Open Deep Research

Source: https://github.com/langchain-ai/open_deep_research

- Preserve source metadata through research, summarization, and report writing.
- Keep the report language aligned with the user-requested language.
- Separate research-topic clarification from evidence collection and final synthesis.
- Treat workflow shape and prompt principles as inspiration only; do not vendor prompts.

## Graphify

Graphify remains optional support only.

- Useful for raw-folder discipline, manifests, cache, corpus graph, clustering, and provenance tags.
- Helpful for finding cross-document relationships.
- Not authoritative for interpreting a paper, evaluating novelty, or proving a claim.
