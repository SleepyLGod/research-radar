#!/usr/bin/env python3
"""Ad-hoc sign nested Mach-O files and then the outer App bundle."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _is_macho(path: Path) -> bool:
    result = subprocess.run(
        ["/usr/bin/file", "-b", str(path)], capture_output=True, text=True, check=False
    )
    return result.returncode == 0 and "Mach-O" in result.stdout


def nested_macho_files(app: Path) -> list[Path]:
    """Return nested code that must be signed before the outer App bundle."""

    binaries = [
        path
        for path in app.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not _is_app_main_executable(path)
        and _is_macho(path)
    ]
    return sorted(binaries, key=lambda path: (-len(path.parts), path.as_posix()))


def nested_app_bundles(app: Path) -> list[Path]:
    """Return nested App bundles from deepest to shallowest."""

    bundles = [path for path in app.rglob("*.app") if path.is_dir() and path != app]
    return sorted(bundles, key=lambda path: (-len(path.parts), path.as_posix()))


def _is_app_main_executable(path: Path) -> bool:
    return path.parent.name == "MacOS" and path.parent.parent.name == "Contents"


def main() -> int:
    """Sign one staged local-beta App."""

    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    for binary in nested_macho_files(app):
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(binary)],
            check=True,
        )
    for nested_app in nested_app_bundles(app):
        subprocess.run(
            [
                "/usr/bin/codesign",
                "--force",
                "--sign",
                "-",
                "--timestamp=none",
                str(nested_app),
            ],
            check=True,
        )
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(app)],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
