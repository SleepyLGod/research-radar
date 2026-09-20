#!/usr/bin/env python3
"""Sign nested code inside-out with an explicit identity or local ad-hoc signing."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LOCAL_SETTINGS = Path(__file__).resolve().parents[1] / "packaging/macos/signing.local.json"


def select_identity(explicit: str | None, settings_path: Path = LOCAL_SETTINGS) -> str:
    """Read the opted-in local fingerprint, with explicit overrides taking precedence."""
    if explicit is not None:
        return explicit
    environment = os.environ.get("RESEARCH_RADAR_SIGNING_IDENTITY")
    if environment is not None:
        return environment
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "-"
    except (OSError, ValueError):
        raise ValueError("Local signing configuration is unreadable or invalid.") from None
    if not isinstance(settings, dict) or set(settings) != {"identity"}:
        raise ValueError("Local signing configuration must contain only 'identity'.")
    if not isinstance(settings["identity"], str):
        raise ValueError("Local signing configuration requires a certificate fingerprint string.")
    return settings["identity"]


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


def validate_identity(identity: str) -> str:
    """Require an exact usable certificate fingerprint; never downgrade to ad-hoc."""
    if identity == "-":
        return identity
    if re.fullmatch(r"[0-9a-fA-F]{40}", identity) is None:
        raise ValueError("Signing identity must be '-' or an exact 40-digit certificate SHA-1.")
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
            check=True, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Could not list usable signing identities; no code was signed.") from None
    fingerprints = {
        match.upper()
        for match in re.findall(r"^\s*\d+\)\s+([0-9a-fA-F]{40})\s", result.stdout, re.MULTILINE)
    }
    if identity.upper() not in fingerprints:
        raise ValueError(
            "Requested signing certificate/private key is unavailable. "
            "No code was signed; ad-hoc fallback is disabled."
        )
    return identity.upper()


def main() -> int:
    """Sign one staged local-beta App."""

    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument(
        "--identity",
        help="Certificate SHA-1 or '-'; defaults to environment, local settings, then '-'.",
    )
    parser.add_argument(
        "--check-identity", action="store_true",
        help="Validate the identity without reading or changing the app.",
    )
    args = parser.parse_args()
    try:
        identity = validate_identity(select_identity(args.identity))
    except ValueError as exc:
        parser.error(str(exc))
    if args.check_identity:
        return 0
    app = args.app.resolve(strict=True)
    if identity == "-":
        print(
            "Ad-hoc build: Keychain authorization may need renewal after updates.", file=sys.stderr,
        )
    for target in [*nested_macho_files(app), *nested_app_bundles(app), app]:
        subprocess.run(
            [
                "/usr/bin/codesign", "--force", "--sign", identity,
                "--timestamp=none", str(target),
            ],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
