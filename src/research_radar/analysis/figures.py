"""Best-effort paper figure extraction for reader-facing drafts."""

from __future__ import annotations

import gzip
import io
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from research_radar.analysis.figure_text import (
    FIGURE_EXPLANATION_CAPTION_ALIGNMENT_PREFIX,
    FIGURE_EXPLANATION_SOURCE_CONTEXT,
)
from research_radar.discovery.dedupe import canonicalize_url
from research_radar.evidence.policy import publishable_claims
from research_radar.models import Artifact, Claim, SourceCandidate
from research_radar.storage.files import ensure_dir

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".eps"}
RASTER_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
FIGURE_KEYWORDS = (
    "method",
    "architecture",
    "framework",
    "pipeline",
    "system",
    "overview",
    "benchmark",
    "evaluation",
    "result",
    "ablation",
    "performance",
    "table",
)


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
        return []
    work_dir = ensure_dir(output_dir / _safe_name(arxiv_id))
    source_dir = ensure_dir(work_dir / "source")
    image_dir = ensure_dir(work_dir / "images")
    _download_arxiv_source(arxiv_id, source_dir)
    return extract_latex_figures(
        source_dir,
        image_dir,
        artifact.source,
        claims,
        max_figures=max_figures,
    )


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


def _figure_score(raw_image: str, caption: str, label: str) -> float:
    text = f"{raw_image} {caption} {label}".casefold()
    score = 0.0
    for keyword in FIGURE_KEYWORDS:
        if keyword in text:
            score += 1.0
    if "overview" in text or "architecture" in text:
        score += 1.5
    if "appendix" in text or "supplement" in text:
        score -= 0.5
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
    for anchor in claim.evidence:
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
    return f"{FIGURE_EXPLANATION_CAPTION_ALIGNMENT_PREFIX}{claim.text}"


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
