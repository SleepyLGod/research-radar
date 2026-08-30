#!/usr/bin/env python3
"""Verify that the staged macOS bundle is self-contained and private-path free."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]


class BundleVerificationError(RuntimeError):
    """Raised when a staged bundle violates the foundation packaging contract."""


def symlink_manifest(root: Path) -> dict[str, dict[str, str]]:
    """Return a stable symlink manifest and reject links escaping root."""

    resolved_root = root.resolve(strict=True)
    manifest: dict[str, dict[str, str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_symlink():
            continue
        target = os.readlink(path)
        try:
            resolved = path.resolve(strict=True)
            relative_resolved = resolved.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            relative = path.relative_to(root).as_posix()
            raise BundleVerificationError(
                f"Symlink {relative} escapes the engine root or is broken."
            ) from exc
        manifest[path.relative_to(root).as_posix()] = {
            "target": target,
            "resolved": relative_resolved.as_posix(),
        }
    return manifest


def verify_engine_copy(source: Path, staged: Path) -> None:
    """Verify that an engine copy preserved links and contains no private build paths."""

    source_manifest = symlink_manifest(source)
    staged_manifest = symlink_manifest(staged)
    if source_manifest != staged_manifest:
        raise BundleVerificationError("The staged engine symlink manifest differs from source.")
    _reject_private_build_paths(staged)


def verify_bundle(source_engine: Path, app: Path) -> None:
    """Run all static foundation bundle checks."""

    app = app.resolve(strict=True)
    if app.suffix != ".app" or not app.is_dir():
        raise BundleVerificationError("The staged application is not an App bundle.")
    symlink_manifest(app)
    staged_engine = app / "Contents/Helpers/ResearchRadarEngine.app"
    verify_engine_copy(source_engine, staged_engine)
    _verify_info_plist(app)
    _verify_macho_dependencies(app)
    _reject_private_build_paths(app)
    if any(path.name == "process_fixture.py" for path in app.rglob("*")):
        raise BundleVerificationError("Test fixture executable must not enter the App bundle.")


def _verify_info_plist(app: Path) -> None:
    path = app / "Contents/Info.plist"
    try:
        value = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise BundleVerificationError("Info.plist is missing or invalid.") from exc
    required: dict[str, Any] = {
        "CFBundleExecutable": "ResearchRadar",
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "26.0",
        "LSUIElement": True,
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise BundleVerificationError(f"Info.plist has an invalid {key} value.")


def _reject_private_build_paths(root: Path) -> None:
    forbidden = [
        str(SOURCE_ROOT).encode(),
        b"/private/tmp",
        b"/.venv/",
    ]
    executable_forbidden = [b"/opt/homebrew", b"/usr/local/"]
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise BundleVerificationError(f"Could not inspect bundled file {path.name}.") from exc
        is_binary = b"\x00" in data[:4096]
        values = forbidden
        if not is_binary and (os.access(path, os.X_OK) or path.suffix in {".py", ".sh"}):
            values = [*values, *executable_forbidden]
        if any(value in data for value in values):
            raise BundleVerificationError(
                f"Bundled file {path.name} contains a private build path."
            )


def _verify_macho_dependencies(app: Path) -> None:
    executable_dir = app / "Contents/MacOS"
    for binary in _macho_files(app):
        architectures = _run(["/usr/bin/lipo", "-archs", str(binary)]).split()
        if architectures != ["arm64"]:
            raise BundleVerificationError(
                f"{binary.name} must contain only arm64, found: {' '.join(architectures)}"
            )
        dependencies = _otool_dependencies(binary)
        install_name = _otool_install_name(binary)
        rpaths = _otool_rpaths(binary)
        for dependency in dependencies:
            if dependency == install_name:
                continue
            if dependency.startswith(("/System/Library/", "/usr/lib/")):
                continue
            if not _dependency_resolves_inside(
                dependency,
                binary=binary,
                executable_dir=executable_dir,
                rpaths=rpaths,
                app=app,
            ):
                raise BundleVerificationError(
                    f"Dependency {dependency} from {binary.name} does not resolve inside the App."
                )


def _macho_files(app: Path) -> list[Path]:
    found: list[Path] = []
    for path in app.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        description = _run(["/usr/bin/file", "-b", str(path)], check=False)
        if "Mach-O" in description:
            found.append(path)
    return found


def _otool_dependencies(binary: Path) -> list[str]:
    lines = _run(["/usr/bin/otool", "-L", str(binary)]).splitlines()[1:]
    return [line.strip().split(" (", 1)[0] for line in lines if line.strip()]


def _otool_install_name(binary: Path) -> str | None:
    lines = _run(["/usr/bin/otool", "-D", str(binary)], check=False).splitlines()[1:]
    return lines[0].strip() if lines else None


def _otool_rpaths(binary: Path) -> list[str]:
    lines = _run(["/usr/bin/otool", "-l", str(binary)]).splitlines()
    rpaths: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() == "cmd LC_RPATH" and index + 2 < len(lines):
            path_line = lines[index + 2].strip()
            if path_line.startswith("path "):
                rpaths.append(path_line[5:].split(" (offset", 1)[0])
    return rpaths


def _dependency_resolves_inside(
    dependency: str,
    *,
    binary: Path,
    executable_dir: Path,
    rpaths: list[str],
    app: Path,
) -> bool:
    candidates: list[Path] = []
    if dependency.startswith("@loader_path/"):
        candidates.append(binary.parent / dependency.removeprefix("@loader_path/"))
    elif dependency.startswith("@executable_path/"):
        candidates.append(executable_dir / dependency.removeprefix("@executable_path/"))
    elif dependency.startswith("@rpath/"):
        suffix = dependency.removeprefix("@rpath/")
        for rpath in rpaths:
            expanded = _expand_token_path(rpath, binary=binary, executable_dir=executable_dir)
            if expanded is not None:
                candidates.append(expanded / suffix)
    elif dependency.startswith("/"):
        return False
    for candidate in candidates:
        try:
            candidate.resolve(strict=True).relative_to(app)
        except (OSError, ValueError):
            continue
        return True
    return False


def _expand_token_path(value: str, *, binary: Path, executable_dir: Path) -> Path | None:
    if value == "@loader_path":
        return binary.parent
    if value.startswith("@loader_path/"):
        return binary.parent / value.removeprefix("@loader_path/")
    if value == "@executable_path":
        return executable_dir
    if value.startswith("@executable_path/"):
        return executable_dir / value.removeprefix("@executable_path/")
    if value.startswith("/"):
        return Path(value)
    return None


def _run(command: list[str], *, check: bool = True) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise BundleVerificationError(detail or f"Command failed: {command[0]}")
    return result.stdout.strip()


def main() -> int:
    """Verify a staged App from the command line."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--source-engine", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    verify_bundle(args.source_engine, args.app)
    print("macOS bundle verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
