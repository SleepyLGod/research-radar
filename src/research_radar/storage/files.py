"""Filesystem helpers for run artifacts."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any

from research_radar.models import dataclass_to_dict


def ensure_dir(path: Path) -> Path:
    """Create a directory if needed and return it."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, value: Any) -> None:
    """Atomically write JSON to a file."""

    serializable = dataclass_to_dict(value) if is_dataclass(value) else value
    _atomic_write(path, json.dumps(serializable, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    """Read JSON from a file."""

    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, values: Iterable[Any]) -> None:
    """Atomically write JSON Lines to a file."""

    lines = []
    for value in values:
        serializable = dataclass_to_dict(value) if is_dataclass(value) else value
        lines.append(json.dumps(serializable, ensure_ascii=False))
    _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON Lines from a file."""

    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_text(path: Path, value: str) -> None:
    """Atomically write UTF-8 text."""

    _atomic_write(path, value if value.endswith("\n") else value + "\n")


def _atomic_write(path: Path, value: str) -> None:
    ensure_dir(path.parent)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(value, encoding="utf-8")
    os.replace(tmp_path, path)
