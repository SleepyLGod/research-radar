"""Weekly deep-dive pipeline."""

from __future__ import annotations

from pathlib import Path

from research_radar.compose.draft import build_weekly_draft
from research_radar.compose.markdown import render_markdown
from research_radar.compose.wechat import render_wechat_html
from research_radar.evidence.ledger import load_claims
from research_radar.models import dataclass_to_dict
from research_radar.storage.files import write_json, write_text


def compose_weekly_from_run(run_dir: Path, topic_id: str) -> None:
    """Compose weekly artifacts from a run's verified claims."""

    claims = load_claims(run_dir / "claims.jsonl")
    draft = build_weekly_draft(topic_id, claims)
    write_json(run_dir / "article_draft.json", dataclass_to_dict(draft))
    write_text(run_dir / "weekly_draft.md", render_markdown(draft))
    write_text(run_dir / "wechat.html", render_wechat_html(draft))
