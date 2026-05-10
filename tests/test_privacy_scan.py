from pathlib import Path

from research_radar.exceptions import PrivacyScanError
from research_radar.security.privacy_scan import assert_clean


def test_privacy_scan_passes_clean_file(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text("No secrets here.\n", encoding="utf-8")

    assert_clean(tmp_path)


def test_privacy_scan_fails_on_fake_secret(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    fake_value = "abcd1234abcd1234"
    path.write_text("token='" + fake_value + "'\n", encoding="utf-8")

    try:
        assert_clean(tmp_path)
    except PrivacyScanError as exc:
        assert "token" in str(exc)
    else:
        raise AssertionError("Expected PrivacyScanError")


def test_privacy_scan_skips_local_only_secret_files(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    config_path = tmp_path / "config.yaml"
    fake_secret = "abcd1234abcd1234"

    env_path.write_text(f"DEEPSEEK_API_KEY='{fake_secret}'\n", encoding="utf-8")
    config_path.write_text(f"secret: '{fake_secret}'\n", encoding="utf-8")

    assert_clean(tmp_path)
