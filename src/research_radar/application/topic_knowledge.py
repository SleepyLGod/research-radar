"""Explicit knowledge organization using existing providers and private atomic snapshots."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from research_radar.analysis.knowledge_inputs import (
    KnowledgeError,
    KnowledgeInput,
    build_knowledge_input,
    fingerprint,
)
from research_radar.analysis.providers import LLMProvider, ModelResponse
from research_radar.analysis.topic_knowledge import (
    PROMPT_VERSION,
    organization_messages,
    validate_organization,
    validate_organization_value,
)
from research_radar.exceptions import OperationCancelled
from research_radar.storage.files import write_json
from research_radar.storage.paper_ledger import LedgerReport


@dataclass(frozen=True)
class KnowledgeOrganizationResult:
    """A committed organization snapshot and its private local artifact path."""

    snapshot: dict[str, Any]
    path: Path


def organize_topic(
    workspace: Path,
    topic_id: str,
    reports: list[LedgerReport],
    *,
    research_question: str,
    provider: LLMProvider,
    model: str,
    language: str = "zh",
    cancelled: Callable[[], bool] = lambda: False,
) -> KnowledgeOrganizationResult:
    """Organize the supplied full scope once; no discovery, secrets, delivery or fallback."""
    _check_cancelled(cancelled)
    if not isinstance(model, str) or not model.strip():
        raise KnowledgeError("Knowledge model must be explicitly selected.")
    root = _topic_root(workspace, topic_id, create=True)
    with _topic_lock(root):
        # Existing corruption is not permission to reset the user's current knowledge.
        load_current_knowledge(workspace, topic_id)
        materials = build_knowledge_input(workspace, topic_id, reports, cancelled=cancelled)
        if not materials.papers:
            raise KnowledgeError("No usable public deep reads are available for organization.")
        messages = organization_messages(
            materials, research_question=research_question, language=language
        )
        _check_cancelled(cancelled)
        response = provider.complete(messages, model=model)
        _check_cancelled(cancelled)
        organization = validate_organization(response.content, materials)
        snapshot_id = uuid4().hex
        snapshot = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(UTC).isoformat(),
            "topic_id": topic_id,
            "research_question": research_question,
            "language": language,
            "prompt_version": PROMPT_VERSION,
            "provider": provider.name,
            "requested_model": model,
            "model": response.model,
            "inference_settings": _inference_settings(response),
            "input_fingerprint": materials.fingerprint,
            "facet_fingerprint": fingerprint(organization["facets"]),
            "inputs": materials.to_payload(),
            "organization": organization,
        }
        path = root / "snapshots" / f"{snapshot_id}.json"
        _validate_snapshot(snapshot, topic_id, snapshot_id)
        # A changed report is never silently combined with an earlier model response.
        _check_fresh(workspace, topic_id, reports, materials, cancelled)
        _write_private(path, snapshot)
        _write_private(
            root / "current.json",
            {
                "schema_version": 1,
                "snapshot_id": snapshot_id,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
            before_replace=lambda: _check_fresh(workspace, topic_id, reports, materials, cancelled),
        )
        return KnowledgeOrganizationResult(snapshot, path)


def load_current_knowledge(workspace: Path, topic_id: str) -> dict[str, Any] | None:
    """Load a committed snapshot; preserve and reject corrupt files, never reset them."""
    root = _topic_root(workspace, topic_id, create=False)
    pointer = root / "current.json"
    if not pointer.exists() and not pointer.is_symlink():
        return None
    try:
        value = _read_private_json(pointer)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "snapshot_id", "sha256"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or not isinstance(value["snapshot_id"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", value["snapshot_id"])
        ):
            raise KnowledgeError("Invalid current knowledge pointer.")
        path = root / "snapshots" / f"{value['snapshot_id']}.json"
        content = _read_private_bytes(path)
        if hashlib.sha256(content).hexdigest() != value["sha256"]:
            raise KnowledgeError("Current knowledge snapshot checksum does not match.")
        snapshot = json.loads(content)
        _validate_snapshot(snapshot, topic_id, value["snapshot_id"])
        return snapshot
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        raise KnowledgeError("Could not read the current knowledge snapshot.") from exc


def _validate_snapshot(value: object, topic_id: str, snapshot_id: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "snapshot_id",
        "created_at",
        "topic_id",
        "research_question",
        "language",
        "prompt_version",
        "provider",
        "requested_model",
        "model",
        "inference_settings",
        "input_fingerprint",
        "facet_fingerprint",
        "inputs",
        "organization",
    }:
        raise KnowledgeError("Invalid knowledge snapshot fields.")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["topic_id"] != topic_id
        or value["snapshot_id"] != snapshot_id
    ):
        raise KnowledgeError("Knowledge snapshot identity does not match.")
    for key in (
        "created_at",
        "research_question",
        "prompt_version",
        "provider",
        "requested_model",
        "model",
    ):
        if not isinstance(value[key], str) or not value[key].strip():
            raise KnowledgeError("Invalid knowledge snapshot metadata.")
    if value["language"] not in ("en", "zh") or not isinstance(value["inference_settings"], dict):
        raise KnowledgeError("Invalid knowledge snapshot settings.")
    inputs = value["inputs"]
    if (
        not isinstance(inputs, dict)
        or set(inputs) != {"topic_id", "papers", "references", "reports", "coverage"}
        or inputs["topic_id"] != topic_id
        or fingerprint(inputs) != value["input_fingerprint"]
    ):
        raise KnowledgeError("Knowledge input manifest does not match its fingerprint.")
    materials = KnowledgeInput(**inputs)
    validate_organization_value(value["organization"], materials)
    if fingerprint(value["organization"]["facets"]) != value["facet_fingerprint"]:
        raise KnowledgeError("Knowledge facets do not match their fingerprint.")


def _inference_settings(response: ModelResponse) -> dict[str, str]:
    # Never persist arbitrary provider diagnostics, process output or transport metadata.
    allowed = {
        "thinking": {"enabled", "disabled", "inherited"},
        "reasoning_effort": {
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
            "inherited",
        },
    }
    return {
        key: response.metadata[key]
        for key, choices in allowed.items()
        if isinstance(response.metadata.get(key), str) and response.metadata[key] in choices
    }


def _topic_root(workspace: Path, topic_id: str, *, create: bool) -> Path:
    if not isinstance(topic_id, str) or not topic_id.strip():
        raise KnowledgeError("Knowledge topic must be non-empty.")
    try:
        root = workspace.resolve(strict=True)
        digest = hashlib.sha256(topic_id.encode()).hexdigest()
        for relative in (
            Path("knowledge"),
            Path("knowledge") / digest,
            Path("knowledge") / digest / "snapshots",
        ):
            path = root / relative
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise KnowledgeError("Knowledge storage must not traverse a symlink or file.")
            if create:
                path.mkdir(mode=0o700, exist_ok=True)
                path.chmod(0o700)
        return root / "knowledge" / digest
    except (OSError, ValueError) as exc:
        raise KnowledgeError("Could not open private knowledge storage.") from exc


@contextmanager
def _topic_lock(root: Path) -> Iterator[None]:
    fd = os.open(root / "organize.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise KnowledgeError("Knowledge lock must be a regular file.")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise KnowledgeError(
                "Knowledge organization is already running for this topic."
            ) from exc
        yield


def _read_private_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise KnowledgeError("Knowledge artifact must be a regular file.")
    return path.read_bytes()


def _read_private_json(path: Path) -> Any:
    return json.loads(_read_private_bytes(path))


def _write_private(
    path: Path,
    value: dict[str, Any],
    *,
    before_replace: Callable[[], None] | None = None,
) -> None:
    for candidate in (path, path.with_suffix(path.suffix + ".tmp")):
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
            raise KnowledgeError("Knowledge output must not replace an unsafe file.")
    # Set permissions before promotion: a post-replace chmod failure must not make
    # a successfully replaced pointer look like a failed, safely retryable write.
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise KnowledgeError("Knowledge temporary output must be a private regular file.")
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    write_json(path, value, before_replace=before_replace)


def _check_cancelled(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise OperationCancelled("Knowledge organization cancelled.")


def _check_fresh(
    workspace: Path,
    topic_id: str,
    reports: list[LedgerReport],
    original: KnowledgeInput,
    cancelled: Callable[[], bool],
) -> None:
    _check_cancelled(cancelled)
    current = build_knowledge_input(workspace, topic_id, reports, cancelled=cancelled)
    if current.fingerprint != original.fingerprint:
        raise KnowledgeError("Knowledge inputs changed during organization; current not updated.")
    _check_cancelled(cancelled)
