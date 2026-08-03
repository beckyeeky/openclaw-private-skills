#!/usr/bin/env python3
"""Download article images locally and optionally publish them to Cloudflare R2.

This module intentionally uses only Python's standard library.  It keeps a local
copy even when R2 is enabled, so a temporary cloud-storage failure cannot destroy
an article archive.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import mimetypes
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


# Defuddle normally emits this Markdown form.  The optional title syntax is
# accepted as well, while deliberately avoiding a broad URL regex that could
# rewrite ordinary links.
MARKDOWN_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\((<[^>]+>|[^)\s]+)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\)"
)

WECHAT_IMAGE_HOSTS = {"mmbiz.qpic.cn"}
DEFAULT_MAX_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.34(0x16082222) NetType/WIFI Language/zh_CN"
)
FALLBACK_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)


class ImageAssetError(RuntimeError):
    """Raised when an image cannot be downloaded or validated."""


@dataclass
class R2Config:
    """Minimal configuration for the Cloudflare R2 S3-compatible API."""

    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    public_base_url: str
    key_prefix: str = "wechat"

    @classmethod
    def from_env(cls) -> "R2Config":
        names = {
            "account_id": "CF_R2_ACCOUNT_ID",
            "access_key_id": "CF_R2_ACCESS_KEY_ID",
            "secret_access_key": "CF_R2_SECRET_ACCESS_KEY",
            "bucket": "CF_R2_BUCKET",
            "public_base_url": "CF_R2_PUBLIC_BASE_URL",
        }
        values = {field: os.environ.get(env_name, "").strip() for field, env_name in names.items()}
        missing = [env_name for field, env_name in names.items() if not values[field]]
        if missing:
            raise ValueError("R2 配置不完整，缺少环境变量: " + ", ".join(missing))
        values["key_prefix"] = os.environ.get("CF_R2_KEY_PREFIX", "wechat").strip("/") or "wechat"
        values["public_base_url"] = values["public_base_url"].rstrip("/")
        return cls(**values)

    @property
    def endpoint(self) -> str:
        return "https://%s.r2.cloudflarestorage.com" % self.account_id


class R2Client:
    """Small dependency-free R2 client using AWS Signature Version 4."""

    def __init__(self, config: R2Config, timeout: int = 60):
        self.config = config
        self.timeout = timeout

    @staticmethod
    def _sign(key: bytes, value: str) -> bytes:
        return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()

    def _authorization(self, key: str, payload: bytes, content_type: str) -> Tuple[str, Dict[str, str]]:
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        host = urlparse(self.config.endpoint).netloc
        payload_hash = hashlib.sha256(payload).hexdigest()

        # R2 uses the S3-compatible API with the AWS region name "auto".
        canonical_uri = "/%s/%s" % (
            quote(self.config.bucket, safe=""),
            quote(key, safe="/~"),
        )
        canonical_headers = (
            "host:%s\n"
            "x-amz-content-sha256:%s\n"
            "x-amz-date:%s\n"
            % (host, payload_hash, amz_date)
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [
                "PUT",
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = "%s/auto/s3/aws4_request" % date_stamp
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        k_date = self._sign(("AWS4" + self.config.secret_access_key).encode("utf-8"), date_stamp)
        k_region = self._sign(k_date, "auto")
        k_service = self._sign(k_region, "s3")
        k_signing = self._sign(k_service, "aws4_request")
        signature = hmac.new(
            k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
            % (self.config.access_key_id, credential_scope, signed_headers, signature)
        )
        headers = {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
            "Cache-Control": "public, max-age=31536000, immutable",
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        return self.config.endpoint + canonical_uri, headers

    def upload_file(self, local_path: Path, key: str) -> None:
        payload = local_path.read_bytes()
        content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        url, headers = self._authorization(key, payload, content_type)
        request = Request(url, data=payload, headers=headers, method="PUT")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", response.getcode())
                if status < 200 or status >= 300:
                    raise ImageAssetError("R2 上传返回 HTTP %s" % status)
        except HTTPError as exc:
            # Do not print the response body: some S3-compatible errors may
            # echo request details, and credentials should never enter logs.
            raise ImageAssetError("R2 上传失败，HTTP %s" % exc.code) from exc
        except (URLError, OSError) as exc:
            raise ImageAssetError("R2 上传网络失败: %s" % exc.__class__.__name__) from exc

    def public_url(self, key: str) -> str:
        return "%s/%s" % (self.config.public_base_url, quote(key, safe="/~"))


def _image_extension(content_type: str, payload: bytes, source_url: str) -> str:
    """Choose a browser-friendly extension from bytes, headers, then URL."""
    lowered = (content_type or "").split(";", 1)[0].strip().lower()
    magic = (
        (b"\xff\xd8\xff", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"GIF87a", ".gif"),
        (b"GIF89a", ".gif"),
        (b"RIFF", ".webp"),
        (b"BM", ".bmp"),
        (b"II*\x00", ".tif"),
        (b"MM\x00*", ".tif"),
    )
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp"
    for prefix, extension in magic:
        if payload.startswith(prefix):
            return extension
    type_extensions = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/tiff": ".tif",
        "image/svg+xml": ".svg",
    }
    if lowered in type_extensions:
        return type_extensions[lowered]
    suffix = Path(urlparse(source_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".img"


def _looks_like_image(content_type: str, payload: bytes) -> bool:
    lowered = (content_type or "").split(";", 1)[0].strip().lower()
    if lowered.startswith("image/"):
        return True
    return any(
        payload.startswith(prefix)
        for prefix in (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"II*\x00", b"MM\x00*")
    )


def _is_wechat_image(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in WECHAT_IMAGE_HOSTS


def _download_image(
    url: str,
    source_page_url: str,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    timeout: int = 30,
) -> Tuple[bytes, str]:
    """Download one image, using a WeChat-compatible Referer and UA."""
    referers = [source_page_url]
    if _is_wechat_image(url):
        referers.append("https://mp.weixin.qq.com/")
    last_error: Optional[Exception] = None
    for referer in referers:
        for attempt, user_agent in enumerate((DEFAULT_USER_AGENT, FALLBACK_USER_AGENT), start=1):
            request = Request(
                url,
                headers={
                    "User-Agent": user_agent,
                    "Referer": referer,
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    chunks: List[bytes] = []
                    total = 0
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise ImageAssetError("图片超过 %d MB 限制" % (max_bytes // (1024 * 1024)))
                        chunks.append(chunk)
                    payload = b"".join(chunks)
                    if not payload or not _looks_like_image(content_type, payload):
                        raise ImageAssetError("响应不是可识别的图片")
                    return payload, content_type
            except (HTTPError, URLError, OSError, ImageAssetError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.4)
    if isinstance(last_error, ImageAssetError):
        raise last_error
    raise ImageAssetError("下载失败: %s" % (last_error.__class__.__name__ if last_error else "unknown"))


def _extract_url(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == "<" and raw[-1] == ">":
        raw = raw[1:-1]
    return html.unescape(raw)


def _existing_asset(directory: Path, url_hash: str) -> Optional[Path]:
    # Filename format is NNN-<hash>.<ext>.  Do not match .part files or
    # similarly named files from another hash.
    matches = sorted(directory.glob("*-" + url_hash + ".*"))
    for path in matches:
        if path.is_file() and path.stat().st_size > 0 and not path.name.endswith(".part"):
            return path
    return None


@dataclass
class ImageRecord:
    source_url: str
    local_path: Optional[Path] = None
    local_ref: Optional[str] = None
    public_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ImageRewriteResult:
    local_markdown: str
    publication_markdown: str
    records: List[ImageRecord] = field(default_factory=list)
    r2_error: Optional[str] = None

    @property
    def discovered(self) -> int:
        return len(self.records)

    @property
    def downloaded(self) -> int:
        return sum(record.local_path is not None for record in self.records)

    @property
    def uploaded(self) -> int:
        return sum(record.public_url is not None for record in self.records)

    @property
    def failed(self) -> int:
        return sum(record.error is not None for record in self.records)



def rewrite_images(
    markdown: str,
    article_root: Path,
    slug: str,
    source_page_url: str,
    mode: str = "local",
    r2_client: Optional[R2Client] = None,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> ImageRewriteResult:
    """Save Markdown images locally and optionally upload them to R2.

    The returned ``local_markdown`` always uses relative local paths.  The
    returned ``publication_markdown`` is intended for Telegraph: in R2 mode it
    uses public R2 URLs, while local mode keeps the original remote URLs for
    backwards-compatible Telegraph publishing.
    """
    if mode not in {"local", "r2"}:
        raise ValueError("图片模式只能是 local 或 r2")
    if mode == "r2" and r2_client is None:
        raise ValueError("r2 模式需要 R2 客户端")

    asset_dir = article_root / "assets" / slug
    asset_dir.mkdir(parents=True, exist_ok=True)
    records_by_url: Dict[str, ImageRecord] = {}
    records: List[ImageRecord] = []
    sequence = 0

    def handle(match: re.Match, target: str) -> str:
        nonlocal sequence
        alt = match.group(1)
        source_url = _extract_url(match.group(2))
        if not source_url.startswith(("http://", "https://")):
            return match.group(0)
        if source_url not in records_by_url:
            sequence += 1
            url_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:10]
            record = ImageRecord(source_url=source_url)
            records_by_url[source_url] = record
            records.append(record)
            try:
                existing = _existing_asset(asset_dir, url_hash)
                if existing is None:
                    payload, content_type = _download_image(
                        source_url, source_page_url, max_bytes=max_bytes
                    )
                    extension = _image_extension(content_type, payload, source_url)
                    filename = "%03d-%s%s" % (sequence, url_hash, extension)
                    final_path = asset_dir / filename
                    part_path = asset_dir / (filename + ".part")
                    part_path.write_bytes(payload)
                    os.replace(str(part_path), str(final_path))
                    existing = final_path
                record.local_path = existing
                record.local_ref = (Path("assets") / slug / existing.name).as_posix()
                if mode == "r2" and r2_client is not None:
                    key = "%s/%s/%s" % (
                        r2_client.config.key_prefix.strip("/"),
                        slug,
                        existing.name,
                    )
                    r2_client.upload_file(existing, key)
                    record.public_url = r2_client.public_url(key)
            except Exception as exc:  # local archive should continue per image
                record.error = str(exc)

        record = records_by_url[source_url]
        local_replacement = match.group(0)
        if record.local_ref:
            local_replacement = "![%s](%s)" % (alt, record.local_ref)
        if target == "local":
            return local_replacement
        # For Telegraph, never emit a relative local path.  A failed R2 upload
        # falls back to the original URL, which may still work via Telegraph's
        # own fetcher/Referer behavior.
        if record.public_url:
            return "![%s](%s)" % (alt, record.public_url)
        return match.group(0)

    local_markdown = MARKDOWN_IMAGE_RE.sub(lambda m: handle(m, "local"), markdown)
    publication_markdown = MARKDOWN_IMAGE_RE.sub(lambda m: handle(m, "publication"), markdown)
    return ImageRewriteResult(local_markdown, publication_markdown, records)


def make_slug(title: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff_-]", "-", title, flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip("-") or "article"
    return slug[:100]


__all__ = [
    "ImageRecord",
    "ImageRewriteResult",
    "R2Client",
    "R2Config",
    "make_slug",
    "rewrite_images",
]
