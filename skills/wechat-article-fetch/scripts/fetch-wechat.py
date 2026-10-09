#!/usr/bin/env python3
"""Fetch WeChat articles locally; external publication requires explicit opt-in."""

import argparse
import subprocess, json, re, os, sys, urllib.request, tempfile
from datetime import datetime, timezone
import hashlib
from archive_core import (DEFUDDLE_VERSION, validate_article, output_directory,
                          archive_id, atomic_write, frontmatter, telegraph_token)
from pathlib import Path
from urllib.parse import urlparse

from image_assets import ImageRewriteResult, R2Client, R2Config, make_slug, rewrite_images


def fetch(url: str) -> dict:
    """curl + defuddle 抓取微信文章"""
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or parsed.netloc != "mp.weixin.qq.com" or not (parsed.path.startswith("/s/") or parsed.path == "/s"):
        raise ValueError(f"不是有效的微信文章链接: {url}")

    ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
          "MicroMessenger/8.0.34(0x16082222) NetType/WIFI Language/zh_CN")

    print("🌐 抓取中...", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="wechat-fetch-") as temp:
        tmp_html = str(Path(temp) / "source.html")
        subprocess.run(["curl", "-sL", "--fail", "--show-error",
            "--proto", "=http,https", "--proto-redir", "=http,https",
            "--connect-timeout", "15", "--max-time", "30",
            "-H", f"User-Agent: {ua}",
            "-H", "Accept-Language: zh-CN,zh;q=0.9",
            url, "-o", tmp_html], check=True)
        raw = Path(tmp_html).read_bytes()
        r = subprocess.run(["npx", "--yes", f"defuddle@{DEFUDDLE_VERSION}", "parse", tmp_html, "-m", "-j"],
                           capture_output=True, text=True, check=True, timeout=120)
        data = json.loads(r.stdout)
        validate_article(raw, data)
        data["_raw_html"] = raw
        data["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        return data


def save_markdown(url: str, data: dict, image_mode: str = "local", output_dir=None) -> tuple[str, str, ImageRewriteResult]:
    """Commit a local snapshot BEFORE optional R2 operations."""
    if image_mode not in {"local", "r2"}:
        raise ValueError("Unknown image mode")
    raw = data.get("_raw_html")
    if not isinstance(raw, bytes):
        raise ValueError("Raw HTML bytes required for a durable archive")
    validate_article(raw, data)
    out_dir = output_directory(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = archive_id(url, data["title"])
    revision = hashlib.sha256(raw).hexdigest()[:16]
    fpath = out_dir / f"{slug}-{revision}.md"
    atomic_write(fpath.with_suffix(".html"), raw)
    source_content = data.get("content", "") or ""
    image_result = rewrite_images(source_content, out_dir, slug, url, mode="local")
    md = frontmatter(url, data) + f"# {data['title']}\n\n" + image_result.local_markdown + "\n"
    atomic_write(fpath, md)
    if image_mode == "r2":
        try:
            client = R2Client(R2Config.from_env())
            # Upload only already-saved assets, never retry a failed download here.
            for record in image_result.records:
                if record.local_path is None:
                    continue
                key = f"{client.config.key_prefix}/{slug}/{record.local_path.name}"
                try:
                    client.upload_file(record.local_path, key)
                    record.public_url = client.public_url(key)
                except Exception as exc:
                    record.error = f"R2 upload failed ({type(exc).__name__})"
            from image_assets import MARKDOWN_IMAGE_RE, _extract_url
            mapping = {r.source_url: r.public_url for r in image_result.records if r.public_url}
            image_result.publication_markdown = MARKDOWN_IMAGE_RE.sub(
                lambda m: f"![{m.group(1)}]({mapping[_extract_url(m.group(2))]})"
                if _extract_url(m.group(2)) in mapping else m.group(0), source_content)
        except ValueError as exc:
            image_result.r2_error = str(exc)
    return str(fpath), image_result.publication_markdown, image_result


def md_to_telegraph_nodes(md_text: str) -> list:
    """Markdown → Telegraph Node 数组"""
    nodes = []
    skip_set = {"李姝 李姝", "在小说阅读器读本章", "去阅读",
                "微信扫一扫", "微信扫一扫  ", "使用小程序",
                "继续滑动看下一个", "潇湘晨报", "向上滑动看下一个"}

    for line in md_text.split("\n"):
        s = line.strip()
        if not s or s in skip_set:
            continue

        img_matches = list(re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', s))
        if img_matches:
            pure = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', '', s).strip()
            if not pure or pure in {"△", "▲", "图：", "—", ""} or len(pure) < 5:
                for m in img_matches:
                    alt, src = m.group(1), m.group(2)
                    img_node = {"tag": "img", "attrs": {"src": src}}
                    if alt:
                        nodes.append({"tag": "figure", "children": [
                            img_node, {"tag": "figcaption", "children": [alt]}
                        ]})
                    else:
                        nodes.append(img_node)
                continue

        if s.startswith("## "):
            nodes.append({"tag": "h3", "children": [s[3:].strip("**")]})
        elif s.startswith("**") and s.endswith("**") and len(s) > 4:
            nodes.append({"tag": "h4", "children": [s.strip("*")]})
        else:
            nodes.append({"tag": "p", "children": [s]})

    return nodes


def publish_telegraph(title: str, author: str, author_url: str, content_md: str, token: str) -> str:
    """发布到 Telegra.ph"""
    nodes = md_to_telegraph_nodes(content_md)
    payload = {
        "access_token": token,
        "title": title,
        "author_name": author or "",
        "author_url": author_url,
        "content": nodes
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.telegra.ph/createPage",
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )
    result = json.loads(urllib.request.urlopen(req, timeout=30).read())
    if result.get("ok"):
        return result["result"]["url"]
    raise RuntimeError(f"Telegraph 发布失败: {result.get('error')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微信公众号文章 → Markdown + 本地图片归档 + 可选 R2")
    parser.add_argument("url", help="mp.weixin.qq.com/s/... 文章链接")
    parser.add_argument(
        "--images",
        choices=("local", "r2"),
        default="local",
        help="图片策略：local（默认，保存到 Markdown 同目录）或 r2（本地保存后上传 R2）",
    )
    publication = parser.add_mutually_exclusive_group()
    publication.add_argument("--publish", action="store_true", help="Explicitly publish this article to Telegraph")
    publication.add_argument("--no-telegraph", action="store_true", help="Compatibility alias for the local-only default")
    parser.add_argument("--output-dir", help="Override WECHAT_ARTICLE_OUTPUT_DIR / XDG data directory")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        data = fetch(args.url)
        fpath, content, images = save_markdown(args.url, data, args.images, args.output_dir)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Archive failed: {type(exc).__name__}: " + (str(exc) if isinstance(exc, ValueError) else "fetch/parse/storage operation failed"), file=sys.stderr)
        return 2
    print(f"Local archive: {fpath}")
    print(f"Raw HTML: {Path(fpath).with_suffix('.html')}")
    print(f"Images: found={images.discovered} saved={images.downloaded} uploaded={images.uploaded} failed={images.failed}")
    status = 0
    if images.failed or images.r2_error:
        print("Warning: partial image archive or R2 failure; local files preserved", file=sys.stderr)
        if images.r2_error:
            print(images.r2_error, file=sys.stderr)
        status = 1
    if args.publish:
        try:
            token = telegraph_token()
            print("Telegraph: " + publish_telegraph(data["title"], data.get("author", ""), args.url, content, token))
        except Exception as exc:
            print(f"Telegraph failed ({type(exc).__name__}); local files preserved", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
