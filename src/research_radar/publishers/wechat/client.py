"""WeChat Official Account draft API client."""

from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from research_radar.exceptions import PublishError
from research_radar.security.secrets import SecretManager
from research_radar.storage.encrypted_store import EncryptedJsonStore


@dataclass(frozen=True)
class WeChatArticle:
    """WeChat draft article payload."""

    title: str
    author: str
    digest: str
    content: str
    thumb_media_id: str
    content_source_url: str | None = None


class WeChatDraftClient:
    """Minimal WeChat Official Account draft client."""

    base_url = "https://api.weixin.qq.com/cgi-bin"

    def __init__(
        self,
        secrets: SecretManager,
        token_store: EncryptedJsonStore | None = None,
    ) -> None:
        self._secrets = secrets
        self._token_store = token_store

    def add_draft(self, article: WeChatArticle) -> dict[str, object]:
        """Create a WeChat Official Account draft."""

        access_token = self.get_access_token()
        payload = {
            "articles": [
                {
                    "title": article.title,
                    "author": article.author,
                    "digest": article.digest,
                    "content": article.content,
                    "thumb_media_id": article.thumb_media_id,
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                    **(
                        {"content_source_url": article.content_source_url}
                        if article.content_source_url
                        else {}
                    ),
                }
            ]
        }
        return self._post_json(f"{self.base_url}/draft/add?access_token={access_token}", payload)

    def upload_article_image(self, image_path: Path) -> str:
        """Upload an article body image and return the WeChat-hosted URL."""

        if not image_path.exists():
            raise PublishError(f"WeChat image upload file not found: {image_path}")
        access_token = self.get_access_token()
        result = self._post_multipart_file(
            f"{self.base_url}/media/uploadimg?access_token={access_token}",
            field_name="media",
            file_path=image_path,
        )
        url = result.get("url")
        if not isinstance(url, str) or not url:
            raise PublishError(f"WeChat image upload response did not contain url: {result}")
        return url

    def upload_permanent_image_material(self, image_path: Path) -> dict[str, str]:
        """Upload a permanent image material and return its media id and URL."""

        if not image_path.exists():
            raise PublishError(f"WeChat thumbnail image not found: {image_path}")
        access_token = self.get_access_token()
        result = self._post_multipart_file(
            f"{self.base_url}/material/add_material?access_token={access_token}&type=image",
            field_name="media",
            file_path=image_path,
        )
        media_id = result.get("media_id")
        url = result.get("url")
        if not isinstance(media_id, str) or not media_id:
            raise PublishError(
                f"WeChat thumbnail upload response did not contain media_id: {result}"
            )
        if not isinstance(url, str):
            url = ""
        return {"media_id": media_id, "url": url}

    def get_access_token(self) -> str:
        """Return a cached access token or fetch a new one."""

        cached = self._load_cached_token()
        if cached is not None:
            return cached
        params = urlencode(
            {
                "grant_type": "client_credential",
                "appid": self._secrets.get_wechat_app_id(),
                "secret": self._secrets.get_wechat_app_secret(),
            }
        )
        try:
            with urlopen(f"{self.base_url}/token?{params}", timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise PublishError("Failed to fetch WeChat access token.") from exc
        token = payload.get("access_token")
        expires_in = payload.get("expires_in", 7200)
        if not isinstance(token, str):
            raise PublishError(f"WeChat token response did not contain access_token: {payload}")
        self._save_cached_token(token, int(expires_in))
        return token

    def _load_cached_token(self) -> str | None:
        if self._token_store is None or not self._token_store.path.exists():
            return None
        payload = self._token_store.load()
        token = payload.get("access_token")
        expires_at = payload.get("expires_at", 0)
        if (
            isinstance(token, str)
            and isinstance(expires_at, int)
            and expires_at > int(time.time()) + 60
        ):
            return token
        return None

    def _save_cached_token(self, token: str, expires_in: int) -> None:
        if self._token_store is None:
            return
        self._token_store.save({"access_token": token, "expires_at": int(time.time()) + expires_in})

    def _post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise PublishError("WeChat draft request failed.") from exc
        if not isinstance(result, dict):
            raise PublishError("WeChat draft response must be a JSON object.")
        errcode = result.get("errcode")
        if errcode not in (None, 0):
            raise PublishError(f"WeChat draft request failed: {result}")
        return result

    def _post_multipart_file(
        self,
        url: str,
        *,
        field_name: str,
        file_path: Path,
    ) -> dict[str, object]:
        boundary = f"ResearchRadarBoundary{uuid4().hex}"
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        file_bytes = file_path.read_bytes()
        body = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{file_path.name}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                file_bytes,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        request = Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise PublishError("WeChat image upload failed.") from exc
        if not isinstance(result, dict):
            raise PublishError("WeChat image upload response must be a JSON object.")
        errcode = result.get("errcode")
        if errcode not in (None, 0):
            raise PublishError(f"WeChat image upload failed: {result}")
        return result


def load_wechat_html(run_dir: Path) -> str:
    """Load composed WeChat HTML for publishing."""

    path = run_dir / "wechat.html"
    if not path.exists():
        raise PublishError(f"WeChat HTML not found: {path}")
    return path.read_text(encoding="utf-8")
