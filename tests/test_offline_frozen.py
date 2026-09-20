"""Offline fixture contracts; optional native/frozen integration is explicit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from research_radar.ingestion.paper_quality import paper_text_quality
from research_radar.ingestion.pdf import extract_pdf
from research_radar.models import SourceCandidate, SourceType

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _script_import_path(monkeypatch) -> None:
    """Support both pytest console entrypoint and python -m pytest."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))


def test_synthetic_pdf_is_full_paper_input_with_real_caption(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(FIXTURES))
    from offline_frozen.inputs import SOURCE_URL, TITLE, create_paper

    path = tmp_path / "paper.pdf"
    create_paper(path)
    source = SourceCandidate(
        title=TITLE, url=SOURCE_URL, source_type=SourceType.PAPER, source_name="offline"
    )
    artifact = extract_pdf(source, path)
    assert paper_text_quality(artifact)["status"] == "pass"
    assert artifact.metadata["page_count"] == 7
    assert "Figure 1: Cited memory evidence" in artifact.text
    assert not list(tmp_path.glob("*.html"))
    assert not (tmp_path / "article_draft.json").exists()


def test_test_entry_blocks_network_dns_and_child_programs() -> None:
    program = """
from offline_frozen.entry import block_external_io
import socket, subprocess
block_external_io(None)
for action in (
    lambda: socket.getaddrinfo('example.com', 443),
    lambda: socket.create_connection(('127.0.0.1', 80)),
    lambda: subprocess.run(['/usr/bin/security', 'help']),
):
    try:
        action()
    except RuntimeError as error:
        assert str(error) in {'OFFLINE_NETWORK_BLOCKED', 'OFFLINE_PROCESS_BLOCKED'}
    else:
        raise AssertionError('External IO was not blocked')
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(FIXTURES)},
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_test_model_rejects_unconfigured_models(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(FIXTURES))
    from offline_frozen.inputs import FrozenModel

    from research_radar.analysis.providers import Message

    with pytest.raises(AssertionError, match="Unexpected offline model"):
        FrozenModel().complete([Message(role="user", content="test")], model="real-model")


def test_prepare_configuration_uses_production_loader(tmp_path: Path) -> None:
    from research_radar.app_bridge.configuration import load_app_configuration
    from script.verify_offline_frozen import prepare_config

    config = load_app_configuration(prepare_config(tmp_path))
    assert config.email_enabled and config.wechat.enabled
    assert config.research.topic("memory").report_language == "en"


def test_production_entry_and_spec_do_not_import_fixture() -> None:
    root = Path(__file__).parents[1]
    for path in (
        root / "packaging/macos/engine_entry.py",
        root / "packaging/macos/research-radar-engine.spec",
        root / "src/research_radar/app_bridge/__main__.py",
    ):
        content = path.read_text()
        assert "offline_frozen" not in content
        assert "offline-test" not in content
        assert "tests/fixtures" not in content


@pytest.mark.parametrize("rendered", ["<p>Report</p>", "<p>Report</p>\n"])
def test_report_bytes_match_production_storage_without_hiding_changes(
    tmp_path: Path, rendered: str
) -> None:
    from research_radar.storage.files import write_text
    from script.verify_offline_frozen import verify_rendered_bytes

    path = tmp_path / "report.html"
    write_text(path, rendered)
    verify_rendered_bytes(path.read_bytes(), rendered)
    with pytest.raises(AssertionError):
        verify_rendered_bytes(path.read_bytes() + b" ", rendered)


@pytest.mark.skipif(not os.getenv("RESEARCH_RADAR_OFFLINE_ENGINE"), reason="opt-in frozen E2E")
def test_frozen_accepts_actual_swift_config(tmp_path: Path) -> None:
    from datetime import datetime

    from script.verify_offline_frozen import invoke, verify_report, write_json

    root = tmp_path / "ResearchRadar"
    config = json.loads(
        (FIXTURES / "offline_frozen/swift-app-config-omitted-optionals.json").read_text()
    )
    config["workspace_root"] = str(root / "workspace")
    config_path = root / "config/app-config.json"
    write_json(config_path, config)
    result, _ = invoke(
        [os.environ["RESEARCH_RADAR_OFFLINE_ENGINE"]],
        root,
        "run_daily",
        {
            "topic_id": "memory",
            "report_date": datetime.now().date().isoformat(),
            "limit": 1,
            "deep_limit": 1,
            "language": "en",
            "model_cache": False,
            "model_cache_limit_bytes": None,
        },
        helper=Path(os.environ["RESEARCH_RADAR_OFFLINE_PDF_HELPER"]),
        config=config_path,
    )
    assert result["report"]["deep_read_count"] == 1
    assert result["report"]["publishable_claim_count"] == 6
    evidence = verify_report(Path(result["report"]["run_dir"]))
    assert evidence["figure_count"] == 1
    write_json(root / "swift-config-verification.json", evidence)


@pytest.mark.skipif(not os.getenv("RESEARCH_RADAR_OFFLINE_ENGINE"), reason="opt-in frozen E2E")
def test_frozen_pipeline_and_delivery(tmp_path: Path) -> None:
    from script.verify_offline_frozen import verify

    evidence = verify(
        [os.environ["RESEARCH_RADAR_OFFLINE_ENGINE"]],
        tmp_path / "ResearchRadar",
        Path(os.environ["RESEARCH_RADAR_OFFLINE_PDF_HELPER"]),
    )
    assert evidence["report"]["figure_count"] > 0
    (tmp_path / "verification.json").write_text(json.dumps(evidence, indent=2))
