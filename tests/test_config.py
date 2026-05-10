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
    assert config.publishing.auto_publish is False
