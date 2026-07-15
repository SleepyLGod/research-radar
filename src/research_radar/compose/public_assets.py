"""Shared safety checks for public channel assets."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


def safe_run_asset_path(run_dir: Path, raw_src: str) -> Path | None:
    """Resolve a figure path only when it remains inside the run directory."""

    source = Path(raw_src)
    if source.is_absolute():
        candidate = source
    else:
        normalized = PurePosixPath(raw_src.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            return None
        candidate = run_dir / Path(*normalized.parts)
    try:
        run_root = run_dir.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(run_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def is_public_image(path: Path) -> bool:
    """Return whether a file has a public static image format."""

    return path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
