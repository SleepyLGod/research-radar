"""Zhihu renderer stub.

Zhihu support will need platform-specific API and formatting validation. In the v0.0.0 foundation,
the renderer intentionally returns Markdown-compatible content that can be adapted
once a publisher integration is selected.
"""

from __future__ import annotations

from research_radar.compose.markdown import render_markdown
from research_radar.models import ArticleDraft


def render_zhihu_markdown(draft: ArticleDraft) -> str:
    """Render a draft in a conservative Zhihu-ready Markdown shape."""

    return render_markdown(draft)
