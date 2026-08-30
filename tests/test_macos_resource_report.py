import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "measure_macos_resources", Path("script/measure_macos_resources.py")
)
assert _SPEC is not None and _SPEC.loader is not None
_MEASURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MEASURE)
directory_size = _MEASURE.directory_size


def test_directory_size_reports_logical_and_disk_bytes_without_following_symlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    payload = root / "payload.bin"
    payload.write_bytes(b"12345")
    (root / "payload-link").symlink_to("payload.bin")

    size = directory_size(root)

    assert size["logical_bytes"] == 5
    assert size["disk_bytes"] >= 5
