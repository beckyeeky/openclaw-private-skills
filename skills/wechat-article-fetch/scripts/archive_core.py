"""Local archive identity, validation, metadata and atomic writes (stdlib only)."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from image_assets import make_slug

DEFUDDLE_VERSION = "0.19.4"
ERROR_PHRASES = (
    "环境异常", "已被发布者删除", "该内容已被发布者删除", "请在微信客户端打开",
    "访问过于频繁", "内容已被删除", "此内容因违规无法查看", "该内容无法查看",
    "链接已过期", "网页无法访问", "验证后继续访问", "完成验证", "安全验证",
    "captcha", "access denied", "just a moment", "verify you are human",
    "404 not found", "403 forbidden", "502 bad gateway", "service unavailable",
    "internal server error", "页面不存在", "系统繁忙", "操作频繁",
)


class PageSignals(HTMLParser):
    def __init__(self, raw):
        super().__init__()
        self.hidden = 0
        self.text = []
        self.title = []
        self.in_title = False
        self.article_depth = 0
        self.article_text = []
        self.article_images = 0
        self.feed(raw)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if attrs.get("id") == "js_content" or tag == "article":
            self.article_depth = 1
        elif self.article_depth and tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}:
            self.article_depth += 1
        if self.article_depth and tag == "img":
            self.article_images += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False
        if self.article_depth and tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}:
            self.article_depth -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.in_title:
                self.title.append(data)
            if self.article_depth:
                self.article_text.append(data)


def useful(text):
    return "".join(re.findall(r"[\w\u4e00-\u9fff]", text, re.UNICODE)).lower()


def is_error(text):
    normalized = useful(text)
    return any(normalized == useful(phrase) for phrase in ERROR_PHRASES)


def validate_article(raw, data):
    """Reject status/challenge pages without rejecting quotations in real articles.

    Normal extraction needs 20 useful characters. Structured article bodies can
    be short (4 characters) or image-only. Ambiguous tiny pages fail explicitly.
    """
    if not isinstance(data, dict) or not isinstance(data.get("content", ""), str) or not isinstance(data.get("title", ""), str):
        raise ValueError("Extractor returned an invalid article schema")
    page = PageSignals(raw.decode("utf-8", errors="replace"))
    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "").strip()
    body = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", content)
    body = re.sub(r"<[^>]+>", "", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    body = re.sub(r"^#+\s+.*$", "", body, flags=re.MULTILINE)
    article_text = " ".join(page.article_text)
    structured = len(useful(article_text)) >= 4 or page.article_images > 0
    visible = " ".join(page.text)
    if not title or title.lower() in {"untitled", "undefined", "null"}:
        raise ValueError("Missing article title; refusing an unverified archive")
    if is_error(body) or (not structured and (
        is_error(title) or is_error(" ".join(page.title)) or
        (len(useful(visible)) < 300 and any(
            body.strip().lower().startswith(p) for p in ERROR_PHRASES))
    )):
        raise ValueError("Blocked, deleted or challenge page; not an article")
    minimum = 4 if structured else 20
    if len(useful(body)) < minimum and not (structured and page.article_images and "![" in content):
        raise ValueError("Insufficient useful article body; inspect raw page/browser rather than reporting success")


def output_directory(value=None):
    if value:
        return Path(value).expanduser()
    configured = os.environ.get("WECHAT_ARTICLE_OUTPUT_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(base).expanduser() if base else Path.home() / ".local" / "share") / "wechat-articles"


def archive_id(url, title):
    # Reserve space for URL/revision hashes under common 255-byte filename limits.
    slug = make_slug(title).encode("utf-8")[:160].decode("utf-8", errors="ignore")
    return slug + "-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def frontmatter(url, data):
    values = {
        "title": data["title"], "source_url": url,
        "fetched_at": data.get("_fetched_at") or datetime.now(timezone.utc).isoformat(),
        "author": data.get("author") or "unknown",
        "publish_date": data.get("published") or data.get("date") or "unknown",
    }
    return "---\n" + "".join(k + ": " + json.dumps(v, ensure_ascii=False) + "\n" for k, v in values.items()) + "---\n\n"


def telegraph_token():
    token = os.environ.get("TELEGRAPH_ACCESS_TOKEN", "").strip()
    if token:
        return token
    path = os.environ.get("TELEGRAPH_TOKEN_PATH", "").strip()
    # Compatibility only: this file is read ONLY after an explicit publish request.
    candidate = Path(path).expanduser() if path else Path.home() / ".hermes" / "telegraph_token"
    if candidate.is_file():
        return candidate.read_text().strip()
    raise ValueError("Explicit publication requires TELEGRAPH_ACCESS_TOKEN or TELEGRAPH_TOKEN_PATH")
