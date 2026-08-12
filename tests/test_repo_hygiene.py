import tomllib
from pathlib import Path

from research_radar import __version__


def test_mit_license_exists() -> None:
    license_text = Path("LICENSE").read_text(encoding="utf-8")

    assert "MIT License" in license_text
    assert "ResearchRadar Maintainers" in license_text


def test_gitignore_covers_private_runtime_files() -> None:
    ignore_text = Path(".gitignore").read_text(encoding="utf-8")

    for pattern in [
        ".env",
        "config.yaml",
        "topic_drafts/",
        "runs/",
        "data/",
        "cache/",
        "secrets/",
        "*.sqlite",
        "*.db",
        "*.enc.json",
        "*.pem",
        "*.key",
        "logs/",
    ]:
        assert pattern in ignore_text


def test_version_metadata_matches_package() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == __version__
    assert __version__


def test_readme_is_concise_project_entrypoint() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "![ResearchRadar](docs/assets/research-radar-hero.png)" in readme
    assert "[简体中文](README.zh-CN.md)" in readme
    assert "[Live Archive](https://sleepylgod.github.io/research-radar/archive/)" in readme
    assert "[RSS](https://sleepylgod.github.io/research-radar/archive/feed.xml)" in readme
    assert "[Detailed Usage](docs/usage.md)" in readme
    assert "[Provider Configuration](docs/providers.md)" in readme
    assert "DeepSeek v4 Flash" in readme
    assert "explicit thinking" in readme
    assert "Codex `gpt-5.6-terra`" in readme
    assert "`Evidence-gated`" in readme
    assert "Turn a reviewed research topic into a daily article" in readme
    assert "ResearchRadar does not publish" in readme
    assert "[Roadmap](docs/todo.md)" in readme
    for unsupported_label in ["Exa", "Citation Graph", "PubMed", "Firecrawl"]:
        assert unsupported_label not in readme
    assert "## Target E2E Flow" not in readme
    assert "## What v1 Does" not in readme


def test_readme_cover_image_exists() -> None:
    image = Path("docs/assets/research-radar-hero.png")

    assert image.exists()
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_chinese_readme_and_usage_doc_exist() -> None:
    chinese = Path("README.zh-CN.md").read_text(encoding="utf-8")
    usage = Path("docs/usage.md").read_text(encoding="utf-8")

    assert "微信公众号草稿" in chinese
    assert "证据核验" in chinese
    assert "[English README](README.md)" in chinese
    assert "--config config.yaml" in chinese
    assert "--config config.example.yaml" not in chinese
    assert "# ResearchRadar Usage Guide" in usage
    assert "Deep reading: `deepseek/deepseek-v4-flash`" in usage
    assert "Verification: `codex/gpt-5.6-terra`" in usage
    assert "--deepseek-provider xiaomi" in usage
    assert "[Provider Configuration](providers.md)" in usage
    assert "research-radar compose zhihu" in usage


def test_provider_docs_explain_interfaces_without_expanding_public_config() -> None:
    providers = Path("docs/providers.md").read_text(encoding="utf-8")
    config = Path("config.example.yaml").read_text(encoding="utf-8")

    for phrase in [
        "openai_compatible",
        "anthropic_messages",
        "codex_cli",
        "claude_code_cli",
        "local",
        "secrets set-named kimi.api_key",
        "RESEARCH_RADAR_SECRET_KIMI_API_KEY",
        "provider probe",
        "provider list",
        "provider routes",
    ]:
        assert phrase in providers
    assert "model_providers:\n  kimi:" not in config
    assert "model_providers:\n  qwen:" not in config


def test_readme_daily_command_uses_printed_run_directory_contract() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "--root research-radar-data" in readme
    assert "Created run: <RUN_DIR>" in readme
    assert "--run runs/<date-topic>" not in readme


def test_example_config_enables_tavily_web_search() -> None:
    config = Path("config.example.yaml").read_text(encoding="utf-8")

    assert "provider: tavily" in config
    assert "header_secret_name: web_search.api_key" in config


def test_example_config_uses_codex_terra_high_verifier() -> None:
    config = Path("config.example.yaml").read_text(encoding="utf-8")

    assert "thinking: enabled" in config
    assert "analyst: deepseek-v4-flash" in config
    assert "deepseek-v4-pro" not in config
    assert "reasoning_effort: high" in config
    assert "verifier:\n      provider: codex\n      model: gpt-5.6-terra" in config


def test_architecture_contains_canonical_e2e_flow() -> None:
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")

    for phrase in [
        "Topic setup",
        "Planner",
        "Discovery produces normalized `SourceCandidate` records",
        "Wide scan",
        "Ingestion stores PDFs, HTML pages, and repository metadata",
        "Deep research reading",
        "supporting claim IDs",
        "Evidence ledger and review",
        "public explanation policy",
        "Synthesis outline / prewriting",
        "`ArticleDraft`",
        "Rendering transforms that draft",
        "Publishing is explicit",
        "Audit artifacts",
    ]:
        assert phrase in architecture

    assert "v0.0.0 foundation" not in architecture
    assert "WeChat, Archive/RSS, Zhihu, and email are sibling outputs" in architecture
    assert "Normal run artifacts are local plaintext files" in architecture


def test_old_version_labels_are_not_used() -> None:
    checked_paths = [
        *Path("src").rglob("*.py"),
        *Path("docs").rglob("*.md"),
        Path("README.md"),
        Path("pyproject.toml"),
    ]

    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        assert "ResearchRadar/0.1" not in text
        assert "v0.2" not in text


def test_research_radar_skill_exists() -> None:
    skill_text = Path("docs/skills/research-radar/SKILL.md").read_text(encoding="utf-8")

    assert "name: research-radar" in skill_text
    assert "Act as a skeptical but fair researcher" in skill_text
    assert "Graphify is optional support" in skill_text


def test_research_radar_skill_defines_workflow_contract() -> None:
    skill_text = Path("docs/skills/research-radar/SKILL.md").read_text(encoding="utf-8")

    for section in [
        "Planner:",
        "Wide scan:",
        "Deep reading:",
        "Prewriting:",
        "Publisher:",
    ]:
        assert section in skill_text

    for output_field in [
        "`research_plan`",
        "`wide_scan`",
        "`deep_readings`",
        "`synthesis_outline`",
        "`evidence_index`",
        "`unsupported_or_rejected_claims`",
        "`article_draft_notes`",
    ]:
        assert output_field in skill_text

    assert "Do not jump from a topic directly to a polished article" in skill_text
    assert "do not add them as default dependencies" in skill_text


def test_research_radar_skill_reference_captures_borrowed_patterns() -> None:
    reference_text = Path(
        "docs/skills/research-radar/references/workflow-patterns.md"
    ).read_text(encoding="utf-8")

    for source in ["GPT Researcher", "STORM", "PaperQA2", "Graphify"]:
        assert source in reference_text

    assert "finite planner-executor-publisher" in reference_text
    assert "Perspective-guided" not in reference_text
    assert "perspective-guided" in reference_text
    assert "optional future backend" in reference_text
    assert "default runtime dependencies" in reference_text
    assert "OpenScholar" not in reference_text
