from research_radar.config import ConfigError, parse_config


def test_parse_config_rejects_auto_publish() -> None:
    data = {
        "project": {"name": "ResearchRadar"},
        "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        "publishing": {"auto_publish": True},
    }

    try:
        parse_config(data)
    except ConfigError as exc:
        assert "auto_publish" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_parse_config_accepts_default_plan_shape() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [
                {
                    "id": "agent-memory",
                    "queries": ["agent memory systems"],
                    "paper_queries": ["Memory in the LLM Era"],
                    "web_queries": ["agent memory systems paper"],
                    "exclusion_terms": ["translation memory"],
                    "priority_sources": ["arxiv.org", "github.com"],
                }
            ],
            "security": {"secret_backend": "keychain", "encrypt_storage": True},
        }
    )

    assert config.project.name == "ResearchRadar"
    assert config.topic("agent-memory").queries == ["agent memory systems"]
    assert config.topic("agent-memory").paper_queries == ["Memory in the LLM Era"]
    assert config.topic("agent-memory").web_queries == ["agent memory systems paper"]
    assert config.topic("agent-memory").exclusion_terms == ["translation memory"]
    assert config.topic("agent-memory").required_phrases == []
    assert config.topic("agent-memory").negative_phrases == []
    assert config.topic("agent-memory").report_language == "en"
    assert config.discovery.trusted_domains == []
    assert config.discovery.web_search.endpoint is None
    assert config.topic("agent-memory").source_intent == "research_brief"
    assert config.publishing.auto_publish is False


def test_parse_config_accepts_implementation_scan_source_intent() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [
                {
                    "id": "agent-memory",
                    "queries": ["agent memory systems"],
                    "source_intent": "implementation_scan",
                }
            ],
        }
    )

    assert config.topic("agent-memory").source_intent == "implementation_scan"


def test_parse_config_accepts_topic_precision_and_language() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [
                {
                    "id": "agent-memory",
                    "queries": ["agent memory systems"],
                    "required_phrases": ["agent memory"],
                    "negative_phrases": ["prefill serving"],
                    "concept_groups": {
                        "agent_context": ["agent memory"],
                        "memory_mechanism": ["persistent recall"],
                    },
                    "report_language": "zh",
                }
            ],
        }
    )

    topic = config.topic("agent-memory")

    assert topic.required_phrases == ["agent memory"]
    assert topic.negative_phrases == ["prefill serving"]
    assert topic.concept_groups == {
        "agent_context": ["agent memory"],
        "memory_mechanism": ["persistent recall"],
    }
    assert topic.report_language == "zh"


def test_parse_config_rejects_invalid_concept_groups() -> None:
    data = {
        "project": {"name": "ResearchRadar"},
        "topics": [
            {
                "id": "agent-memory",
                "queries": ["agent memory"],
                "concept_groups": {"agent_context": "agent memory"},
            }
        ],
    }

    try:
        parse_config(data)
    except ConfigError as exc:
        assert "concept_groups.agent_context" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_parse_config_rejects_invalid_report_language() -> None:
    data = {
        "project": {"name": "ResearchRadar"},
        "topics": [
            {
                "id": "agent-memory",
                "queries": ["agent memory"],
                "report_language": "fr",
            }
        ],
    }

    try:
        parse_config(data)
    except ConfigError as exc:
        assert "report_language" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_parse_config_rejects_invalid_source_intent() -> None:
    data = {
        "project": {"name": "ResearchRadar"},
        "topics": [
            {
                "id": "agent-memory",
                "queries": ["agent memory"],
                "source_intent": "project_recommendation",
            }
        ],
    }

    try:
        parse_config(data)
    except ConfigError as exc:
        assert "source_intent" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_parse_config_accepts_discovery_settings() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "discovery": {
                "trusted_domains": ["arxiv.org", "openreview.net"],
                "web_search": {
                    "provider": "generic",
                    "endpoint": "https://search.example.test/api",
                    "header_secret_name": "web_search.api_key",
                    "max_results": 7,
                    "search_depth": "fast",
                },
            },
        }
    )

    assert config.discovery.trusted_domains == ["arxiv.org", "openreview.net"]
    assert config.discovery.web_search.provider == "generic"
    assert config.discovery.web_search.endpoint == "https://search.example.test/api"
    assert config.discovery.web_search.header_secret_name == "web_search.api_key"
    assert config.discovery.web_search.max_results == 7
    assert config.discovery.web_search.search_depth == "fast"


def test_parse_config_accepts_tavily_web_search() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "discovery": {
                "web_search": {
                    "provider": "tavily",
                    "header_secret_name": "web_search.api_key",
                    "search_depth": "basic",
                },
            },
        }
    )

    assert config.discovery.web_search.provider == "tavily"
    assert config.discovery.web_search.endpoint is None
    assert config.discovery.web_search.header_secret_name == "web_search.api_key"


def test_parse_config_rejects_unknown_web_search_provider() -> None:
    data = {
        "project": {"name": "ResearchRadar"},
        "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        "discovery": {
            "web_search": {
                "provider": "unknown",
            }
        },
    }

    try:
        parse_config(data)
    except ConfigError as exc:
        assert "discovery.web_search.provider" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_default_command_providers_have_longer_timeout() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        }
    )

    assert config.model_providers["codex"].timeout_seconds == 900
    assert config.model_providers["claude"].timeout_seconds == 900
    assert config.model_providers["von_claude"].timeout_seconds == 900


def test_command_provider_timeout_can_be_overridden() -> None:
    config = parse_config(
        {
            "project": {"name": "ResearchRadar"},
            "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
            "model_providers": {
                "codex": {
                    "kind": "codex_cli",
                    "command": "codex",
                    "timeout_seconds": 120,
                }
            },
        }
    )

    assert config.model_providers["codex"].timeout_seconds == 120


def test_parse_config_rejects_empty_web_search_endpoint() -> None:
    data = {
        "project": {"name": "ResearchRadar"},
        "topics": [{"id": "agent-memory", "queries": ["agent memory"]}],
        "discovery": {
            "web_search": {
                "endpoint": "",
            }
        },
    }

    try:
        parse_config(data)
    except ConfigError as exc:
        assert "discovery.web_search.endpoint" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")
