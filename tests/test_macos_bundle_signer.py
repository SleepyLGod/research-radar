import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "sign_macos_bundle", Path("script/sign_macos_bundle.py")
)
assert _SPEC is not None and _SPEC.loader is not None
_SIGNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SIGNER)
nested_macho_files = _SIGNER.nested_macho_files
nested_app_bundles = _SIGNER.nested_app_bundles


def test_nested_macho_files_excludes_outer_app_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = tmp_path / "ResearchRadar.app"
    main = app / "Contents/MacOS/ResearchRadar"
    helper_app = app / "Contents/Helpers/ResearchRadarEngine.app"
    helper = helper_app / "Contents/MacOS/engine"
    library = helper_app / "Contents/Resources/libpython.dylib"
    for path in (main, helper, library):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"binary")
    monkeypatch.setattr(_SIGNER, "_is_macho", lambda path: True)

    assert nested_macho_files(app) == [library]
    assert nested_app_bundles(app) == [helper_app]
