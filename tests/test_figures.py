from pathlib import Path

from research_radar.analysis import figures as figures_module
from research_radar.analysis.figures import extract_latex_figures
from research_radar.models import Claim, ClaimStatus, EvidenceAnchor, SourceCandidate, SourceType


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
