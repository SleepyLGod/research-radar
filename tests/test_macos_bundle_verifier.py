import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "verify_macos_bundle", Path("script/verify_macos_bundle.py")
)
assert _SPEC is not None and _SPEC.loader is not None
_VERIFIER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VERIFIER)
BundleVerificationError = _VERIFIER.BundleVerificationError
symlink_manifest = _VERIFIER.symlink_manifest
verify_engine_copy = _VERIFIER.verify_engine_copy
_otool_install_name = _VERIFIER._otool_install_name


def test_symlink_manifest_records_internal_relative_target(tmp_path: Path) -> None:
    root = tmp_path / "engine"
    root.mkdir()
    library = root / "libpython.dylib"
    library.write_bytes(b"safe")
    (root / "python").symlink_to("libpython.dylib")

    assert symlink_manifest(root) == {
        "python": {
            "target": "libpython.dylib",
            "resolved": "libpython.dylib",
        }
    }


def test_symlink_manifest_rejects_link_that_escapes_engine(tmp_path: Path) -> None:
    root = tmp_path / "engine"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    (root / "escape").symlink_to(outside)

    with pytest.raises(BundleVerificationError, match="escapes the engine root"):
        symlink_manifest(root)


def test_verify_engine_copy_rejects_changed_symlink_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    staged = tmp_path / "staged"
    for root, target in [(source, "a"), (staged, "b")]:
        root.mkdir()
        (root / target).write_bytes(b"safe")
        (root / "python").symlink_to(target)

    with pytest.raises(BundleVerificationError, match="symlink manifest differs"):
        verify_engine_copy(source, staged)


@pytest.mark.parametrize("private_value", [b"/private/tmp/build", b"/.venv/bin/python"])
def test_verify_engine_copy_rejects_private_build_paths(
    tmp_path: Path, private_value: bytes
) -> None:
    source = tmp_path / "source"
    staged = tmp_path / "staged"
    source.mkdir()
    staged.mkdir()
    (source / "metadata.txt").write_bytes(b"safe")
    (staged / "metadata.txt").write_bytes(private_value)

    with pytest.raises(BundleVerificationError, match="private build path"):
        verify_engine_copy(source, staged)


def test_verify_engine_copy_accepts_matching_safe_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    staged = tmp_path / "staged"
    for root in (source, staged):
        root.mkdir()
        (root / "library.dylib").write_bytes(b"safe")
        (root / "python").symlink_to("library.dylib")

    verify_engine_copy(source, staged)


def test_verify_engine_copy_rejects_private_paths_embedded_in_binary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    staged = tmp_path / "staged"
    binary = (
        b"\xcf\xfa\xed\xfe\x00"
        + str(_VERIFIER.SOURCE_ROOT).encode()
        + b"/src/research_radar\x00"
    )
    for root in (source, staged):
        root.mkdir()
        (root / "library.dylib").write_bytes(binary)

    with pytest.raises(BundleVerificationError, match="private build path"):
        verify_engine_copy(source, staged)


def test_verify_engine_copy_allows_generic_install_path_in_binary_documentation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    staged = tmp_path / "staged"
    binary = b"\xcf\xfa\xed\xfe\x00example: /usr/local/lib/python/site-packages\x00"
    for root in (source, staged):
        root.mkdir()
        (root / "library.dylib").write_bytes(binary)

    verify_engine_copy(source, staged)


def test_verify_engine_copy_allows_upstream_wheel_build_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    staged = tmp_path / "staged"
    upstream_path = b"/" + b"Users/runner/work/cffi/cffi/src/c"
    binary = b"\xcf\xfa\xed\xfe\x00" + upstream_path + b"\x00"
    for root in (source, staged):
        root.mkdir()
        (root / "library.dylib").write_bytes(binary)

    verify_engine_copy(source, staged)


def test_verify_engine_copy_allows_homebrew_path_in_package_documentation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    staged = tmp_path / "staged"
    for root in (source, staged):
        root.mkdir()
        (root / "METADATA").write_text(
            "Homebrew ARM documentation: /opt/homebrew/share\n",
            encoding="utf-8",
        )

    verify_engine_copy(source, staged)


def test_verify_engine_copy_rejects_homebrew_path_in_executable_script(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    staged = tmp_path / "staged"
    source.mkdir()
    staged.mkdir()
    (source / "launch.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script = staged / "launch.sh"
    script.write_text("#!/opt/homebrew/bin/python\n", encoding="utf-8")
    script.chmod(0o700)

    with pytest.raises(BundleVerificationError, match="private build path"):
        verify_engine_copy(source, staged)


def test_otool_install_name_parses_dylib_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _VERIFIER,
        "_run",
        lambda command, check=True: "/tmp/libpython.dylib:\n@rpath/libpython3.13.dylib",
    )

    assert _otool_install_name(Path("libpython.dylib")) == "@rpath/libpython3.13.dylib"
