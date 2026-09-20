import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

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


FINGERPRINT = "A1" * 20


def test_local_identity_persists_without_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RESEARCH_RADAR_SIGNING_IDENTITY", raising=False)
    settings = tmp_path / "signing.local.json"
    settings.write_text('{"identity": "' + FINGERPRINT + '"}', encoding="utf-8")
    assert _SIGNER.select_identity(None, settings) == FINGERPRINT


def test_unconfigured_checkout_keeps_adhoc_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RESEARCH_RADAR_SIGNING_IDENTITY", raising=False)
    assert _SIGNER.select_identity(None, tmp_path / "absent.json") == "-"


@pytest.mark.parametrize("contents", ["{", "[]", '{"identity": 123}', '{"other": "-"}'])
def test_invalid_local_identity_config_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str,
) -> None:
    monkeypatch.delenv("RESEARCH_RADAR_SIGNING_IDENTITY", raising=False)
    settings = tmp_path / "signing.local.json"
    settings.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="Local signing configuration"):
        _SIGNER.select_identity(None, settings)


def test_explicit_identity_and_environment_override_local_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "signing.local.json"
    settings.write_text("invalid", encoding="utf-8")
    monkeypatch.setenv("RESEARCH_RADAR_SIGNING_IDENTITY", FINGERPRINT)
    assert _SIGNER.select_identity("-", settings) == "-"
    assert _SIGNER.select_identity(None, settings) == FINGERPRINT


@pytest.mark.parametrize("identity", ["-", FINGERPRINT])
def test_signs_nested_code_with_one_explicit_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: str,
) -> None:
    app = tmp_path / "ResearchRadar.app"
    app.mkdir()
    library = app / "library.dylib"
    helper = app / "Engine.app"
    monkeypatch.setattr(_SIGNER, "nested_macho_files", lambda _: [library])
    monkeypatch.setattr(_SIGNER, "nested_app_bundles", lambda _: [helper])
    monkeypatch.setenv("RESEARCH_RADAR_SIGNING_IDENTITY", identity)
    monkeypatch.setattr(sys, "argv", ["sign_macos_bundle.py", str(app)])
    calls = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, f'1) {FINGERPRINT} "Fixture identity"\n', "")

    monkeypatch.setattr(_SIGNER.subprocess, "run", run)
    assert _SIGNER.main() == 0
    signing = [call for call in calls if call[0] == "/usr/bin/codesign"]
    assert [call[-1] for call in signing] == [str(library), str(helper), str(app)]
    assert all(call[call.index("--sign") + 1] == identity for call in signing)
    assert all("--requirements" not in call and "--deep" not in call for call in signing)


@pytest.mark.parametrize("identity", ["", "Fixture name", "A1" * 19])
def test_rejects_ambiguous_identity_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: str,
) -> None:
    monkeypatch.setattr(sys, "argv", [
        "sign_macos_bundle.py", str(tmp_path), "--identity", identity,
    ])
    calls = []
    monkeypatch.setattr(_SIGNER.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(SystemExit) as error:
        _SIGNER.main()
    assert error.value.code == 2
    assert calls == []


def test_missing_identity_fails_before_signing_or_replacing_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", [
        "sign_macos_bundle.py", str(tmp_path), "--identity", FINGERPRINT,
    ])
    calls = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "0 valid identities found\n", "")

    monkeypatch.setattr(_SIGNER.subprocess, "run", run)
    with pytest.raises(SystemExit) as error:
        _SIGNER.main()
    assert error.value.code == 2
    assert len(calls) == 1 and calls[0][0] == "/usr/bin/security"


def test_identity_precheck_does_not_require_or_touch_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_RADAR_SIGNING_IDENTITY", "invalid")
    monkeypatch.setattr(sys, "argv", [
        "sign_macos_bundle.py", str(tmp_path / "absent.app"), "--identity", "-", "--check-identity",
    ])
    assert _SIGNER.main() == 0
    assert not (tmp_path / "absent.app").exists()


def test_sign_failure_does_not_fall_back_to_adhoc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", [
        "sign_macos_bundle.py", str(tmp_path), "--identity", FINGERPRINT,
    ])
    monkeypatch.setattr(_SIGNER, "nested_macho_files", lambda _: [tmp_path / "library.dylib"])
    monkeypatch.setattr(_SIGNER, "nested_app_bundles", lambda _: [])
    calls = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[0] == "/usr/bin/codesign":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, f'1) {FINGERPRINT} "Fixture identity"\n', "")

    monkeypatch.setattr(_SIGNER.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        _SIGNER.main()
    assert len(calls) == 2
    assert "-" not in calls[-1]


@pytest.mark.parametrize("error", [
    OSError("fixture"), subprocess.TimeoutExpired("security", 15),
    subprocess.CalledProcessError(1, "security"),
])
def test_identity_lookup_failure_stops_before_signing(
    monkeypatch: pytest.MonkeyPatch, error: Exception,
) -> None:
    def run(command: list[str], **kwargs: Any) -> None:
        assert command[0] == "/usr/bin/security"
        raise error

    monkeypatch.setattr(_SIGNER.subprocess, "run", run)
    with pytest.raises(ValueError, match="Could not list usable signing identities"):
        _SIGNER.validate_identity(FINGERPRINT)
