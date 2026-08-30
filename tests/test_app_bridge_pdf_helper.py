import json
import subprocess
from pathlib import Path

import pytest

from research_radar.analysis.figures import PdfCropBox
from research_radar.app_bridge.pdf_helper import PDFHelperClient, PDFHelperError


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
