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


def test_version_metadata_is_foundation() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == "0.0.0"
    assert __version__ == "0.0.0"


def test_readme_describes_foundation_not_current_v1() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## Current v0.0.0 Foundation" in readme
    assert "## Target E2E Flow" in readme
    assert "## What v1 Does" not in readme
    assert "not yet the full v1" in readme
    assert "product" in readme


def test_architecture_contains_canonical_e2e_flow() -> None:
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")

    for phrase in [
        "Topic setup",
        "Planner",
        "Discovery produces normalized `SourceCandidate` records",
        "Wide scan",
        "Ingestion stores PDFs, HTML pages, and repository metadata",
        "Deep research reading",
        "Evidence ledger",
        "Review checks hallucination risk",
        "Synthesis outline / prewriting",
        "`ArticleDraft`",
        "Rendering transforms the same draft",
        "Manual publishing creates a WeChat draft",
        "Audit artifacts",
    ]:
        assert phrase in architecture

    assert "v0.0.0 foundation" in architecture
    assert "WeChat and Zhihu are downstream publishing channels" in architecture


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
