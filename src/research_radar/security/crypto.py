"""Envelope encryption for sensitive runtime state."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Protocol

from research_radar.exceptions import CryptoError, SecretError
from research_radar.security.secrets import SecretBackend

MASTER_KEY_NAME = "storage.master_key"


class MasterKeyProvider(Protocol):
    """Provider for the local or cloud master key."""

    def get_or_create_master_key(self) -> bytes:
        """Return a 32-byte master key."""


@dataclass
class InMemoryMasterKeyProvider:
    """In-memory master key provider for tests."""

    master_key: bytes | None = None

    def get_or_create_master_key(self) -> bytes:
        """Return a stable in-memory master key."""

        if self.master_key is None:
            self.master_key = os.urandom(32)
        return self.master_key


@dataclass(frozen=True)
class SecretMasterKeyProvider:
    """Master key provider backed by a secret backend."""

    backend: SecretBackend

    def get_or_create_master_key(self) -> bytes:
        """Return the storage master key, creating it if absent."""

        try:
            encoded = self.backend.get_secret(MASTER_KEY_NAME)
        except SecretError:
            key = os.urandom(32)
            self.backend.set_secret(MASTER_KEY_NAME, _b64encode(key))
            return key
        key = _b64decode(encoded)
        if len(key) != 32:
            raise CryptoError("Stored master key must be 32 bytes.")
        return key


@dataclass(frozen=True)
class EnvelopeEncryptor:
    """Encrypt and decrypt payloads with envelope AES-GCM."""

    master_key_provider: MasterKeyProvider

    def encrypt_json(self, value: dict[str, object], *, aad: bytes = b"") -> dict[str, str]:
        """Encrypt a JSON-serializable mapping."""

        plaintext = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.encrypt_bytes(plaintext, aad=aad)

    def decrypt_json(self, payload: dict[str, str], *, aad: bytes = b"") -> dict[str, object]:
        """Decrypt a JSON mapping."""

        raw = self.decrypt_bytes(payload, aad=aad)
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise CryptoError("Encrypted JSON payload must contain an object.")
        return loaded

    def encrypt_bytes(self, value: bytes, *, aad: bytes = b"") -> dict[str, str]:
        """Encrypt bytes and return a JSON-friendly payload."""

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise CryptoError("Install cryptography to use encrypted storage.") from exc

        master_key = self.master_key_provider.get_or_create_master_key()
        data_key = os.urandom(32)
        wrap_nonce = os.urandom(12)
        data_nonce = os.urandom(12)
        wrapped_data_key = AESGCM(master_key).encrypt(
            wrap_nonce,
            data_key,
            b"research-radar:data-key",
        )
        ciphertext = AESGCM(data_key).encrypt(data_nonce, value, aad)
        return {
            "version": "1",
            "algorithm": "AES-256-GCM",
            "wrap_nonce": _b64encode(wrap_nonce),
            "data_nonce": _b64encode(data_nonce),
            "wrapped_data_key": _b64encode(wrapped_data_key),
            "ciphertext": _b64encode(ciphertext),
        }

    def decrypt_bytes(self, payload: dict[str, str], *, aad: bytes = b"") -> bytes:
        """Decrypt bytes from an envelope payload."""

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise CryptoError("Install cryptography to use encrypted storage.") from exc

        if payload.get("version") != "1" or payload.get("algorithm") != "AES-256-GCM":
            raise CryptoError("Unsupported encrypted payload format.")
        master_key = self.master_key_provider.get_or_create_master_key()
        data_key = AESGCM(master_key).decrypt(
            _b64decode(payload["wrap_nonce"]),
            _b64decode(payload["wrapped_data_key"]),
            b"research-radar:data-key",
        )
        return AESGCM(data_key).decrypt(
            _b64decode(payload["data_nonce"]),
            _b64decode(payload["ciphertext"]),
            aad,
        )


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
