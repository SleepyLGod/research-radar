"""Upload one validated App-selected image through the existing WeChat client."""

from __future__ import annotations

import hashlib
import io
import os
import stat
from collections.abc import Callable
from pathlib import Path
from threading import Event

from PIL import Image, UnidentifiedImageError

from research_radar.exceptions import OperationCancelled, PublishError
from research_radar.publishers.wechat.client import WeChatDraftClient
from research_radar.security.secrets import SecretManager

MAX_COVER_BYTES = 2 * 1024 * 1024
MAX_COVER_PIXELS = 40_000_000


def upload_wechat_cover(
    image_path: Path,
    image_sha256: str,
    secret_manager: SecretManager,
    *,
    client_factory: Callable[..., WeChatDraftClient] = WeChatDraftClient,
    cancellation_event: Event | None = None,
) -> dict[str, str]:
    """Upload once, returning a receipt without changing configuration or any report."""
    if cancellation_event is not None and cancellation_event.is_set():
        raise OperationCancelled()
    try:
        descriptor = os.open(image_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as image_file:
            info = os.fstat(image_file.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_COVER_BYTES:
                raise PublishError("Choose a PNG or JPEG cover up to 2 MiB.")
            content = image_file.read(MAX_COVER_BYTES + 1)
        if len(content) > MAX_COVER_BYTES or hashlib.sha256(content).hexdigest() != image_sha256:
            raise PublishError("The selected cover changed; choose and confirm it again.")
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"PNG", "JPEG"} or image.width * image.height > MAX_COVER_PIXELS:
                raise PublishError("Choose a PNG or JPEG cover up to 40 megapixels.")
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise PublishError("The selected cover could not be read as a safe image.") from exc
    result = client_factory(secret_manager).upload_permanent_image_material(
        image_path, image_bytes=content, cancellation_event=cancellation_event,
    )
    media_id = result.get("media_id")
    if not isinstance(media_id, str) or not media_id.strip():
        raise PublishError("WeChat did not return a cover media ID.")
    return {"media_id": media_id, "image_sha256": image_sha256}
