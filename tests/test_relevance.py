from research_radar.config import TopicConfig
from research_radar.discovery.relevance import gate_relevant_sources, score_source
from research_radar.evaluation.topic_smoke import DEFAULT_TOPIC_SMOKE_SPECS
from research_radar.models import SourceCandidate, SourceType


def _agent_memory_concept_topic(source_intent: str = "research_brief") -> TopicConfig:
    return TopicConfig(
        id="agent-memory",
        queries=["agent memory systems", "LLM memory benchmark"],
        source_intent=source_intent,
        concept_groups={
            "agent_context": [
                "agent memory",
                "LLM agent memory",
                "agentic memory",
                "autonomous LLM agents",
            ],
            "memory_mechanism": [
                "memory retrieval",
                "agent recall",
                "persistent recall",
                "long-term memory",
                "memory systems",
            ],
            "evaluation_signal": [
                "LOCOMO",
                "LongMemEval",
                "agent memory benchmark",
                "memory evaluation",
            ],
            "negative_compute_or_training": [
                "prefill serving",
                "kv cache",
                "fine-tuning",
                "QLoRA",
            ],
        },
    )


def _smoke_topic(topic_id: str) -> TopicConfig:
    spec = next(item for item in DEFAULT_TOPIC_SMOKE_SPECS if item.id == topic_id)
    return TopicConfig(
        id=spec.id,
        queries=list(spec.queries),
        paper_queries=list(spec.paper_queries),
        source_intent=spec.source_intent,
        concept_groups={
            group: list(aliases) for group, aliases in spec.concept_groups.items()
        },
    )


def test_relevance_gate_filters_irrelevant_arxiv_source() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory", "LLM memory benchmark"])
    source = SourceCandidate(
        title="The Kubo-Thermalization Correspondence",
        url="https://arxiv.org/abs/2605.06666",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="Quantum thermalization links long-time equilibration with response theory.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "irrelevant"


def test_relevance_gate_keeps_agent_memory_source() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory", "LLM memory benchmark"])
    source = SourceCandidate(
        title="Mimir",
        url="https://github.com/example/mimir",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary="Build memory systems for AI agents with persistent recall.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "relevant"


def test_relevance_gate_marks_borderline_source_needs_review() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory", "LLM memory benchmark"])
    source = SourceCandidate(
        title="Why Global LLM Leaderboards Are Misleading",
        url="https://arxiv.org/abs/2605.06656",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="Ranking LLMs via pairwise human feedback can make leaderboards misleading.",
    )

    all_sources, selected, findings = gate_relevant_sources([source], topic)

    assert all_sources[0].metadata["relevance"]["status"] == "needs_review"
    assert selected == []
    assert findings[0].metadata["source_status"] == "needs_review"
    assert findings[0].severity == "info"


def test_relevance_exact_phrase_outranks_weak_single_token_match() -> None:
    topic = TopicConfig(
        id="rag-systems",
        queries=["RAG systems evaluation"],
        paper_queries=["retrieval augmented generation evaluation benchmark"],
    )
    phrase_source = SourceCandidate(
        title="Evaluating Retrieval-Augmented Generation Systems",
        url="https://arxiv.org/abs/2605.01000",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="A benchmark for retrieval augmented generation evaluation.",
    )
    weak_source = SourceCandidate(
        title="Normalizing Trajectory Models",
        url="https://arxiv.org/abs/2605.01001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="A method for generation in trajectory modeling.",
    )

    phrase = score_source(phrase_source, topic)
    weak = score_source(weak_source, topic)

    assert phrase.metadata["relevance"]["status"] == "relevant"
    assert weak.metadata["relevance"]["status"] != "relevant"
    assert phrase.metadata["relevance"]["score"] > weak.metadata["relevance"]["score"]


def test_relevance_generic_benchmark_wording_is_not_enough_for_viable_paper() -> None:
    topic = TopicConfig(id="agent-memory", queries=["agent memory systems"])
    source = SourceCandidate(
        title="A General Benchmark for Efficient Inference",
        url="https://arxiv.org/abs/2605.01002",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="This benchmark evaluates inference systems without memory agents.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] != "relevant"


def test_relevance_future_dated_paper_requires_review() -> None:
    topic = TopicConfig(
        id="rag-systems",
        queries=["RAG systems evaluation"],
        paper_queries=["retrieval augmented generation evaluation benchmark"],
    )
    source = SourceCandidate(
        title="Retrieval Augmented Generation Benchmark",
        url="https://example.com/future-paper",
        source_type=SourceType.PAPER,
        source_name="openalex",
        published_at="2999-01-01",
        summary="A benchmark for retrieval augmented generation evaluation.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "needs_review"
    assert scored.metadata["relevance"]["future_publication"] == "2999-01-01"

    _, _, findings = gate_relevant_sources([source], topic)

    assert findings[0].severity == "warning"


def test_agent_memory_required_phrases_filter_topic_mismatch_papers() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory systems", "LLM memory benchmark"],
        required_phrases=[
            "agent memory",
            "LLM memory",
            "LOCOMO",
            "LongMemEval",
        ],
        negative_phrases=[
            "prefill serving",
            "retrieval adapter",
            "planning problems",
        ],
    )
    sources = [
        SourceCandidate(
            title="ZeRO-Prefill: Zero Redundancy Overheads in MoE Prefill Serving",
            url="https://arxiv.org/abs/2605.00010",
            source_type=SourceType.PAPER,
            source_name="arxiv",
            summary="A method to reduce redundancy in serving prefill-only MoE models.",
        ),
        SourceCandidate(
            title="Align then Train: Efficient Retrieval Adapter Learning",
            url="https://arxiv.org/abs/2605.00011",
            source_type=SourceType.PAPER,
            source_name="arxiv",
            summary="A label-efficient framework that trains retrieval adapters.",
        ),
        SourceCandidate(
            title="Analysis of Optimality of Large Language Models on Planning Problems",
            url="https://arxiv.org/abs/2605.00012",
            source_type=SourceType.PAPER,
            source_name="arxiv",
            summary="An analysis of whether LLMs reason optimally in planning tasks.",
        ),
    ]

    scored = [score_source(source, topic) for source in sources]

    assert all(item.metadata["relevance"]["status"] != "relevant" for item in scored)
    assert all(
        not item.metadata["relevance"]["required_phrase_matches"]
        for item in scored
    )
    assert scored[0].metadata["relevance"]["negative_phrase_matches"] == ["prefill serving"]
    assert scored[1].metadata["relevance"]["negative_phrase_matches"] == ["retrieval adapter"]
    assert scored[2].metadata["relevance"]["negative_phrase_matches"] == ["planning problems"]


def test_agent_memory_required_phrases_keep_memory_papers() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory systems", "LLM memory benchmark"],
        required_phrases=["agent memory", "LLM memory", "LOCOMO", "LongMemEval"],
    )
    source = SourceCandidate(
        title="Memory in the LLM Era",
        url="https://arxiv.org/abs/2604.01707",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary=(
            "This LLM memory paper studies agent memory and evaluates systems with "
            "LOCOMO and LongMemEval."
        ),
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "relevant"
    assert scored.metadata["relevance"]["required_phrase_matches"] == [
        "agent memory",
        "LLM memory",
        "LOCOMO",
        "LongMemEval",
    ]


def test_agent_memory_required_phrases_ignore_generic_persistent_memory() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory systems", "LLM memory benchmark"],
        required_phrases=[
            "agent memory",
            "LLM memory",
            "agentic memory",
            "conversational memory",
            "long-term memory for agents",
            "persistent recall",
            "LOCOMO",
            "LongMemEval",
        ],
    )
    source = SourceCandidate(
        title="When Agents Handle Secrets: A Survey of Confidential Computing for Agentic AI",
        url="https://arxiv.org/abs/2605.03213",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary=(
            "Agentic AI systems maintain persistent memory, hold credentials, "
            "and use confidential computing defenses."
        ),
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] != "relevant"
    assert scored.metadata["relevance"]["required_phrase_matches"] == []


def test_research_brief_repo_without_required_phrase_is_not_relevant() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory systems", "LLM memory benchmark"],
        required_phrases=["agent memory", "LLM memory", "LOCOMO", "LongMemEval"],
    )
    source = SourceCandidate(
        title="Samarth2001/LLM-Fine-tuning",
        url="https://github.com/Samarth2001/LLM-Fine-tuning",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary=(
            "Parameter-efficient fine-tuning experiments for 7B LLMs with QLoRA "
            "and memory optimization strategies."
        ),
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] != "relevant"
    assert scored.metadata["relevance"]["required_phrase_matches"] == []
    assert (
        "research brief repo missing configured required phrase"
        in scored.metadata["relevance"]["reason"]
    )


def test_research_brief_keeps_serious_agent_memory_repo() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory systems", "LLM memory benchmark"],
        required_phrases=["agent memory", "LLM memory", "LOCOMO", "LongMemEval"],
    )
    source = SourceCandidate(
        title="agent-memory-benchmark",
        url="https://github.com/example/agent-memory-benchmark",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary="Benchmark implementation for agent memory systems with LongMemEval support.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "relevant"
    assert scored.metadata["relevance"]["required_phrase_matches"] == [
        "agent memory",
        "LongMemEval",
    ]


def test_implementation_scan_does_not_apply_research_brief_repo_required_phrase_gate() -> None:
    topic = TopicConfig(
        id="agent-memory",
        queries=["agent memory systems", "LLM memory benchmark"],
        required_phrases=["agent memory"],
        source_intent="implementation_scan",
    )
    source = SourceCandidate(
        title="haxlys/llm-bench",
        url="https://github.com/haxlys/llm-bench",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary="Apple Silicon LLM benchmark harness with memory and eval coverage.",
    )

    scored = score_source(source, topic)

    assert scored.metadata["relevance"]["status"] == "relevant"
    assert "research brief repo missing" not in scored.metadata["relevance"]["reason"]


def test_concept_gate_accepts_agent_memory_paper() -> None:
    source = SourceCandidate(
        title="Memory in the LLM Era",
        url="https://arxiv.org/abs/2604.01707",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary=(
            "A unified framework for agent memory systems with memory retrieval "
            "and LongMemEval evaluation."
        ),
    )

    scored = score_source(source, _agent_memory_concept_topic())
    concept_gate = scored.metadata["relevance"]["concept_gate"]

    assert scored.metadata["relevance"]["status"] == "relevant"
    assert concept_gate["passed"] is True
    assert concept_gate["decision_rule"] == "benchmark_anchor"
    assert concept_gate["matched_aliases"]["agent_context"] == ["agent memory"]


def test_concept_gate_accepts_known_benchmark_anchor() -> None:
    source = SourceCandidate(
        title="A New Evaluation Built on LongMemEval",
        url="https://arxiv.org/abs/2605.01010",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary="LongMemEval probes memory behavior over many sessions.",
    )

    scored = score_source(source, _agent_memory_concept_topic())

    assert scored.metadata["relevance"]["status"] == "relevant"
    assert scored.metadata["relevance"]["concept_gate"]["decision_rule"] == "benchmark_anchor"


def test_concept_gate_downgrades_generic_compute_and_training_sources() -> None:
    topic = _agent_memory_concept_topic()
    sources = [
        SourceCandidate(
            title="ZeRO-Prefill: Zero Redundancy Overheads in MoE Prefill Serving",
            url="https://arxiv.org/abs/2605.00010",
            source_type=SourceType.PAPER,
            source_name="arxiv",
            summary="A method to reduce memory overhead in prefill serving.",
        ),
        SourceCandidate(
            title="Samarth2001/LLM-Fine-tuning",
            url="https://github.com/Samarth2001/LLM-Fine-tuning",
            source_type=SourceType.REPOSITORY,
            source_name="github",
            summary="Fine-tuning experiments for LLMs with QLoRA memory optimization.",
        ),
        SourceCandidate(
            title="haxlys/llm-bench",
            url="https://github.com/haxlys/llm-bench",
            source_type=SourceType.REPOSITORY,
            source_name="github",
            summary="Generic LLM memory benchmark harness for Apple Silicon.",
        ),
    ]

    scored = [score_source(source, topic) for source in sources]

    assert all(item.metadata["relevance"]["status"] != "relevant" for item in scored)
    assert "negative concept matched" in scored[0].metadata["relevance"]["reason"]
    assert "negative concept matched" in scored[1].metadata["relevance"]["reason"]
    assert (
        "concept gate missing required concept combination"
        in scored[2].metadata["relevance"]["reason"]
    )


def test_concept_gate_keeps_serious_repository_for_research_brief() -> None:
    source = SourceCandidate(
        title="agent-memory-benchmark",
        url="https://github.com/example/agent-memory-benchmark",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary="Benchmark implementation for agent memory systems with LongMemEval support.",
    )

    scored = score_source(source, _agent_memory_concept_topic())

    assert scored.metadata["relevance"]["status"] == "relevant"
    assert scored.metadata["relevance"]["concept_gate"]["passed"] is True


def test_implementation_scan_does_not_apply_concept_gate_to_repositories() -> None:
    source = SourceCandidate(
        title="haxlys/llm-bench",
        url="https://github.com/haxlys/llm-bench",
        source_type=SourceType.REPOSITORY,
        source_name="github",
        summary="Apple Silicon LLM benchmark harness with memory and eval coverage.",
    )

    scored = score_source(source, _agent_memory_concept_topic("implementation_scan"))

    assert scored.metadata["relevance"]["status"] == "relevant"
    assert "concept gate missing" not in scored.metadata["relevance"]["reason"]


def test_reasoning_eval_concept_profile_accepts_paper_level_signals() -> None:
    source = SourceCandidate(
        title="Verifier-Guided Chain-of-Thought for Mathematical Reasoning",
        url="https://arxiv.org/abs/2605.01020",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary=(
            "This paper evaluates LLM reasoning on AIME, MATH, and GPQA with "
            "test-time compute and deliberation."
        ),
    )

    scored = score_source(source, _smoke_topic("llm-reasoning-eval"))

    assert scored.metadata["relevance"]["status"] == "relevant"
    concept_gate = scored.metadata["relevance"]["concept_gate"]
    assert concept_gate["passed"] is True
    assert "chain-of-thought" in concept_gate["matched_aliases"]["agent_context"]
    assert "test-time compute" in concept_gate["matched_aliases"]["memory_mechanism"]


def test_rag_concept_profile_downgrades_application_noise() -> None:
    source = SourceCandidate(
        title="RAG for Optical Retail E-Commerce Project Assessment",
        url="https://arxiv.org/abs/2605.01021",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary=(
            "This application uses retrieval augmented generation for peer review "
            "and generic project assessment."
        ),
    )

    scored = score_source(source, _smoke_topic("rag-systems"))

    assert scored.metadata["relevance"]["status"] != "relevant"
    concept_gate = scored.metadata["relevance"]["concept_gate"]
    assert "peer review" in concept_gate["matched_negative_aliases"]
    assert "e-commerce" in concept_gate["matched_negative_aliases"]
    assert "negative concept matched" in scored.metadata["relevance"]["reason"]


def test_rag_concept_profile_keeps_system_evaluation_paper() -> None:
    source = SourceCandidate(
        title="RAG Systems Evaluation Benchmark",
        url="https://arxiv.org/abs/2605.01022",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        summary=(
            "A retrieval augmented generation system benchmark for RAG systems "
            "evaluation with retrieval pipeline analysis."
        ),
    )

    scored = score_source(source, _smoke_topic("rag-systems"))

    assert scored.metadata["relevance"]["status"] == "relevant"
    assert scored.metadata["relevance"]["concept_gate"]["passed"] is True
