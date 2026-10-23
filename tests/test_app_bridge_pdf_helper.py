import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_radar.analysis.figures import PdfCropBox
from research_radar.app_bridge.pdf_helper import PDFHelperClient, PDFHelperError


@pytest.mark.parametrize("result_kind", [
    "alias", "different", "outside", "missing", "invalid", "relative", "symlink",
    "parent_symlink", "no_output", "directory",
])
def test_crop_response_requires_same_safe_file(tmp_path: Path, result_kind: str) -> None:
    root = tmp_path.resolve()
    if result_kind == "alias" and (
        sys.platform != "darwin" or not str(root).startswith("/private/")
    ):
        pytest.skip("Requires a macOS system temporary-directory alias")
    helper = root / "helper"
    helper.write_text("fixture")
    helper.chmod(0o700)
    allowed = root / "allowed"
    allowed.mkdir()
    pdf = allowed / "paper.pdf"
    pdf.write_bytes(b"pdf")
    output = allowed / "figure.png"
    if result_kind == "parent_symlink":
        (allowed / "images").mkdir()
        output = allowed / "images/figure.png"

    def run(args, **kwargs):
        if result_kind == "directory":
            output.mkdir()
        elif result_kind != "no_output":
            output.write_bytes(b"png")
        returned: object = str(output)
        if result_kind == "alias":
            returned = str(output).removeprefix("/private")
        elif result_kind in {"different", "outside"}:
            other = (allowed if result_kind == "different" else root) / "other.png"
            other.write_bytes(b"other")
            returned = str(other)
        elif result_kind == "missing":
            returned = str(allowed / "missing.png")
        elif result_kind == "invalid":
            returned = 123
        elif result_kind == "relative":
            returned = "figure.png"
        elif result_kind == "symlink":
            link = allowed / "alias.png"
            link.symlink_to(output)
            returned = str(link)
        elif result_kind == "parent_symlink":
            directory = allowed / "images"
            link = allowed / "images-link"
            link.symlink_to(directory, target_is_directory=True)
            returned = str(link / "figure.png")
        return subprocess.CompletedProcess(args, 0, json.dumps({
            "schema_version": 1, "operation": "render_crop", "output_path": returned,
        }), "")

    client = PDFHelperClient(helper, runner=run)
    def render() -> bool:
        return client.render_crop(pdf, 1, PdfCropBox(x=0, y=0, width=10, height=10),
                                  output, dpi=72, allowed_root=allowed)

    if result_kind == "alias":
        assert render()
    else:
        with pytest.raises(PDFHelperError):
            render()


def test_pdf_helper_client_reports_missing_executable(tmp_path: Path) -> None:
    with pytest.raises(PDFHelperError, match="executable is unavailable"):
        PDFHelperClient(tmp_path / "missing-helper")


def test_pdf_helper_client_uses_one_process_per_operation(tmp_path: Path) -> None:
    helper = tmp_path / "ResearchRadarPDFHelper"
    helper.write_text("fixture", encoding="utf-8")
    helper.chmod(0o700)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    output = tmp_path / "figure.png"
    calls: list[dict[str, object]] = []

    def fake_run(args, **kwargs):
        request = json.loads(kwargs["input"])
        calls.append(request)
        if request["operation"] == "page_text":
            response = {
                "schema_version": 1,
                "operation": "page_text",
                "page": {
                    "page_index": 1,
                    "page_box": {"x": 0, "y": 0, "width": 600, "height": 800},
                    "words": [
                        {
                            "text": "Figure",
                            "box": {"x": 40, "y": 500, "width": 35, "height": 12},
                        }
                    ],
                },
            }
        else:
            output.write_bytes(b"png")
            response = {
                "schema_version": 1,
                "operation": "render_crop",
                "output_path": str(output),
            }
        return subprocess.CompletedProcess(args, 0, json.dumps(response), "")

    client = PDFHelperClient(helper, runner=fake_run)
    page = client.page_bbox(pdf, 2, allowed_root=tmp_path)
    rendered = client.render_crop(
        pdf,
        2,
        PdfCropBox(x=20, y=30, width=400, height=200),
        output,
        dpi=160,
        allowed_root=tmp_path,
    )

    assert page is not None
    assert page.width == 600
    assert page.words[0].text == "Figure"
    assert rendered is True
    assert [call["operation"] for call in calls] == ["page_text", "render_crop"]
    assert calls[0]["page_index"] == 1
    assert calls[1]["scale"] == pytest.approx(160 / 72)


def test_pdf_helper_client_rejects_escape_and_malformed_response(tmp_path: Path) -> None:
    helper = tmp_path / "ResearchRadarPDFHelper"
    helper.write_text("fixture", encoding="utf-8")
    helper.chmod(0o700)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"pdf")

    client = PDFHelperClient(
        helper,
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "{}", ""),
    )

    with pytest.raises(PDFHelperError, match="allowed root"):
        client.page_bbox(outside, 1, allowed_root=allowed)

    inside = allowed / "paper.pdf"
    inside.write_bytes(b"pdf")
    with pytest.raises(PDFHelperError, match="response"):
        client.page_bbox(inside, 1, allowed_root=allowed)


@pytest.mark.parametrize("failure", ["timeout", "nonzero", "invalid_json", "invalid_encoding"])
@pytest.mark.parametrize("operation", ["page_text", "render_crop"])
def test_optional_pdf_helper_failure_skips_figures_not_research(
    tmp_path: Path, failure: str, operation: str,
) -> None:
    from research_radar.app_bridge.pdf_helper import app_figure_extractor
    from research_radar.models import (
        Artifact,
        Claim,
        ClaimStatus,
        EvidenceAnchor,
        SourceCandidate,
        SourceType,
    )
    from research_radar.pipeline.daily import _extract_deep_read_figures

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF offline fixture")
    source = SourceCandidate(title="MARS", url="https://example.com/offline-mars",
                             source_type=SourceType.PAPER, source_name="offline")
    artifact = Artifact(source=source, artifact_path=str(pdf), content_type="application/pdf",
        text="[page 3]\nFigure 2: MARS architecture. MARS predicts API duration and "
             "schedules requests with memory-aware handling.\n")
    claim = Claim(text="Solution: MARS predicts API duration for memory-aware scheduling.",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url=source.url, quote="MARS predicts API duration")])
    calls: list[str] = []

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        request = json.loads(kwargs["input"])
        calls.append(request["operation"])
        if request["operation"] == operation:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, kwargs["timeout"])
            if failure == "invalid_encoding":
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "Offline invalid helper output")
            return subprocess.CompletedProcess(args, 1 if failure == "nonzero" else 0,
                "{", "Offline helper rejected operation")
        words = [("MARS", 45, 60, 37, 14), ("uses", 86, 60, 29, 14),
                 ("scheduling", 120, 60, 68, 14), ("Figure", 45, 410, 46, 15),
                 ("2:", 96, 410, 16, 15), ("MARS", 116, 410, 37, 15),
                 ("architecture.", 158, 410, 82, 15)]
        return subprocess.CompletedProcess(args, 0, json.dumps({
            "schema_version": 1, "operation": "page_text", "page": {
                "page_box": {"x": 0, "y": 0, "width": 600, "height": 800},
                "words": [{"text": text, "box": {"x": x, "y": y, "width": w, "height": h}}
                          for text, x, y, w, h in words],
            },
        }), "")

    figures, findings = _extract_deep_read_figures([artifact], [claim], tmp_path / "figures",
        figure_extractor=app_figure_extractor(PDFHelperClient(Path(sys.executable), runner=run),
                                             allowed_root=tmp_path))
    assert figures == {}
    assert len(findings) == 1
    assert findings[0].metadata["kind"] == "figure_extraction_skipped"
    assert claim.is_publishable()
    assert calls == (["page_text"] if operation == "page_text" else ["page_text", "render_crop"])


def test_pdf_helper_adapter_does_not_swallow_programming_errors(tmp_path: Path) -> None:
    from research_radar.app_bridge.pdf_helper import app_figure_extractor
    from research_radar.models import (
        Artifact,
        Claim,
        ClaimStatus,
        EvidenceAnchor,
        SourceCandidate,
        SourceType,
    )

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF offline fixture")
    source = SourceCandidate(title="MARS", url="https://example.com/offline-mars",
                             source_type=SourceType.PAPER, source_name="offline")
    artifact = Artifact(source=source, artifact_path=str(pdf), content_type="application/pdf",
        text="[page 3]\nFigure 2: MARS architecture. MARS predicts API duration and "
             "schedules requests with memory-aware handling.\n")
    claim = Claim(text="Solution: MARS predicts API duration for memory-aware scheduling.",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url=source.url, quote="MARS predicts API duration")])

    def broken_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise TypeError("Offline programming defect")

    extract = app_figure_extractor(PDFHelperClient(Path(sys.executable), runner=broken_runner),
                                    allowed_root=tmp_path)
    with pytest.raises(TypeError, match="programming defect"):
        extract(artifact, tmp_path / "figures", [claim])


def test_daily_writes_verified_report_when_optional_pdf_helper_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    from research_radar.app_bridge.configuration import load_app_configuration
    from research_radar.app_bridge.events import EventWriter
    from research_radar.app_bridge.protocol import EngineRequestV1, RunDailyPayloadV1
    from research_radar.compose.draft_io import load_article_draft
    from script.verify_offline_frozen import prepare_config

    monkeypatch.syspath_prepend(str(Path(__file__).parent / "fixtures"))
    from offline_frozen.entry import dependencies

    root = tmp_path / "ResearchRadar"
    config_path = prepare_config(root)
    config = load_app_configuration(config_path)
    injected = dependencies(config.workspace_root)
    result = injected.run_daily(
        EngineRequestV1(1, "offline", "run_daily", "2026-10-24T00:00:00Z", root,
            config_path, RunDailyPayloadV1("memory", "2026-10-24", 1, 1, "en", False, None)),
        config=config, secrets=injected.secret_manager_factory(),
        events=EventWriter(root / "events.jsonl", request_id="offline"),
        pdf_helper_path=Path("/usr/bin/false"),
    )
    run = Path(result["run_dir"])
    draft = load_article_draft(run / "article_draft.json")
    findings = [json.loads(line)
                for line in (run / "review_findings.jsonl").read_text().splitlines()]
    assert result["deep_read_count"] == 1
    assert result["publishable_claim_count"] == 6
    assert result["research_outcome"]["status"] == "ready"
    assert draft.claims and all(claim.is_publishable() for claim in draft.claims)
    assert any(item.get("metadata", {}).get("kind") == "figure_extraction_skipped"
               for item in findings)
    assert (run / "wechat.html").is_file()
    assert not list((run / "figures").rglob("*.png"))
    assert not (run / "email_send_result.json").exists()
    assert not (run / "publish_wechat_draft_request.json").exists()
