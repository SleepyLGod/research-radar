import runpy
import sys
from pathlib import Path

import pytest


def test_frozen_metadata_relocates_only_python_prefix_without_mutating_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = runpy.run_path("packaging/macos/frozen_sysconfig.py")["render_sysconfig"]
    original = {
        "prefix": "/build/python",
        "BINDIR": "/build/python/bin",
        "FLAGS": "-I/build/python/include -L/build/python/lib -framework CoreFoundation",
        "VERSION": "3.13",
        "SIZEOF_VOID_P": 8,
    }
    source = render(original, "/build/python")
    assert "/build/python" not in source
    monkeypatch.setattr(
        sys, "_MEIPASS", "/Applications/Radar.app/Contents/Frameworks", raising=False
    )
    namespace: dict[str, object] = {}
    exec(compile(source, "_sysconfigdata_fixture.py", "exec"), namespace)
    assert namespace["build_time_vars"] == {
        "prefix": "/Applications/Radar.app/Contents/Frameworks",
        "BINDIR": "/Applications/Radar.app/Contents/Frameworks/bin",
        "FLAGS": "-I/Applications/Radar.app/Contents/Frameworks/include "
                 "-L/Applications/Radar.app/Contents/Frameworks/lib -framework CoreFoundation",
        "VERSION": "3.13",
        "SIZEOF_VOID_P": 8,
    }
    assert original["prefix"] == "/build/python"
    assert original["FLAGS"] == (
        "-I/build/python/include -L/build/python/lib -framework CoreFoundation"
    )


def test_generated_metadata_keeps_host_sysconfig_untouched(tmp_path: Path) -> None:
    import importlib
    import sysconfig

    prepare = runpy.run_path("packaging/macos/frozen_sysconfig.py")["prepare_sysconfig"]
    name = sysconfig._get_sysconfigdata_name()
    module = importlib.import_module(name)
    before = dict(module.build_time_vars)
    original_file = Path(module.__file__).read_bytes()
    generated = prepare(tmp_path)
    assert generated == tmp_path / "frozen-stdlib"
    source = (generated / f"{name}.py").read_text()
    assert sys.base_prefix not in source
    namespace: dict[str, object] = {}
    exec(compile(source, name, "exec"), namespace)
    assert namespace["build_time_vars"] == before
    assert module.build_time_vars == before
    assert Path(module.__file__).read_bytes() == original_file


def test_metadata_rejects_empty_prefix() -> None:
    render = runpy.run_path("packaging/macos/frozen_sysconfig.py")["render_sysconfig"]
    with pytest.raises(ValueError, match="prefix"):
        render({"VERSION": "3.13"}, "")
