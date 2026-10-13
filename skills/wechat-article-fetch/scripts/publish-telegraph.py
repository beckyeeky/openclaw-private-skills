#!/usr/bin/env python3
"""将微信文章发布到 Telegra.ph
用法: python3 publish-telegraph.py <markdown文件路径>

依赖: pip3 install telegraph (或直接用 urllib)
"""

import json, urllib.request, re, sys, os
import argparse
from pathlib import Path
from archive_core import telegraph_token
from image_assets import MARKDOWN_IMAGE_RE, _extract_url
from telegraph_nodes import md_to_telegraph_nodes


def publish(title: str, author: str, author_url: str, content_md: str, token: str) -> str:
    """发布到 Telegra.ph，返回公开链接"""
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicitly publish existing Markdown to Telegraph")
    parser.add_argument("markdown")
    parser.add_argument("--publish", action="store_true", required=True, help="Consent to public publication")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.markdown).read_text(encoding="utf-8")
        metadata = {}
        if raw.startswith("---\n"):
            header, separator, body = raw[4:].partition("\n---\n")
            if not separator:
                raise ValueError("Invalid archive frontmatter")
            for line in header.splitlines():
                key, separator, value = line.partition(": ")
                if separator:
                    metadata[key] = json.loads(value)
        else:
            # Compatibility with pre-frontmatter archives.
            body = raw.split("---", 1)[-1]
            for key, label in (("author", "作者"), ("source_url", "链接")):
                match = re.search(r"\*\*" + label + r"\*\*: (.+)", raw)
                metadata[key] = match.group(1).strip() if match else ""
        title = re.search(r"^# (.+)", raw, re.MULTILINE)
        metadata.setdefault("title", title.group(1).strip() if title else "Article")
        for match in MARKDOWN_IMAGE_RE.finditer(body):
            if not _extract_url(match.group(2)).startswith("https://"):
                raise ValueError("Publication needs public HTTPS images, not local assets; use fetch --images r2 --publish")
        token = telegraph_token()
        print(publish(metadata["title"], metadata.get("author", ""), metadata.get("source_url", ""), body, token))
        return 0
    except Exception as exc:
        print(f"Publication failed ({type(exc).__name__}); local file unchanged", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
