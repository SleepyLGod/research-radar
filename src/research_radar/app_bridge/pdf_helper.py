"""On-demand client for the bundled native PDFKit helper."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from research_radar.analysis.figures import PdfCropBox, PdfPageBbox, PdfTextWord
from research_radar.security.redaction import redact_text


class PDFHelperError(RuntimeError):
    """Raised when the native PDF helper cannot safely complete an operation."""


class PDFHelperClient:
    """Launch one native helper process for each requested PDF operation."""

    def __init__(
        self,
        executable: Path,
        *,
        timeout_seconds: int = 30,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        try:
            self.executable = executable.resolve(strict=True)
        except OSError as exc:
            raise PDFHelperError("PDF helper executable is unavailable.") from exc
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise PDFHelperError("PDF helper executable is unavailable.")
        if timeout_seconds <= 0:
            raise PDFHelperError("PDF helper timeout must be positive.")
        self.timeout_seconds = timeout_seconds
        self._runner = runner

    def page_bbox(
        self,
        pdf_path: Path,
        page_number: int,
        *,
        allowed_root: Path,
    ) -> PdfPageBbox | None:
        """Return page text boxes in top-left PDF-point coordinates."""

        if page_number < 1:
            raise PDFHelperError("PDF page number must be at least 1.")
        root = _root(allowed_root)
        pdf = _existing_file(pdf_path, root)
        response = self._call(
            {
                "schema_version": 1,
                "operation": "page_text",
                "allowed_root": str(root),
                "input_path": str(pdf),
                "page_index": page_number - 1,
            }
        )
        if response.get("schema_version") != 1 or response.get("operation") != "page_text":
            raise PDFHelperError("PDF helper returned an invalid response.")
        page = _mapping(response.get("page"), "PDF page response")
        page_box = _box(page.get("page_box"))
        words_value = page.get("words")
        if not isinstance(words_value, list):
            raise PDFHelperError("PDF helper returned an invalid response.")
        words: list[PdfTextWord] = []
        for value in words_value:
            item = _mapping(value, "PDF word")
            text = item.get("text")
            if not isinstance(text, str):
                raise PDFHelperError("PDF helper returned an invalid response.")
            box = _box(item.get("box"))
            words.append(
                PdfTextWord(
                    text=text,
                    x_min=box[0],
                    y_min=box[1],
                    x_max=box[0] + box[2],
                    y_max=box[1] + box[3],
                )
            )
        return PdfPageBbox(width=page_box[2], height=page_box[3], words=words)

    def render_crop(
        self,
        pdf_path: Path,
        page_number: int,
        crop_box: PdfCropBox,
        destination: Path,
        *,
        dpi: int,
        allowed_root: Path,
    ) -> bool:
        """Render one policy-approved crop and verify the returned output path."""

        if page_number < 1 or dpi <= 0:
            raise PDFHelperError("PDF page number and DPI must be positive.")
        root = _root(allowed_root)
        pdf = _existing_file(pdf_path, root)
        output = _output_file(destination, root)
        response = self._call(
            {
                "schema_version": 1,
                "operation": "render_crop",
                "allowed_root": str(root),
                "input_path": str(pdf),
                "output_path": str(output),
                "page_index": page_number - 1,
                "crop": {
                    "x": crop_box.x,
                    "y": crop_box.y,
                    "width": crop_box.width,
                    "height": crop_box.height,
                },
                "scale": dpi / 72.0,
            }
        )
        if (
            response.get("schema_version") != 1
            or response.get("operation") != "render_crop"
            or response.get("output_path") != str(output)
        ):
            raise PDFHelperError("PDF helper returned an invalid response.")
        return output.is_file()

    def _call(self, request: dict[str, object]) -> dict[str, object]:
        try:
            result = self._runner(
                [str(self.executable)],
                input=json.dumps(request, sort_keys=True),
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
                env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PDFHelperError("PDF helper did not complete.") from exc
        if result.returncode != 0:
            detail = redact_text(result.stderr)[:300].strip()
            raise PDFHelperError(detail or "PDF helper failed.")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PDFHelperError("PDF helper returned an invalid response.") from exc
        return _mapping(value, "PDF helper response")


def app_figure_extractor(client: PDFHelperClient, *, allowed_root: Path):
    """Build an extractor that keeps policy in Python and mechanics in PDFKit."""

    from research_radar.analysis.figures import extract_paper_figures

    def extract(artifact, output_dir, claims):
        return extract_paper_figures(
            artifact,
            output_dir,
            claims,
            pdf_page_bbox_reader=lambda path, page: client.page_bbox(
                path, page, allowed_root=allowed_root
            ),
            pdf_crop_renderer=lambda path, page, crop, destination: client.render_crop(
                path,
                page,
                crop,
                destination,
                dpi=160,
                allowed_root=allowed_root,
            ),
        )

    return extract


def _root(path: Path) -> Path:
    try:
        root = path.resolve(strict=True)
    except OSError as exc:
        raise PDFHelperError("PDF allowed root is unavailable.") from exc
    if not root.is_dir():
        raise PDFHelperError("PDF allowed root must be a directory.")
    return root


def _existing_file(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise PDFHelperError("PDF path must stay within the allowed root.") from exc
    if path.is_symlink() or not resolved.is_file():
        raise PDFHelperError("PDF path must be a regular file within the allowed root.")
    return resolved


def _output_file(path: Path, root: Path) -> Path:
    try:
        parent = path.parent.resolve(strict=True)
        parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise PDFHelperError("PDF output must stay within the allowed root.") from exc
    if path.is_symlink() or not parent.is_dir():
        raise PDFHelperError("PDF output must be a regular path within the allowed root.")
    return parent / path.name


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PDFHelperError(f"{label} is invalid.")
    return value


def _box(value: Any) -> tuple[float, float, float, float]:
    item = _mapping(value, "PDF box")
    if set(item) != {"x", "y", "width", "height"}:
        raise PDFHelperError("PDF helper returned an invalid response.")
    numbers = tuple(item[key] for key in ("x", "y", "width", "height"))
    if any(isinstance(number, bool) or not isinstance(number, int | float) for number in numbers):
        raise PDFHelperError("PDF helper returned an invalid response.")
    x, y, width, height = (float(number) for number in numbers)
    if width <= 0 or height <= 0:
        raise PDFHelperError("PDF helper returned an invalid response.")
    return x, y, width, height
