#!/usr/bin/env python3
"""抓取微信公众号文章 → Markdown + Telegraph
用法: python3 fetch-wechat.py <mp.weixin.qq.com/s/...>
"""

import subprocess, json, re, os, sys, urllib.request, tempfile
from datetime import datetime
from urllib.parse import urlparse


def fetch(url: str) -> dict:
    """curl + defuddle 抓取微信文章"""
    parsed = urlparse(url)
    if parsed.netloc != "mp.weixin.qq.com" or not parsed.path.startswith("/s/"):
        raise ValueError(f"不是有效的微信文章链接: {url}")

    ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
          "MicroMessenger/8.0.34(0x16082222) NetType/WIFI Language/zh_CN")

    print("🌐 抓取中...", file=sys.stderr)
    tmp_html = tempfile.mktemp(suffix=".html")
    subprocess.run(["curl", "-sL", "--fail", "--show-error",
        "--connect-timeout", "15", "--max-time", "30",
        "-H", f"User-Agent: {ua}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "-H", "Accept-Language: zh-CN,zh;q=0.9",
        url, "-o", tmp_html], check=True)

    print("📝 解析中...", file=sys.stderr)
    r = subprocess.run(["npx", "--no-install", "defuddle", "parse", tmp_html, "-m", "-j"],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def save_markdown(url: str, data: dict) -> str:
    """保存 Markdown 到本地"""
    out_dir = os.path.expanduser("~/.hermes/wechat-articles")
    os.makedirs(out_dir, exist_ok=True)
    title = data.get("title", "untitled")
    slug = re.sub(r'[^\w\u4e00-\u9fff_-]', '-', title)
    slug = re.sub(r'-+', '-', slug).strip('-') or "article"
    fpath = os.path.join(out_dir, f"{slug}.md")

    md = f"""# {data.get('title', '')}

**作者**: {data.get('author', '') or '-'}
**来源**: 微信公众号
**链接**: {url}
**抓取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**字数**: {data.get('wordCount', '')}

---

{data.get('content', '')}
"""
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(md)
    return fpath


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
    result = json.loads(urllib.request.urlopen(req).read())
    if result.get("ok"):
        return result["result"]["url"]
    raise RuntimeError(f"Telegraph 发布失败: {result.get('error')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: fetch-wechat.py <mp.weixin.qq.com/s/...>", file=sys.stderr)
        sys.exit(1)

    wx_url = sys.argv[1]

    # Step 1-2: 抓取 + 解析
    data = fetch(wx_url)

    # Step 3: 保存到本地
    fpath = save_markdown(wx_url, data)

    title = data.get("title", "未命名文章")
    print(f"\n✅ {title}")
    print(f"📁 {fpath}")
    if data.get('author'):
        print(f"✍️  {data['author']}")
    if data.get('wordCount'):
        print(f"🔢 {data['wordCount']} 字")

    # Step 4: 发布 Telegraph
    token_path = os.path.expanduser("~/.hermes/telegraph_token")
    if os.path.exists(token_path):
        print("📤 发布到 Telegraph...", file=sys.stderr)
        with open(token_path) as f:
            token = f.read().strip()
        try:
            teleg_url = publish_telegraph(
                title,
                data.get("author", ""),
                wx_url,
                data.get("content", ""),
                token
            )
            print(f"🔗 {teleg_url}")
        except Exception as e:
            print(f"⚠️  Telegraph 发布失败: {e}", file=sys.stderr)
    else:
        print("💡 提示: 创建 ~/.hermes/telegraph_token 可自动发布到 Telegraph")
