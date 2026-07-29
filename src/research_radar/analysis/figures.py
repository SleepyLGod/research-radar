"""Best-effort paper figure extraction for reader-facing drafts."""

from __future__ import annotations

import gzip
import io
import re
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

from research_radar.analysis.figure_text import (
    FIGURE_EXPLANATION_SOURCE_CONTEXT,
)
from research_radar.discovery.dedupe import canonicalize_url
from research_radar.evidence.policy import publishable_claims
from research_radar.models import Artifact, Claim, SourceCandidate
from research_radar.storage.files import ensure_dir

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".eps"}
RASTER_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
FIGURE_KEYWORD_WEIGHTS = {
    "architecture": 3.0,
    "framework": 2.6,
    "pipeline": 2.6,
    "system": 2.2,
    "overview": 2.2,
    "method": 2.0,
    "mechanism": 2.0,
    "design": 1.8,
    "benchmark": 1.8,
    "evaluation": 1.8,
    "result": 1.6,
    "ablation": 1.6,
    "performance": 1.4,
    "table": 1.0,
}
FIGURE_KEYWORDS = tuple(FIGURE_KEYWORD_WEIGHTS)
PDF_FIGURE_CROP_DPI = 160
PDF_MIN_CROP_WIDTH = 180
PDF_MIN_CROP_HEIGHT = 120
PDF_MAX_CROP_HEIGHT_RATIO = 0.62
PDF_COLUMN_GAP_RATIO = 0.04
PDF_MAX_EDGE_DARK_RATIO = 0.02


class FigureExtractionError(Exception):
    """Raised when arXiv source figure extraction fails."""


@dataclass(frozen=True)
class PaperFigure:
    """A selected figure asset for a paper draft."""

    title: str
    source_url: str
    source_title: str
    asset_path: str
    relative_path: str
    original_path: str
    caption: str
    label: str | None
    explanation: str
    matched_claim: str | None
    license: str
    reuse_status: str
    attribution: str
    renderable: bool
    score: float

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""

        return {
            "title": self.title,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "asset_path": self.asset_path,
            "relative_path": self.relative_path,
            "original_path": self.original_path,
            "caption": self.caption,
            "label": self.label,
            "explanation": self.explanation,
            "matched_claim": self.matched_claim,
            "license": self.license,
            "reuse_status": self.reuse_status,
            "attribution": self.attribution,
            "renderable": self.renderable,
            "score": self.score,
        }


@dataclass(frozen=True)
class FigureCandidate:
    """A parsed figure reference before ranking and copying."""

    image_path: Path
    original_path: str
    caption: str
    label: str | None
    score: float


@dataclass(frozen=True)
class PdfFigureCandidate:
    """A figure caption located in extracted PDF text."""

    page_number: int
    figure_number: str
    caption: str
    label: str | None
    score: float


@dataclass(frozen=True)
class PdfTextWord:
    """A positioned word from Poppler bbox output."""

    text: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class PdfPageBbox:
    """Positioned text for one PDF page."""

    width: float
    height: float
    words: list[PdfTextWord]


@dataclass(frozen=True)
class PdfCropBox:
    """Crop box expressed in PDF points until the render boundary."""

    x: int
    y: int
    width: int
    height: int


def extract_paper_figures(
    artifact: Artifact,
    output_dir: Path,
    claims: list[Claim],
    *,
    max_figures: int = 3,
) -> list[PaperFigure]:
    """Download arXiv source and extract selected figure assets."""

    arxiv_id = _arxiv_id(artifact.source)
    if not arxiv_id:
        figure_root = output_dir / _safe_name(
            artifact.source.canonical_id or artifact.source.title
        )
        return extract_pdf_cropped_figures(
            artifact,
            ensure_dir(figure_root),
            claims,
            max_figures=max_figures,
        )
    work_dir = ensure_dir(output_dir / _safe_name(arxiv_id))
    source_dir = ensure_dir(work_dir / "source")
    image_dir = ensure_dir(work_dir / "images")
    try:
        _download_arxiv_source(arxiv_id, source_dir)
        return extract_latex_figures(
            source_dir,
            image_dir,
            artifact.source,
            claims,
            max_figures=max_figures,
        )
    except FigureExtractionError:
        return extract_pdf_cropped_figures(
            artifact,
            image_dir,
            claims,
            max_figures=max_figures,
        )


def extract_pdf_cropped_figures(
    artifact: Artifact,
    image_dir: Path,
    claims: list[Claim],
    *,
    max_figures: int = 3,
) -> list[PaperFigure]:
    """Crop selected PDF figure regions when source figures are unavailable."""

    if artifact.content_type != "application/pdf" or not artifact.artifact_path:
        return []
    pdf_path = Path(artifact.artifact_path)
    if not pdf_path.is_file():
        return []
    ensure_dir(image_dir)
    candidates = sorted(
        _parse_pdf_figure_candidates(artifact.text),
        key=lambda item: item.score,
        reverse=True,
    )
    figures: list[PaperFigure] = []
    used_pages: set[int] = set()
    for candidate in candidates:
        if len(figures) >= max_figures:
            break
        if candidate.page_number in used_pages:
            continue
        matched_claim = _best_matching_claim(candidate.caption, claims, source=artifact.source)
        if matched_claim is None:
            continue
        crop_box = _pdf_caption_crop_box(pdf_path, candidate)
        if crop_box is None:
            continue
        destination = (
            image_dir
            / f"{len(figures) + 1:02d}-figure-{candidate.figure_number}-page-"
            f"{candidate.page_number}.png"
        )
        if not _render_pdf_crop(pdf_path, candidate.page_number, crop_box, destination):
            continue
        if not _rendered_crop_is_publishable(destination):
            continue
        used_pages.add(candidate.page_number)
        figures.append(
            PaperFigure(
                title=candidate.label or _pdf_figure_title(candidate.caption),
                source_url=artifact.source.url,
                source_title=artifact.source.title,
                asset_path=str(destination),
                relative_path=_relative_figure_path(destination),
                original_path=(
                    f"page {candidate.page_number}, Figure "
                    f"{candidate.figure_number} crop"
                ),
                caption=candidate.caption,
                label=candidate.label,
                explanation=_figure_explanation(candidate.caption, matched_claim),
                matched_claim=matched_claim.text,
                license=_source_license(artifact.source),
                reuse_status=_reuse_status(artifact.source),
                attribution=_attribution(artifact.source),
                renderable=True,
                score=round(candidate.score, 3),
            )
        )
    return figures


def extract_latex_figures(
    source_dir: Path,
    image_dir: Path,
    source: SourceCandidate,
    claims: list[Claim],
    *,
    max_figures: int = 3,
) -> list[PaperFigure]:
    """Extract selected figures from a local LaTeX source tree."""

    ensure_dir(image_dir)
    candidates = _parse_figure_candidates(source_dir)
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    figures = []
    for candidate in ranked:
        if len(figures) >= max_figures:
            break
        matched_claim = _best_matching_claim(candidate.caption, claims, source=source)
        if matched_claim is None:
            continue
        destination = image_dir / f"{len(figures) + 1:02d}-{candidate.image_path.name}"
        asset_path, renderable = _copy_or_convert_asset(candidate.image_path, destination)
        figures.append(
            PaperFigure(
                title=_figure_title(candidate),
                source_url=source.url,
                source_title=source.title,
                asset_path=str(asset_path),
                relative_path=_relative_figure_path(asset_path),
                original_path=candidate.original_path,
                caption=candidate.caption,
                label=candidate.label,
                explanation=_figure_explanation(candidate.caption, matched_claim),
                matched_claim=matched_claim.text if matched_claim else None,
                license=_source_license(source),
                reuse_status=_reuse_status(source),
                attribution=_attribution(source),
                renderable=renderable,
                score=round(candidate.score, 3),
            )
        )
    return figures


def _download_arxiv_source(arxiv_id: str, source_dir: Path) -> None:
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    request = Request(url, headers={"User-Agent": "ResearchRadar/0.0.0"})
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read()
    except OSError as exc:
        raise FigureExtractionError(f"Failed to download arXiv source: {arxiv_id}") from exc
    _unpack_source_payload(payload, source_dir)


def _unpack_source_payload(payload: bytes, source_dir: Path) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            _safe_extract_tar(archive, source_dir)
            return
    except tarfile.TarError:
        pass
    try:
        payload = gzip.decompress(payload)
    except OSError:
        pass
    (source_dir / "source.tex").write_bytes(payload)


def _safe_extract_tar(archive: tarfile.TarFile, source_dir: Path) -> None:
    root = source_dir.resolve()
    for member in archive.getmembers():
        if not member.isfile():
            continue
        target = (source_dir / member.name).resolve()
        if root not in target.parents and target != root:
            continue
        ensure_dir(target.parent)
        extracted = archive.extractfile(member)
        if extracted is None:
            continue
        target.write_bytes(extracted.read())


def _parse_figure_candidates(source_dir: Path) -> list[FigureCandidate]:
    tex_files = list(source_dir.rglob("*.tex"))
    candidates: list[FigureCandidate] = []
    for tex_path in tex_files:
        text = tex_path.read_text(encoding="utf-8", errors="ignore")
        for block in _figure_blocks(text):
            caption = _latex_command_arg(block, "caption")
            label = _latex_command_arg(block, "label")
            for raw_image in _includegraphics_paths(block):
                image_path = _resolve_image_path(source_dir, tex_path.parent, raw_image)
                if image_path is None:
                    continue
                candidates.append(
                    FigureCandidate(
                        image_path=image_path,
                        original_path=raw_image,
                        caption=_clean_latex_text(caption),
                        label=_clean_latex_text(label) or None,
                        score=_figure_score(raw_image, caption, label),
                    )
                )
    return candidates


def _figure_blocks(text: str) -> list[str]:
    pattern = re.compile(
        r"\\begin\{figure\*?\}(?P<body>.*?)\\end\{figure\*?\}",
        re.DOTALL,
    )
    return [match.group("body") for match in pattern.finditer(text)]


def _includegraphics_paths(block: str) -> list[str]:
    pattern = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^}]+)\}")
    return [match.group("path").strip() for match in pattern.finditer(block)]


def _latex_command_arg(block: str, command: str) -> str:
    marker = f"\\{command}"
    start = block.find(marker)
    if start < 0:
        return ""
    brace_start = block.find("{", start + len(marker))
    if brace_start < 0:
        return ""
    depth = 0
    for index in range(brace_start, len(block)):
        char = block[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return block[brace_start + 1 : index]
    return ""


def _resolve_image_path(source_dir: Path, tex_dir: Path, raw_image: str) -> Path | None:
    raw_path = Path(raw_image)
    direct_candidates = [tex_dir / raw_path, source_dir / raw_path]
    for candidate in direct_candidates:
        resolved = _with_known_extension(candidate, source_dir=source_dir)
        if resolved is not None:
            return resolved
    stem = raw_path.name
    for candidate in source_dir.rglob("*"):
        if not candidate.is_file() or candidate.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        if candidate.name == stem or candidate.stem == stem:
            return candidate
    return None


def _with_known_extension(path: Path, *, source_dir: Path) -> Path | None:
    if (
        path.is_file()
        and path.suffix.casefold() in IMAGE_EXTENSIONS
        and _is_under(path, source_dir)
    ):
        return path
    if path.suffix:
        return None
    for extension in IMAGE_EXTENSIONS:
        candidate = path.with_suffix(extension)
        if candidate.is_file() and _is_under(candidate, source_dir):
            return candidate
    return None


def _copy_or_convert_asset(source_path: Path, destination: Path) -> tuple[Path, bool]:
    suffix = source_path.suffix.casefold()
    if suffix in RASTER_EXTENSIONS:
        shutil.copyfile(source_path, destination)
        return destination, True
    converted = destination.with_suffix(".png")
    if suffix == ".svg" and _convert_svg_to_png(source_path, converted):
        return converted, True
    if suffix == ".pdf" and _convert_pdf_to_png(source_path, converted):
        return converted, True
    if suffix == ".eps" and _convert_eps_to_png(source_path, converted):
        return converted, True
    shutil.copyfile(source_path, destination)
    return destination, False


def _convert_pdf_to_png(source_path: Path, destination: Path) -> bool:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return _convert_with_sips(source_path, destination)
    output_prefix = destination.with_suffix("")
    try:
        subprocess.run(
            [
                pdftoppm,
                "-png",
                "-singlefile",
                str(source_path),
                str(output_prefix),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return destination.is_file()


def _convert_eps_to_png(source_path: Path, destination: Path) -> bool:
    return _convert_with_sips(source_path, destination)


def _convert_svg_to_png(source_path: Path, destination: Path) -> bool:
    converter = shutil.which("rsvg-convert")
    if converter:
        try:
            subprocess.run(
                [converter, "-o", str(destination), str(source_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return _convert_with_sips(source_path, destination)
        return destination.is_file()
    return _convert_with_sips(source_path, destination)


def _convert_with_sips(source_path: Path, destination: Path) -> bool:
    sips = shutil.which("sips")
    if not sips:
        return False
    try:
        subprocess.run(
            [sips, "-s", "format", "png", str(source_path), "--out", str(destination)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return destination.is_file()


def _is_under(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    resolved_root = root.resolve()
    return resolved == resolved_root or resolved_root in resolved.parents


def _parse_pdf_figure_candidates(text: str) -> list[PdfFigureCandidate]:
    candidates: list[PdfFigureCandidate] = []
    for page_number, page_text in _pdf_pages(text):
        lines = page_text.splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"(?i)^\s*Figure\s+(?P<number>\d+)\s*[:.]\s*.+", line)
            if not match:
                continue
            caption = _clean_latex_text(_pdf_caption_from_lines(lines, index))
            if not caption:
                continue
            label = f"Figure {match.group('number')}"
            candidates.append(
                PdfFigureCandidate(
                    page_number=page_number,
                    figure_number=match.group("number"),
                    caption=caption,
                    label=label,
                    score=_figure_score(label, caption, label),
                )
            )
    return candidates


def _pdf_caption_from_lines(lines: list[str], start_index: int) -> str:
    caption_lines = [lines[start_index].strip()]
    for line in lines[start_index + 1 : start_index + 8]:
        stripped = line.strip()
        if not stripped:
            break
        if re.match(r"(?i)^(Figure|Table)\s+\d+\s*[:.]", stripped):
            break
        if re.match(r"^\d+(?:\.\d+)*\s+[A-Z][A-Za-z]", stripped):
            break
        caption_text = " ".join(caption_lines).strip()
        if caption_text.endswith(".") and len(caption_text) >= 80:
            break
        caption_lines.append(stripped)
        caption_text = " ".join(caption_lines).strip()
        if caption_text.endswith(".") and len(caption_text) >= 120:
            break
    return " ".join(caption_lines)


def _pdf_pages(text: str) -> list[tuple[int, str]]:
    pattern = re.compile(r"(?m)^\[page (?P<page>\d+)\]\s*$")
    matches = list(pattern.finditer(text))
    if not matches:
        return [(1, text)]
    pages: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append((int(match.group("page")), text[start:end]))
    return pages


def _pdf_caption_crop_box(
    pdf_path: Path,
    candidate: PdfFigureCandidate,
) -> PdfCropBox | None:
    page = _pdf_page_bbox(pdf_path, candidate.page_number)
    if page is None:
        return _pypdf_caption_crop_box(pdf_path, candidate)
    crop_box = _pdf_caption_crop_box_from_bbox(page, candidate)
    if crop_box is None:
        return None
    if not _pdf_crop_text_is_publishable(
        page,
        crop_box,
        figure_number=candidate.figure_number,
    ):
        return None
    return crop_box


def _pdf_caption_crop_box_from_bbox(
    page: PdfPageBbox,
    candidate: PdfFigureCandidate,
) -> PdfCropBox | None:
    if page is None:
        return None
    caption_line = _caption_line_words(page.words, candidate.figure_number)
    if not caption_line:
        return None

    caption_top = min(word.y_min for word in caption_line)
    caption_left = min(word.x_min for word in caption_line)
    caption_right = max(word.x_max for word in caption_line)
    if caption_top <= page.height * 0.12:
        return None

    x, width = _pdf_caption_column(page, caption_left, caption_right)
    horizontal_padding = max(8, int(page.width * 0.015))
    x = max(0, x + horizontal_padding)
    width = min(page.width - x, width - (horizontal_padding * 2))

    top = _pdf_crop_top_from_text_gap(page, x, x + width, caption_top)
    if top is None:
        return None
    bottom = max(top, caption_top - 8)
    height = bottom - top
    max_height = page.height * PDF_MAX_CROP_HEIGHT_RATIO
    if (
        width < PDF_MIN_CROP_WIDTH
        or height < PDF_MIN_CROP_HEIGHT
        or height > max_height
    ):
        return None
    return PdfCropBox(
        x=max(0, int(round(x))),
        y=max(0, int(round(top))),
        width=max(1, int(round(width))),
        height=max(1, int(round(height))),
    )


def _pypdf_caption_crop_box(
    pdf_path: Path,
    candidate: PdfFigureCandidate,
) -> PdfCropBox | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(pdf_path))
        page = reader.pages[candidate.page_number - 1]
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
    except (IndexError, OSError, ValueError):
        return None

    target = f"figure{candidate.figure_number}"
    marks: list[tuple[float, float, float]] = []

    def visitor(
        text: str,
        cm: object,
        tm: object,
        font_dict: object,
        font_size: object,
    ) -> None:
        if not _pdf_word_key(text).startswith(target):
            return
        if not isinstance(tm, list | tuple) or len(tm) < 6:
            return
        try:
            marks.append((float(tm[4]), float(tm[5]), float(font_size or 10.0)))
        except (TypeError, ValueError):
            return

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return None
    if not marks:
        return None

    _, caption_y, caption_font_size = max(marks, key=lambda item: item[1])
    caption_top = page_height - (caption_y + caption_font_size)
    if caption_top <= page_height * 0.08 or caption_top >= page_height * 0.55:
        return None

    horizontal_margin = max(12.0, page_width * 0.09)
    top_margin = max(12.0, page_height * 0.045)
    bottom = caption_top - max(6.0, caption_font_size)
    width = page_width - (horizontal_margin * 2)
    height = bottom - top_margin
    if width < PDF_MIN_CROP_WIDTH or height < PDF_MIN_CROP_HEIGHT:
        return None
    if height > page_height * PDF_MAX_CROP_HEIGHT_RATIO:
        return None
    return PdfCropBox(
        x=max(0, int(round(horizontal_margin))),
        y=max(0, int(round(top_margin))),
        width=max(1, int(round(width))),
        height=max(1, int(round(height))),
    )


def _pdf_page_bbox(pdf_path: Path, page_number: int) -> PdfPageBbox | None:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return None
    try:
        result = subprocess.run(
            [
                pdftotext,
                "-bbox-layout",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                str(pdf_path),
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _parse_pdf_bbox_output(result.stdout)


def _parse_pdf_bbox_output(output: str) -> PdfPageBbox | None:
    html_start = output.find("<html")
    if html_start > 0:
        output = output[html_start:]
    try:
        root = ET.fromstring(output)
    except ET.ParseError:
        return None
    page_element = next((node for node in root.iter() if _xml_name(node.tag) == "page"), None)
    if page_element is None:
        return None
    try:
        page_width = float(page_element.attrib["width"])
        page_height = float(page_element.attrib["height"])
    except (KeyError, ValueError):
        return None
    words: list[PdfTextWord] = []
    for node in page_element.iter():
        if _xml_name(node.tag) != "word":
            continue
        text = "".join(node.itertext()).strip()
        if not text:
            continue
        try:
            words.append(
                PdfTextWord(
                    text=text,
                    x_min=float(node.attrib["xMin"]),
                    y_min=float(node.attrib["yMin"]),
                    x_max=float(node.attrib["xMax"]),
                    y_max=float(node.attrib["yMax"]),
                )
            )
        except (KeyError, ValueError):
            continue
    if not words:
        return None
    return PdfPageBbox(width=page_width, height=page_height, words=words)


def _caption_line_words(words: list[PdfTextWord], figure_number: str) -> list[PdfTextWord]:
    for index, word in enumerate(words[:-1]):
        if _pdf_word_key(word.text) != "figure":
            continue
        next_word = _pdf_word_key(words[index + 1].text)
        if next_word != figure_number:
            continue
        line_y = (word.y_min + word.y_max + words[index + 1].y_min + words[index + 1].y_max) / 4
        tolerance = max(5.0, (word.y_max - word.y_min) * 0.9)
        same_line = sorted(
            [
                item
                for item in words
                if abs(((item.y_min + item.y_max) / 2) - line_y) <= tolerance
            ],
            key=lambda item: item.x_min,
        )
        try:
            figure_index = same_line.index(word)
        except ValueError:
            return []
        if figure_index + 1 >= len(same_line):
            return []
        caption_words = same_line[figure_index : figure_index + 2]
        max_gap = max(12.0, (word.y_max - word.y_min) * 1.2)
        for item in same_line[figure_index + 2 :]:
            if item.x_min - caption_words[-1].x_max > max_gap:
                break
            caption_words.append(item)
        return caption_words
    return []


def _pdf_crop_text_is_publishable(
    page: PdfPageBbox,
    crop_box: PdfCropBox,
    *,
    figure_number: str,
) -> bool:
    """Reject crops that visibly include article text or another float caption."""

    crop_right = crop_box.x + crop_box.width
    crop_bottom = crop_box.y + crop_box.height
    words = [
        word
        for word in page.words
        if crop_box.x <= (word.x_min + word.x_max) / 2 <= crop_right
        and crop_box.y <= (word.y_min + word.y_max) / 2 <= crop_bottom
    ]
    paragraph_lines = 0
    for line in _pdf_words_by_line(words):
        normalized = "".join(_pdf_word_key(word.text) for word in line)
        if normalized.startswith("table"):
            return False
        figure_match = re.match(r"^figure(?P<number>\d+)", normalized)
        if figure_match and figure_match.group("number") != figure_number:
            return False
        line_width = max(word.x_max for word in line) - min(word.x_min for word in line)
        if len(line) >= 7 and line_width >= crop_box.width * 0.65:
            paragraph_lines += 1
    return paragraph_lines < 3


def _pdf_words_by_line(words: list[PdfTextWord]) -> list[list[PdfTextWord]]:
    """Group positioned PDF words into approximate visual lines."""

    lines: list[list[PdfTextWord]] = []
    for word in sorted(words, key=lambda item: (item.y_min, item.x_min)):
        center = (word.y_min + word.y_max) / 2
        target = next(
            (
                line
                for line in lines
                if min(item.y_min for item in line) - 4
                <= center
                <= max(item.y_max for item in line) + 4
            ),
            None,
        )
        if target is None:
            lines.append([word])
        else:
            target.append(word)
    return [sorted(line, key=lambda item: item.x_min) for line in lines]


def _pdf_caption_column(
    page: PdfPageBbox,
    caption_left: float,
    caption_right: float,
) -> tuple[float, float]:
    caption_width = caption_right - caption_left
    if caption_width >= page.width * 0.45:
        return 0.0, page.width
    gap = page.width * PDF_COLUMN_GAP_RATIO
    midpoint = page.width / 2
    if ((caption_left + caption_right) / 2) < midpoint:
        return 0.0, midpoint - (gap / 2)
    return midpoint + (gap / 2), midpoint - (gap / 2)


def _pdf_crop_top_from_text_gap(
    page: PdfPageBbox,
    crop_left: float,
    crop_right: float,
    caption_top: float,
) -> float | None:
    lines = _pdf_text_lines(
        [
            word
            for word in page.words
            if word.x_max >= crop_left
            and word.x_min <= crop_right
            and word.y_max < caption_top - 4
        ]
    )
    if not lines:
        return max(0.0, caption_top - min(page.height * 0.36, 360.0))

    previous_bottom = None
    best_gap = 0.0
    best_top: float | None = None
    for line_top, line_bottom in lines:
        if previous_bottom is not None:
            gap = line_top - previous_bottom
            if gap > best_gap:
                best_gap = gap
                best_top = previous_bottom
        previous_bottom = max(previous_bottom or 0.0, line_bottom)
    if previous_bottom is not None:
        gap = caption_top - previous_bottom
        if gap > best_gap:
            best_gap = gap
            best_top = previous_bottom

    min_gap = max(20.0, page.height * 0.025)
    if best_top is None or best_gap < min_gap:
        return None
    return min(page.height, max(0.0, best_top + 4))


def _pdf_text_lines(words: list[PdfTextWord]) -> list[tuple[float, float]]:
    lines: list[tuple[float, float]] = []
    for word in sorted(words, key=lambda item: (item.y_min, item.x_min)):
        center = (word.y_min + word.y_max) / 2
        matched_index = None
        for index, (line_top, line_bottom) in enumerate(lines):
            if line_top - 4 <= center <= line_bottom + 4:
                matched_index = index
                break
        if matched_index is None:
            lines.append((word.y_min, word.y_max))
        else:
            line_top, line_bottom = lines[matched_index]
            lines[matched_index] = (min(line_top, word.y_min), max(line_bottom, word.y_max))
    return sorted(lines)


def _render_pdf_crop(
    pdf_path: Path,
    page_number: int,
    crop_box: PdfCropBox,
    destination: Path,
) -> bool:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return False
    output_prefix = destination.with_suffix("")
    pixel_crop = _pdf_points_to_pixels(crop_box)
    try:
        subprocess.run(
            [
                pdftoppm,
                "-png",
                "-singlefile",
                "-r",
                str(PDF_FIGURE_CROP_DPI),
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-x",
                str(pixel_crop.x),
                "-y",
                str(pixel_crop.y),
                "-W",
                str(pixel_crop.width),
                "-H",
                str(pixel_crop.height),
                str(pdf_path),
                str(output_prefix),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return destination.is_file()


def _pdf_points_to_pixels(crop_box: PdfCropBox) -> PdfCropBox:
    """Convert one PDF-point crop box to pdftoppm pixel coordinates."""

    scale = PDF_FIGURE_CROP_DPI / 72.0
    return PdfCropBox(
        x=max(0, int(round(crop_box.x * scale))),
        y=max(0, int(round(crop_box.y * scale))),
        width=max(1, int(round(crop_box.width * scale))),
        height=max(1, int(round(crop_box.height * scale))),
    )


def _rendered_crop_is_publishable(path: Path) -> bool:
    """Reject blank or visibly clipped PNG crops before public rendering."""

    try:
        with Image.open(path) as image:
            grayscale = image.convert("L")
    except (OSError, UnidentifiedImageError):
        return False
    width, height = grayscale.size
    if width < PDF_MIN_CROP_WIDTH or height < PDF_MIN_CROP_HEIGHT:
        return False
    border = max(2, int(round(min(width, height) * 0.015)))
    edges = (
        grayscale.crop((0, 0, width, border)),
        grayscale.crop((0, height - border, width, height)),
        grayscale.crop((0, 0, border, height)),
        grayscale.crop((width - border, 0, width, height)),
    )
    for edge in edges:
        pixels = edge.tobytes()
        if (
            pixels
            and sum(value < 245 for value in pixels) / len(pixels)
            > PDF_MAX_EDGE_DARK_RATIO
        ):
            return False
    return True


def _xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _pdf_word_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", value).casefold()


def _pdf_figure_title(caption: str) -> str:
    match = re.match(r"(?i)\s*(figure\s+\d+)", caption)
    return match.group(1).title() if match else caption[:80]


def _figure_score(raw_image: str, caption: str, label: str) -> float:
    text = f"{raw_image} {caption} {label}".casefold()
    score = 0.0
    for keyword, weight in FIGURE_KEYWORD_WEIGHTS.items():
        if keyword in text:
            score += weight
    if "fig:" in text and ("architecture" in text or "framework" in text):
        score += 0.8
    if "appendix" in text or "supplement" in text:
        score -= 1.0
    return score


def _best_matching_claim(
    caption: str,
    claims: list[Claim],
    *,
    source: SourceCandidate,
) -> Claim | None:
    verified = [
        claim for claim in publishable_claims(claims) if _claim_matches_source(claim, source)
    ]
    if not verified:
        return None
    caption_tokens = _tokens(caption)
    best_claim = None
    best_score = 0
    for claim in verified:
        score = len(caption_tokens & _tokens(claim.text))
        if score > best_score:
            best_claim = claim
            best_score = score
    return best_claim if best_score >= 2 else None


def _claim_matches_source(claim: Claim, source: SourceCandidate) -> bool:
    source_url = canonicalize_url(source.url)
    source_arxiv = _arxiv_id(source)
    source_openreview = _openreview_id(source)
    for anchor in claim.evidence:
        anchor_openreview = _openreview_id_from_text(anchor.source_url)
        if source_openreview or anchor_openreview:
            if source_openreview and anchor_openreview:
                return source_openreview == anchor_openreview
            continue
        anchor_url = canonicalize_url(anchor.source_url)
        if source_url and anchor_url == source_url:
            return True
        anchor_arxiv = _arxiv_id_from_text(anchor.source_url)
        if source_arxiv and anchor_arxiv:
            return _arxiv_family(source_arxiv) == _arxiv_family(anchor_arxiv)
    return False


def _figure_explanation(caption: str, claim: Claim | None) -> str:
    if claim is None:
        return FIGURE_EXPLANATION_SOURCE_CONTEXT
    return f"Visual context for this verified point: {claim.text}"


def _figure_title(candidate: FigureCandidate) -> str:
    if candidate.label:
        return candidate.label
    if candidate.caption:
        return candidate.caption[:80]
    return candidate.image_path.stem


def _relative_figure_path(path: Path) -> str:
    parts = path.parts
    if "figures" in parts:
        index = parts.index("figures")
        return "/".join(parts[index:])
    return path.name


def _arxiv_id(source: SourceCandidate) -> str | None:
    external_ids = source.metadata.get("external_ids")
    if isinstance(external_ids, dict):
        value = external_ids.get("ArXiv") or external_ids.get("arxiv")
        if isinstance(value, str) and value:
            return value.removeprefix("arXiv:")
    if source.canonical_id:
        canonical = source.canonical_id
        if canonical.startswith("ArXiv:"):
            return canonical.removeprefix("ArXiv:")
        if canonical.startswith("DOI:10.48550/arXiv."):
            return canonical.removeprefix("DOI:10.48550/arXiv.")
        if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", canonical):
            return canonical
    return _arxiv_id_from_text(source.url)


def _openreview_id(source: SourceCandidate) -> str | None:
    if source.canonical_id and source.canonical_id.startswith("OpenReview:"):
        return source.canonical_id.removeprefix("OpenReview:")
    return _openreview_id_from_text(source.url)


def _openreview_id_from_text(value: str) -> str | None:
    match = re.search(r"openreview\.net/(?:forum|pdf)\?id=([^&#\s]+)", value)
    return match.group(1) if match else None


def _arxiv_id_from_text(value: str) -> str | None:
    match = re.search(
        r"(?:arxiv[:./\s]|10\.48550/arxiv\.|arxiv\.org/(?:abs|pdf|html)/)"
        r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)",
        value,
        re.IGNORECASE,
    )
    return match.group("id") if match else None


def _arxiv_family(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)


def _source_license(source: SourceCandidate) -> str:
    value = source.metadata.get("license") or source.metadata.get("license_url")
    if isinstance(value, str) and value:
        return value
    return "unknown"


def _reuse_status(source: SourceCandidate) -> str:
    license_value = _source_license(source).casefold()
    if "creativecommons.org/licenses/by/" in license_value or "cc by" in license_value:
        return "allowed_with_attribution"
    if "creativecommons.org/publicdomain/zero" in license_value or "cc0" in license_value:
        return "allowed_public_domain"
    return "needs_manual_review"


def _attribution(source: SourceCandidate) -> str:
    authors = ", ".join(source.authors[:3])
    if authors and len(source.authors) > 3:
        authors += " et al."
    if authors:
        return f"{source.title}; {authors}; {source.url}"
    return f"{source.title}; {source.url}"


def _clean_latex_text(value: str) -> str:
    cleaned = _strip_latex_comments(value)
    cleaned = cleaned.replace(r"\%", "%")
    cleaned = cleaned.replace("~", " ")
    cleaned = cleaned.replace(r"\times", "×").replace(r"\Delta", "∆")
    cleaned = re.sub(r"\\\((.*?)\\\)", r"\1", cleaned)
    cleaned = re.sub(r"\$([^$\n]{1,160})\$", r"\1", cleaned)
    cleaned = cleaned.replace("$", "")
    cleaned = re.sub(
        r"\\(?:text|mathrm|emph|textbf|textit)\{([^{}]*)\}",
        r"\1",
        cleaned,
    )
    cleaned = re.sub(
        r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?",
        lambda match: match.group(1) or "",
        cleaned,
    )
    cleaned = cleaned.replace("{", "").replace("}", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _strip_latex_comments(value: str) -> str:
    lines = []
    for line in value.splitlines():
        cut_at = len(line)
        for index, char in enumerate(line):
            if char == "%" and (index == 0 or line[index - 1] != "\\"):
                cut_at = index
                break
        lines.append(line[:cut_at])
    return "\n".join(lines)


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", value)}


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "paper"
