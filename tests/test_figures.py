from pathlib import Path

from research_radar.analysis import figures as figures_module
from research_radar.analysis.figures import extract_latex_figures, extract_pdf_cropped_figures
from research_radar.models import (
    Artifact,
    Claim,
    ClaimStatus,
    EvidenceAnchor,
    SourceCandidate,
    SourceType,
)


def test_extract_latex_figures_parses_caption_label_and_claim_link(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    image_dir = tmp_path / "figures" / "images"
    (source_dir / "figures").mkdir(parents=True)
    (source_dir / "figures" / "architecture.png").write_bytes(b"fake-png")
    (source_dir / "main.tex").write_text(
        r"""
        \begin{figure}
        \centering
        \includegraphics[width=\linewidth]{figures/architecture}
        \caption{Architecture overview for retrieval memory in the agent pipeline.}
        \label{fig:architecture}
        \end{figure}
        """,
        encoding="utf-8",
    )
    source = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
        authors=["Ada Lovelace", "Alan Turing"],
        metadata={"license_url": "https://creativecommons.org/licenses/by/4.0/"},
    )
    claim = Claim(
        text="Solution: The architecture uses retrieval memory in the agent pipeline.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                source_title=source.title,
                quote="retrieval memory in the agent pipeline",
            )
        ],
    )

    figures = extract_latex_figures(source_dir, image_dir, source, [claim])

    assert len(figures) == 1
    figure = figures[0]
    assert figure.caption == "Architecture overview for retrieval memory in the agent pipeline."
    assert figure.label == "fig:architecture"
    assert figure.matched_claim == claim.text
    assert "verified observation" in figure.explanation
    assert figure.reuse_status == "allowed_with_attribution"
    assert figure.attribution == (
        "Memory Paper; Ada Lovelace, Alan Turing; https://arxiv.org/abs/2605.00001"
    )
    assert Path(figure.asset_path).exists()
    assert figure.relative_path.startswith("figures/")
    assert figure.renderable is True


def test_extract_latex_figures_skips_unmatched_figure_claim(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    image_dir = tmp_path / "figures" / "images"
    (source_dir / "plots").mkdir(parents=True)
    (source_dir / "plots" / "unrelated.pdf").write_bytes(b"fake-pdf")
    (source_dir / "main.tex").write_text(
        r"""
        \begin{figure}
        \includegraphics{plots/unrelated}
        \caption{Architecture overview for an unrelated tokenizer component.}
        \label{fig:appendix}
        \end{figure}
        """,
        encoding="utf-8",
    )
    source = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )
    claim = Claim(
        text="Solution: The paper evaluates agent memory retrieval.",
        status=ClaimStatus.SUPPORTED,
        evidence=[EvidenceAnchor(source_url=source.url, quote="agent memory retrieval")],
    )

    figures = extract_latex_figures(source_dir, image_dir, source, [claim])

    assert figures == []


def test_extract_latex_figures_ignores_paths_outside_source_tree(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    image_dir = tmp_path / "figures" / "images"
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        r"""
        \begin{figure}
        \includegraphics{../outside.png}
        \caption{Architecture overview.}
        \label{fig:outside}
        \end{figure}
        """,
        encoding="utf-8",
    )
    source = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )

    figures = extract_latex_figures(source_dir, image_dir, source, [])

    assert figures == []


def test_extract_latex_figures_converts_pdf_asset_when_tool_available(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    image_dir = tmp_path / "figures" / "images"
    (source_dir / "figures").mkdir(parents=True)
    (source_dir / "figures" / "overview.pdf").write_bytes(b"fake-pdf")
    (source_dir / "main.tex").write_text(
        r"""
        \begin{figure}
        \includegraphics{figures/overview}
        \caption{Overview of the retrieval memory architecture.}
        \label{fig:overview}
        \end{figure}
        """,
        encoding="utf-8",
    )
    source = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )
    claim = Claim(
        text="Solution: The paper describes a retrieval memory architecture.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(source_url=source.url, quote="retrieval memory architecture")
        ],
    )

    def fake_which(name: str) -> str | None:
        return "/usr/bin/fake-pdftoppm" if name == "pdftoppm" else None

    def fake_run(args: list[str], **kwargs: object) -> object:
        output_prefix = Path(args[-1])
        output_prefix.with_suffix(".png").write_bytes(b"fake-png")
        return object()

    monkeypatch.setattr(figures_module.shutil, "which", fake_which)
    monkeypatch.setattr(figures_module.subprocess, "run", fake_run)

    selected = extract_latex_figures(source_dir, image_dir, source, [claim])

    assert len(selected) == 1
    assert selected[0].renderable is True
    assert selected[0].asset_path.endswith(".png")
    assert Path(selected[0].asset_path).exists()


def test_extract_latex_figures_does_not_match_claim_from_other_paper(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    image_dir = tmp_path / "figures" / "images"
    (source_dir / "figures").mkdir(parents=True)
    (source_dir / "figures" / "architecture.png").write_bytes(b"fake-png")
    (source_dir / "main.tex").write_text(
        r"""
        \begin{figure}
        \includegraphics{figures/architecture}
        \caption{Architecture overview for retrieval memory in the agent pipeline.}
        \label{fig:architecture}
        \end{figure}
        """,
        encoding="utf-8",
    )
    source = SourceCandidate(
        title="Memory Paper A",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )
    other_claim = Claim(
        text="Solution: The architecture uses retrieval memory in the agent pipeline.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://arxiv.org/abs/2605.99999",
                quote="retrieval memory in the agent pipeline",
            )
        ],
    )

    figures = extract_latex_figures(source_dir, image_dir, source, [other_claim])

    assert figures == []


def test_extract_pdf_page_figures_renders_matched_openreview_figure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    image_dir = tmp_path / "figures" / "images"
    source = SourceCandidate(
        title="MARS Paper",
        url="https://openreview.net/forum?id=uNqTxj5brQ",
        canonical_id="OpenReview:uNqTxj5brQ",
        source_type=SourceType.PAPER,
        source_name="web_search",
    )
    artifact = Artifact(
        source=source,
        text=(
            "[page 3]\n"
            "Figure 2: MARS architecture. MARS predicts API duration and schedules "
            "requests with memory-aware handling.\n"
        ),
        artifact_path=str(pdf_path),
        content_type="application/pdf",
    )
    claim = Claim(
        text="Solution: MARS predicts API duration for memory-aware scheduling.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://openreview.net/forum?id=uNqTxj5brQ",
                quote="MARS predicts API duration",
            )
        ],
    )

    def fake_which(name: str) -> str | None:
        if name in {"pdftoppm", "pdftotext"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr(figures_module.shutil, "which", fake_which)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> object:
        calls.append(args)
        if args[0].endswith("pdftotext"):
            return figures_module.subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=_pdf_bbox_xml(
                    words=[
                        ("MARS", 45, 60, 82, 74),
                        ("uses", 86, 60, 115, 74),
                        ("scheduling", 120, 60, 188, 74),
                        ("Figure", 45, 410, 91, 425),
                        ("2:", 96, 410, 112, 425),
                        ("MARS", 116, 410, 153, 425),
                        ("architecture.", 158, 410, 240, 425),
                    ]
                ),
            )
        Path(args[-1]).with_suffix(".png").write_bytes(b"fake-crop")
        return figures_module.subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr(figures_module.subprocess, "run", fake_run)

    selected = extract_pdf_cropped_figures(artifact, image_dir, [claim])

    assert len(selected) == 1
    assert selected[0].title == "Figure 2"
    assert selected[0].original_path == "page 3, Figure 2 crop"
    assert selected[0].relative_path.startswith("figures/")
    assert "figure-2-page-3" in selected[0].asset_path
    assert Path(selected[0].asset_path).exists()
    render_call = next(call for call in calls if call[0].endswith("pdftoppm"))
    assert "-x" in render_call
    assert "-y" in render_call
    assert "-W" in render_call
    assert "-H" in render_call


def test_extract_pdf_page_figures_does_not_match_other_openreview_paper(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    source = SourceCandidate(
        title="MARS Paper",
        url="https://openreview.net/forum?id=uNqTxj5brQ",
        canonical_id="OpenReview:uNqTxj5brQ",
        source_type=SourceType.PAPER,
        source_name="web_search",
    )
    artifact = Artifact(
        source=source,
        text=(
            "[page 3]\n"
            "Figure 2: MARS architecture. MARS predicts API duration and schedules "
            "requests with memory-aware handling.\n"
        ),
        artifact_path=str(pdf_path),
        content_type="application/pdf",
    )
    claim = Claim(
        text="Solution: MARS predicts API duration for memory-aware scheduling.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://openreview.net/forum?id=different",
                quote="MARS predicts API duration",
            )
        ],
    )

    monkeypatch.setattr(figures_module.shutil, "which", lambda name: f"/usr/bin/{name}")

    selected = extract_pdf_cropped_figures(artifact, tmp_path / "figures", [claim])

    assert selected == []


def test_extract_pdf_page_figures_skips_when_caption_bbox_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    source = SourceCandidate(
        title="MARS Paper",
        url="https://openreview.net/forum?id=uNqTxj5brQ",
        canonical_id="OpenReview:uNqTxj5brQ",
        source_type=SourceType.PAPER,
        source_name="web_search",
    )
    artifact = Artifact(
        source=source,
        text="[page 3]\nFigure 2: MARS architecture for memory-aware scheduling.\n",
        artifact_path=str(pdf_path),
        content_type="application/pdf",
    )
    claim = Claim(
        text="Solution: MARS uses memory-aware scheduling.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://openreview.net/forum?id=uNqTxj5brQ",
                quote="memory-aware scheduling",
            )
        ],
    )

    monkeypatch.setattr(figures_module.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(args: list[str], **kwargs: object) -> object:
        return figures_module.subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=_pdf_bbox_xml(words=[("Not", 45, 60, 72, 74), ("caption", 80, 60, 132, 74)]),
        )

    monkeypatch.setattr(figures_module.subprocess, "run", fake_run)

    selected = extract_pdf_cropped_figures(artifact, tmp_path / "figures", [claim])

    assert selected == []


def test_extract_pdf_page_figures_skips_when_crop_is_too_small(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    source = SourceCandidate(
        title="MARS Paper",
        url="https://openreview.net/forum?id=uNqTxj5brQ",
        canonical_id="OpenReview:uNqTxj5brQ",
        source_type=SourceType.PAPER,
        source_name="web_search",
    )
    artifact = Artifact(
        source=source,
        text="[page 3]\nFigure 2: MARS architecture for memory-aware scheduling.\n",
        artifact_path=str(pdf_path),
        content_type="application/pdf",
    )
    claim = Claim(
        text="Solution: MARS uses memory-aware scheduling.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url="https://openreview.net/forum?id=uNqTxj5brQ",
                quote="memory-aware scheduling",
            )
        ],
    )

    monkeypatch.setattr(figures_module.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(args: list[str], **kwargs: object) -> object:
        return figures_module.subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=_pdf_bbox_xml(
                words=[
                    ("MARS", 45, 100, 82, 114),
                    ("Figure", 45, 150, 91, 165),
                    ("2:", 96, 150, 112, 165),
                    ("MARS", 116, 150, 153, 165),
                ]
            ),
        )

    monkeypatch.setattr(figures_module.subprocess, "run", fake_run)

    selected = extract_pdf_cropped_figures(artifact, tmp_path / "figures", [claim])

    assert selected == []


def test_parse_pdf_bbox_output_ignores_poppler_abort_preamble() -> None:
    page = figures_module._parse_pdf_bbox_output(
        "libc++abi: terminating due to uncaught exception\n"
        + _pdf_bbox_xml(words=[("Figure", 45, 410, 91, 425), ("2:", 96, 410, 112, 425)])
    )

    assert page is not None
    assert page.width == 1000
    assert page.words[0].text == "Figure"


def test_extract_latex_figures_rasterizes_svg_before_rendering(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    image_dir = tmp_path / "figures" / "images"
    (source_dir / "figures").mkdir(parents=True)
    (source_dir / "figures" / "architecture.svg").write_text(
        "<svg><script>alert(1)</script></svg>",
        encoding="utf-8",
    )
    (source_dir / "main.tex").write_text(
        r"""
        \begin{figure}
        \includegraphics{figures/architecture}
        \caption{Architecture overview for retrieval memory in the agent pipeline.}
        \label{fig:architecture}
        \end{figure}
        """,
        encoding="utf-8",
    )
    source = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )
    claim = Claim(
        text="Solution: The architecture uses retrieval memory in the agent pipeline.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(source_url=source.url, quote="retrieval memory in the agent pipeline")
        ],
    )

    def fake_which(name: str) -> str | None:
        return "/usr/bin/rsvg-convert" if name == "rsvg-convert" else None

    def fake_run(args: list[str], **kwargs: object) -> object:
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_bytes(b"fake-png")
        return object()

    monkeypatch.setattr(figures_module.shutil, "which", fake_which)
    monkeypatch.setattr(figures_module.subprocess, "run", fake_run)

    selected = extract_latex_figures(source_dir, image_dir, source, [claim])

    assert len(selected) == 1
    assert selected[0].renderable is True
    assert selected[0].asset_path.endswith(".png")


def test_extract_latex_figures_marks_unconverted_svg_non_renderable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    image_dir = tmp_path / "figures" / "images"
    (source_dir / "figures").mkdir(parents=True)
    (source_dir / "figures" / "architecture.svg").write_text("<svg></svg>", encoding="utf-8")
    (source_dir / "main.tex").write_text(
        r"""
        \begin{figure}
        \includegraphics{figures/architecture}
        \caption{Architecture overview for retrieval memory in the agent pipeline.}
        \label{fig:architecture}
        \end{figure}
        """,
        encoding="utf-8",
    )
    source = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )
    claim = Claim(
        text="Solution: The architecture uses retrieval memory in the agent pipeline.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(source_url=source.url, quote="retrieval memory in the agent pipeline")
        ],
    )

    monkeypatch.setattr(figures_module.shutil, "which", lambda name: None)

    selected = extract_latex_figures(source_dir, image_dir, source, [claim])

    assert len(selected) == 1
    assert selected[0].renderable is False
    assert selected[0].asset_path.endswith(".svg")


def test_extract_latex_figures_cleans_latex_caption_noise(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    image_dir = tmp_path / "figures" / "images"
    (source_dir / "figures").mkdir(parents=True)
    (source_dir / "figures" / "architecture.png").write_bytes(b"fake-png")
    (source_dir / "main.tex").write_text(
        r"""
        \begin{figure}
        \includegraphics{figures/architecture}
        \caption{SLM~V3.3 architecture with 32$$ cold-start speedup,
        100\% local storage, $R 0.35$ retention, and 2 \times faster lookup. % comment
        }
        \label{fig:architecture}
        \end{figure}
        """,
        encoding="utf-8",
    )
    source = SourceCandidate(
        title="Memory Paper",
        url="https://arxiv.org/abs/2605.00001",
        source_type=SourceType.PAPER,
        source_name="arxiv",
    )
    claim = Claim(
        text="Solution: SLM V3.3 uses a local storage architecture with faster lookup.",
        status=ClaimStatus.SUPPORTED,
        evidence=[
            EvidenceAnchor(
                source_url=source.url,
                quote="local storage architecture with faster lookup",
            )
        ],
    )

    selected = extract_latex_figures(source_dir, image_dir, source, [claim])

    assert len(selected) == 1
    caption = selected[0].caption
    assert "SLM V3.3 architecture" in caption
    assert "32 cold-start speedup" in caption
    assert "100% local storage" in caption
    assert "R 0.35 retention" in caption
    assert "2 × faster lookup" in caption
    assert "$" not in caption
    assert "comment" not in caption


def _pdf_bbox_xml(
    *,
    words: list[tuple[str, int, int, int, int]],
    width: int = 1000,
    height: int = 1200,
) -> str:
    word_xml = "\n".join(
        (
            f'<word xMin="{x_min}" yMin="{y_min}" xMax="{x_max}" yMax="{y_max}">'
            f"{text}</word>"
        )
        for text, x_min, y_min, x_max, y_max in words
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <doc>
      <page width="{width}" height="{height}">
        {word_xml}
      </page>
    </doc>
  </body>
</html>
"""
