"""Connector-local optional resolution; required backend reads remain retryable."""

from collections.abc import Callable
from threading import Lock

from research_radar.exceptions import SecretError, SecretNotFoundError


class OptionalCredential:
    """Resolve once for this connector, including absent or inaccessible values."""

    def __init__(self, getter: Callable[[], str] | None) -> None:
        self._getter = getter
        self._resolved = False
        self._value: str | None = None
        self._access_failed = False
        self._lock = Lock()

    def get(self) -> str | None:
        """Return the cached optional credential without repeating denied prompts."""
        with self._lock:
            if not self._resolved:
                try:
                    self._value = self._getter() if self._getter is not None else None
                except SecretNotFoundError:
                    pass
                except SecretError:
                    self._access_failed = True
                self._resolved = True
            return self._value

    def warnings(self) -> list[dict[str, str]]:
        """Return at most one fixed, redacted warning for this discovery call."""
        if not self._access_failed:
            return []
        return [{
            "kind": "optional_credential_access_failed",
            "error_type": "SecretAccessError",
            "message": "Optional credential unavailable; continuing anonymously.",
        }]
