#!/usr/bin/env python3
"""将微信文章发布到 Telegra.ph
用法: python3 publish-telegraph.py <markdown文件路径>

依赖: pip3 install telegraph (或直接用 urllib)
"""

import json, urllib.request, re, sys, os
from datetime import datetime


def md_to_telegraph_nodes(md_text: str) -> list:
    """将 Markdown 正文转换为 Telegraph Node 数组"""
    nodes = []
    skip_set = {"李姝 李姝", "在小说阅读器读本章", "去阅读",
                "微信扫一扫", "微信扫一扫  ", "使用小程序",
                "继续滑动看下一个", "潇湘晨报", "向上滑动看下一个"}

    for line in md_text.split("\n"):
        s = line.strip()
        if not s or s in skip_set:
            continue

        # 图片行
        img_matches = list(re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', s))
        if img_matches:
            pure = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', '', s).strip()
            if not pure or pure in {"△", "▲", "图：", "—", ""} or len(pure) < 5:
                for m in img_matches:
                    alt, src = m.group(1), m.group(2)
                    img_node = {"tag": "img", "attrs": {"src": src}}
                    if alt:
                        nodes.append({"tag": "figure", "children": [
                            img_node,
                            {"tag": "figcaption", "children": [alt]}
                        ]})
                    else:
                        nodes.append(img_node)
                continue

        # 标题
        if s.startswith("## "):
            nodes.append({"tag": "h3", "children": [s[3:].strip("**")]})
        elif s.startswith("**") and s.endswith("**") and len(s) > 4:
            nodes.append({"tag": "h4", "children": [s.strip("*")]})
        else:
            nodes.append({"tag": "p", "children": [s]})

    return nodes


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
    result = json.loads(urllib.request.urlopen(req).read())
    if result.get("ok"):
        return result["result"]["url"]
    raise RuntimeError(f"Telegraph 发布失败: {result.get('error')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: publish-telegraph.py <markdown文件路径>")
        sys.exit(1)

    # 读取 markdown 文件
    fpath = sys.argv[1]
    with open(fpath, "r", encoding="utf-8") as f:
        raw = f.read()

    # 解析元数据
    title_m = re.search(r'^# (.+)', raw, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else "文章"

    author_m = re.search(r'\*\*作者\*\*: (.+)', raw)
    author = author_m.group(1).strip() if author_m else ""

    link_m = re.search(r'\*\*链接\*\*: (.+)', raw)
    link = link_m.group(1).strip() if link_m else ""

    # 提取正文（--- 之后）
    parts = raw.split("---", 1)
    body = parts[1].strip() if len(parts) > 1 else raw

    # 读取 token
    token_path = os.path.expanduser("~/.hermes/telegraph_token")
    if not os.path.exists(token_path):
        print("❌ 未找到 Telegraph token，请先创建: ~/.hermes/telegraph_token")
        sys.exit(1)
    with open(token_path) as f:
        token = f.read().strip()

    # 发布
    print(f"📤 发布中: {title}")
    url = publish(title, author, link, body, token)
    print(f"✅ {url}")
