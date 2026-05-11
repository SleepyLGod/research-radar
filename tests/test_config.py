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
                    "priority_sources": ["arxiv.org", "github.com"],
                }
            ],
            "security": {"secret_backend": "keychain", "encrypt_storage": True},
        }
    )

    assert config.project.name == "ResearchRadar"
    assert config.topic("agent-memory").queries == ["agent memory systems"]
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
