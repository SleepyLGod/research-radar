"""Generate relocatable CPython build metadata for the frozen engine only."""

from __future__ import annotations

import importlib
import sys
import sysconfig
from collections.abc import Mapping
from pathlib import Path


def render_sysconfig(variables: Mapping[str, str | int], prefix: str) -> str:
    """Preserve build variables while resolving the builder prefix inside the bundle."""
    if not prefix:
        raise ValueError("The build Python prefix must not be empty.")
    lines = [
        '"""Relocatable build metadata generated during freezing."""',
        "import sys as _sys",
        "_prefix = getattr(_sys, '_MEIPASS', _sys.base_prefix)",
        "build_time_vars = {",
    ]
    for key, value in sorted(variables.items()):
        expression = repr(value)
        if isinstance(value, str) and prefix in value:
            expression = " + _prefix + ".join(repr(part) for part in value.split(prefix))
        lines.append(f"    {key!r}: {expression},")
    lines.extend(["}", "del _prefix, _sys", ""])
    return "\n".join(lines)


def prepare_sysconfig(work_directory: Path) -> Path:
    """Write a build-local replacement module, never modify the installed Python."""
    name = sysconfig._get_sysconfigdata_name()
    variables = importlib.import_module(name).build_time_vars
    directory = work_directory / "frozen-stdlib"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.py").write_text(
        render_sysconfig(variables, sys.base_prefix), encoding="utf-8"
    )
    return directory
