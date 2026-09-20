"""Bounded diagnostics without query text, URLs, response bodies, or credentials."""

from urllib.error import HTTPError, URLError


class QueryDiagnostics:
    """Track all query counts while retaining at most twenty failure records."""

    def __init__(self, provider: str, query_count: int) -> None:
        self.succeeded = 0
        self.failed = 0
        self._failures: list[dict[str, object]] = []
        self._provider = provider
        self._query_count = query_count

    def failure(self, error: OSError) -> None:
        """Record only allowlisted exception categories and valid HTTP status codes."""
        self.failed += 1
        if len(self._failures) >= 20:
            return
        error_type = "OSError"
        for kind in (HTTPError, URLError, TimeoutError, ConnectionError):
            if isinstance(error, kind):
                error_type = kind.__name__
                break
        status = error.code if isinstance(error, HTTPError) else None
        self._failures.append({
            "status": "failed",
            "error_type": error_type,
            "http_status": status if type(status) is int and 100 <= status <= 599 else None,
        })

    def snapshot(
        self, candidate_count: int, warnings: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        """Return the existing orchestrator diagnostics contract plus explicit counts."""
        return {
            "provider": self._provider,
            "query_count": self._query_count,
            "successful_query_count": self.succeeded,
            "failed_query_count": self.failed,
            "candidate_count": candidate_count,
            "queries": list(self._failures),
            "warnings": warnings or [],
        }
