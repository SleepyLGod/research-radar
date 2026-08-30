from pathlib import Path

import pytest

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


def test_privacy_scan_allows_secret_reference_names(tmp_path: Path) -> None:
    path = tmp_path / "provider.py"
    path.write_text('api_key_secret="deepseek.api_key"\n', encoding="utf-8")

    assert_clean(tmp_path)


def test_privacy_scan_allows_smtp_password_secret_reference_name(tmp_path: Path) -> None:
    path = tmp_path / "email_config.py"
    reference = "email.smtp_" + "password"
    path.write_text(
        "password_" + "secret" + "=" + repr(reference) + "\n",
        encoding="utf-8",
    )

    assert_clean(tmp_path)


def test_privacy_scan_does_not_hide_secret_beside_smtp_reference(tmp_path: Path) -> None:
    path = tmp_path / "bad_email_config.py"
    fake_value = "abcd1234abcd1234"
    path.write_text(
        'password_secret="email.smtp_password"; token="' + fake_value + '"\n',
        encoding="utf-8",
    )

    with pytest.raises(PrivacyScanError, match="token"):
        assert_clean(tmp_path)


def test_privacy_scan_allows_swift_named_secret_but_not_neighboring_value(
    tmp_path: Path,
) -> None:
    path = tmp_path / "AppConfiguration.swift"
    fake_value = "abcd1234abcd1234"
    path.write_text(
        'apiKeySecret: "deepseek.api_key", token="' + fake_value + '"\n',
        encoding="utf-8",
    )

    with pytest.raises(PrivacyScanError, match="token"):
        assert_clean(tmp_path)


def test_privacy_scan_skips_local_only_secret_files(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    config_path = tmp_path / "config.yaml"
    fake_secret = "abcd1234abcd1234"

    env_path.write_text(f"DEEPSEEK_API_KEY='{fake_secret}'\n", encoding="utf-8")
    config_path.write_text(f"secret: '{fake_secret}'\n", encoding="utf-8")

    assert_clean(tmp_path)


@pytest.mark.parametrize("directory", [".build", ".swiftpm", "build", "dist"])
def test_privacy_scan_skips_rebuildable_output_directories(
    tmp_path: Path, directory: str
) -> None:
    output = tmp_path / directory
    output.mkdir()
    local_path = "/" + "Users/private/generated"
    (output / "generated.txt").write_text(local_path, encoding="utf-8")

    assert_clean(tmp_path)
