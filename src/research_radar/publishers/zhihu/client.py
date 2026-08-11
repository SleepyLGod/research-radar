"""Zhihu publisher placeholder.

The integration is intentionally not implemented until the API/auth path is chosen.
"""

from __future__ import annotations

from research_radar.exceptions import PublishError
from research_radar.models import ArticleDraft


class ZhihuPublisher:
    """Placeholder for future Zhihu publishing."""

    def publish_draft(self, draft: ArticleDraft) -> None:
        """Reject publishing until the Zhihu integration is explicitly designed."""

        raise PublishError(
            "Automatic Zhihu publishing is not supported; use 'compose zhihu' for manual export."
        )
