"""Offline coverage for the bounded, explicitly requested WeChat cover upload."""

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PIL import Image

from research_radar.app_bridge.runner import BridgeDependencies, run_bridge
from research_radar.exceptions import PublishError
from research_radar.security.secrets import InMemorySecretBackend, SecretManager


def image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 18), "teal").save(output, format="PNG")
    return output.getvalue()


def test_cover_service_reuses_permanent_material_client_once(tmp_path: Path) -> None:
    from research_radar.application.wechat_cover import upload_wechat_cover

    image = tmp_path / "cover.png"
    image.write_bytes(image_bytes())
    uploads = []

    class Client:
        def __init__(self, manager: SecretManager) -> None:
            pass

        def upload_permanent_image_material(
            self, path: Path, *, image_bytes: bytes, cancellation_event: Event | None = None
        ) -> dict[str, str]:
            uploads.append(image_bytes)
            return {"media_id": "offline-cover-id", "url": "https://example.com/cover.png"}

    receipt = upload_wechat_cover(
        image,
        hashlib.sha256(image.read_bytes()).hexdigest(),
        SecretManager(InMemorySecretBackend()),
        client_factory=Client,
    )
    assert receipt == {
        "media_id": "offline-cover-id",
        "image_sha256": hashlib.sha256(image_bytes()).hexdigest(),
    }
    assert uploads == [image_bytes()]
    assert list(tmp_path.iterdir()) == [image]


@pytest.mark.parametrize("invalid", ["symlink", "bytes", "oversize", "hash"])
def test_invalid_cover_never_constructs_client(tmp_path: Path, invalid: str) -> None:
    from research_radar.application.wechat_cover import upload_wechat_cover

    original = tmp_path / "original.png"
    original.write_bytes(image_bytes())
    image = tmp_path / "cover.png"
    if invalid == "symlink":
        image.symlink_to(original)
    else:
        image.write_bytes(
            b"not an image"
            if invalid == "bytes"
            else b"x" * (2 * 1024 * 1024 + 1)
            if invalid == "oversize"
            else image_bytes()
        )

    def forbidden(*args: object) -> None:
        pytest.fail("Invalid input must not access secrets or construct a network client")

    digest = "0" * 64 if invalid == "hash" else hashlib.sha256(image.read_bytes()).hexdigest()
    with pytest.raises(PublishError):
        upload_wechat_cover(
            image, digest, SecretManager(InMemorySecretBackend()), client_factory=forbidden
        )


def test_cover_bridge_is_separate_from_research_and_delivery(tmp_path: Path) -> None:
    from research_radar.app_bridge.handlers import handle_upload_wechat_cover

    root = tmp_path / "app"
    job = root / "jobs" / "00000000-0000-4000-8000-000000000003"
    job.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    image = job / "cover.png"
    image.write_bytes(image_bytes())
    config_path = root / "config.json"
    config_path.write_text("{}")
    original_config = config_path.read_bytes()
    request = {
        "schema_version": 1,
        "request_id": job.name,
        "command": "upload_wechat_cover",
        "created_at": "2026-10-21T00:00:00Z",
        "app_support_root": str(root),
        "config_path": str(config_path),
        "payload": {
            "image_path": str(image),
            "image_sha256": hashlib.sha256(image_bytes()).hexdigest(),
        },
    }
    (job / "request.json").write_text(json.dumps(request))
    config = SimpleNamespace(
        wechat=SimpleNamespace(app_id_secret="wx.id", app_secret_secret="wx.secret")
    )

    class Client:
        def __init__(self, manager: SecretManager) -> None:
            assert manager.get_wechat_app_id() == "offline-id"
            assert manager.get_wechat_app_secret() == "offline-secret"

        def upload_permanent_image_material(self, path: Path, **kwargs: object) -> dict[str, str]:
            assert kwargs["image_bytes"] == image_bytes()
            return {"media_id": "offline-cover-id", "url": ""}

    def handler(*args, **kwargs):
        return handle_upload_wechat_cover(*args, **kwargs, wechat_client_factory=Client)

    backend = InMemorySecretBackend()
    backend.set_secret("wx.id", "offline-id")
    backend.set_secret("wx.secret", "offline-secret")
    dependencies = replace(
        BridgeDependencies.testing(),
        upload_wechat_cover=handler,
        config_loader=lambda *args: config,
        secret_manager_factory=lambda: SecretManager(backend),
    )
    code = run_bridge(
        request_path=job / "request.json",
        events_path=job / "events.jsonl",
        result_path=job / "result.json",
        error_path=job / "error.json",
        establish_session=False,
        watch_parent=False,
        dependencies=dependencies,
    )
    assert code == 0
    result = json.loads((job / "result.json").read_text())
    assert result["cover"]["media_id"] == "offline-cover-id"
    assert result["delivery"] is None and result["report"] is None
    assert config_path.read_bytes() == original_config
    assert not (root / "workspace").exists()
    assert not (root / "state").exists()


def test_canonical_cover_contract_matches_swift_fixture(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from research_radar.app_bridge.protocol import load_request
    from research_radar.app_bridge.runner import _result_envelope

    fixtures = Path("apps/macos/ResearchRadar/Tests/Fixtures/Protocol")
    canonical = json.loads((fixtures / "upload-cover-request.json").read_text())
    root = tmp_path / "app"
    job = root / "jobs" / canonical["request_id"]
    job.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    image = job / "cover.png"
    image.write_bytes(image_bytes())
    config = root / "config.json"
    config.write_text("{}")
    canonical["app_support_root"] = str(root)
    canonical["config_path"] = str(config)
    canonical["payload"]["image_path"] = str(image)
    path = job / "request.json"
    path.write_text(json.dumps(canonical))
    request = load_request(path, job_dir=job)
    output = {"media_id": "offline-cover-id", "image_sha256": request.payload.image_sha256}
    result = _result_envelope(
        request, output, completed_at=datetime(2026, 10, 21, 0, 0, 1, tzinfo=UTC)
    )
    assert result == json.loads((fixtures / "upload-cover-result.json").read_text())


def test_cover_job_accepts_equivalent_system_directory_alias(tmp_path: Path) -> None:
    from research_radar.app_bridge.protocol import load_request

    root = tmp_path / "app"
    job = root / "jobs" / "00000000-0000-4000-8000-000000000003"
    job.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    (job / "cover.png").write_bytes(image_bytes())
    config = root / "config.json"
    config.write_text("{}")
    alias = job / "alias"
    alias.mkdir()
    image = alias / ".." / "cover.png"
    request = job / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": job.name,
                "command": "upload_wechat_cover",
                "created_at": "2026-10-21T00:00:00Z",
                "app_support_root": str(root),
                "config_path": str(config),
                "payload": {
                    "image_path": str(image),
                    "image_sha256": hashlib.sha256(image_bytes()).hexdigest(),
                },
            }
        )
    )
    parsed = load_request(request, job_dir=job)
    assert parsed.payload.image_path == job.resolve() / "cover.png"


def test_client_uploads_validated_bytes_even_if_staged_path_changes(
    tmp_path: Path, monkeypatch
) -> None:
    from research_radar.application.wechat_cover import upload_wechat_cover
    from research_radar.publishers.wechat.client import WeChatDraftClient

    image = tmp_path / "cover.png"
    original = image_bytes()
    image.write_bytes(original)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self) -> bytes:
            return b'{"media_id":"offline-cover-id"}'

    def offline_http(request, **kwargs):
        requests.append(request.data)
        return Response()

    class ChangingPathClient(WeChatDraftClient):
        def get_access_token(self) -> str:
            image.write_bytes(b"different unconfirmed content")
            return "offline-token"

    monkeypatch.setattr("research_radar.publishers.wechat.client.urlopen", offline_http)
    receipt = upload_wechat_cover(
        image,
        hashlib.sha256(original).hexdigest(),
        SecretManager(InMemorySecretBackend()),
        client_factory=ChangingPathClient,
    )
    assert len(requests) == 1
    assert original in requests[0]
    assert b"different unconfirmed content" not in requests[0]
    assert receipt["media_id"] == "offline-cover-id"


@pytest.mark.parametrize("cancel_at", ["before_handler", "credentials", "token"])
def test_cover_cancellation_prevents_starting_upload(
    tmp_path: Path, monkeypatch, cancel_at: str
) -> None:
    from research_radar.app_bridge.events import EventWriter
    from research_radar.app_bridge.handlers import handle_upload_wechat_cover
    from research_radar.app_bridge.protocol import (
        EngineCommand,
        EngineRequestV1,
        UploadWeChatCoverPayloadV1,
    )
    from research_radar.exceptions import OperationCancelled

    image = tmp_path / "cover.png"
    image.write_bytes(image_bytes())
    cancelled = Event()
    requests: list[str] = []

    class Backend(InMemorySecretBackend):
        def get_secret(self, name: str) -> str:
            if cancel_at == "credentials":
                cancelled.set()
            return super().get_secret(name)

    class Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self) -> bytes:
            return json.dumps(self.payload).encode()

    def offline_http(request, **kwargs):
        if isinstance(request, str):
            requests.append("token")
            if cancel_at == "token":
                cancelled.set()
            return Response({"access_token": "fake-token", "expires_in": 7200})
        requests.append("upload")
        return Response({"media_id": "offline-cover-id"})

    monkeypatch.setattr("research_radar.publishers.wechat.client.urlopen", offline_http)
    backend = Backend()
    backend.set_secret("wx.id", "offline-id")
    backend.set_secret("wx.secret", "offline-secret")
    if cancel_at == "before_handler":
        cancelled.set()
    request = EngineRequestV1(
        schema_version=1, request_id="offline-cover", command=EngineCommand.UPLOAD_WECHAT_COVER,
        created_at="2026-10-23T00:00:00Z", app_support_root=tmp_path, config_path=None,
        payload=UploadWeChatCoverPayloadV1(image, hashlib.sha256(image_bytes()).hexdigest()),
    )
    with pytest.raises(OperationCancelled):
        handle_upload_wechat_cover(
            request,
            config=SimpleNamespace(wechat=SimpleNamespace(
                app_id_secret="wx.id", app_secret_secret="wx.secret"
            )),
            secrets=SecretManager(backend),
            events=EventWriter(tmp_path / "events.jsonl", request_id=request.request_id),
            pdf_helper_path=None, cancellation_event=cancelled,
        )
    assert "upload" not in requests
    if cancel_at == "before_handler":
        assert requests == []
    assert image.read_bytes() == image_bytes()


@pytest.mark.parametrize("escape", ["outside", "other_job", "symlink"])
def test_cover_protocol_rejects_non_job_images(tmp_path: Path, escape: str) -> None:
    from research_radar.app_bridge.protocol import ProtocolError, load_request

    root = tmp_path / "app"
    job = root / "jobs" / "00000000-0000-4000-8000-000000000003"
    job.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    image = (tmp_path if escape == "outside" else root) / "cover.png"
    image.write_bytes(image_bytes())
    if escape == "symlink":
        link = job / "cover.png"
        link.symlink_to(image)
        image = link
    config = root / "config.json"
    config.write_text("{}")
    request = job / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": job.name,
                "command": "upload_wechat_cover",
                "created_at": "2026-10-21T00:00:00Z",
                "app_support_root": str(root),
                "config_path": str(config),
                "payload": {
                    "image_path": str(image),
                    "image_sha256": hashlib.sha256(image_bytes()).hexdigest(),
                },
            }
        )
    )
    with pytest.raises(ProtocolError):
        load_request(request, job_dir=job)
