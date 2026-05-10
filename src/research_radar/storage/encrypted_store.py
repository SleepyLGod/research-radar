"""Encrypted JSON state storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_radar.security.crypto import EnvelopeEncryptor
from research_radar.storage.files import read_json, write_json


@dataclass(frozen=True)
class EncryptedJsonStore:
    """A small encrypted JSON document store."""

    path: Path
    encryptor: EnvelopeEncryptor

    def save(self, value: dict[str, Any]) -> None:
        """Encrypt and save a JSON object."""

        payload = self.encryptor.encrypt_json(value, aad=self._aad())
        write_json(self.path, payload)

    def load(self) -> dict[str, Any]:
        """Load and decrypt a JSON object."""

        payload = read_json(self.path)
        if not isinstance(payload, dict):
            raise ValueError("Encrypted store file must contain a JSON object.")
        return self.encryptor.decrypt_json(payload, aad=self._aad())

    def _aad(self) -> bytes:
        return f"research-radar:{self.path.name}".encode()
