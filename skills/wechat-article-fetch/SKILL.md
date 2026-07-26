---
name: wechat-article-fetch
description: "Fetch any web article (WeChat, Medium, paywalled, etc.) via curl+defuddle → Markdown → optional Telegra.ph publishing for mobile-friendly reading."
license: MIT
metadata:
  hermes:
    version: 3.0.0
    author: Hermes Agent
    category: media
    tags: [wechat, weixin, article, scraping, curl, defuddle, telegraph, paywall, cloudflare]
    triggers:
      - fetch article
      - wechat article
      - 抓取文章
      - 微信文章
    related_skills: []
---

# 文章抓取 + Telegraph 发布（微信 / 非微信通用）

## 概述

核心流水线：**curl 抓取 HTML → defuddle 智能提取转 Markdown → 可选发布到 Telegra.ph**

**微信文章**: curl 需伪装 MicroMessenger UA 绕过滑块。
**非微信文章**: 用常规浏览器 UA 即可；defuddle + Telegraph 发布流程完全一致。

用户只需发一个文章链接，即可拿到干净的 Markdown 正文 + 手机友好的 Telegraph 可读链接。

## 前置条件

- `curl`（通常已预装）
- `node` + `npm`（通常已预装）
- `defuddle` 全局安装：`npm install -g defuddle`
- `telegraph` Python 包：`pip3 install telegraph`（发布用）
- Telegraph access token 保存在 `~/.hermes/telegraph_token`

## 何时使用

**微信文章**: `https://mp.weixin.qq.com/s/` 开头的链接。
**非微信文章**: 任意网页文章链接（Medium、The Atlantic、arxiv 等），需要提取正文 + 保存 + 可选发布 Telegraph。

## 差异备忘

| 环节 | 微信文章 | 非微信文章 |
|---|---|---|
| curl UA | 伪装 MicroMessenger/iPhone/zh_CN | 常规浏览器 UA (Chrome/Firefox) |
| URL 校验 | 需 `mp.weixin.qq.com/s/` | 无需校验，直接抓取 |
| 保存目录 | `~/.hermes/wechat-articles/` | `~/.hermes/articles/` |
| 来源标注 | "微信公众号" | 取域名或文章 site 字段 |
| skip_set | 微信特有广告行（可跳过） | 通常无需过滤 |

## 首次设置

### Telegraph 账号（只需一次）

```bash
curl -s "https://api.telegra.ph/createAccount?short_name=BeckChao&author_name=BeckChao" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['access_token'])" \
  > ~/.hermes/telegraph_token
```

Token 保存后永久可用，后续所有文章共用。

## 操作流程

### Step 1 — curl 抓取原始 HTML

```bash
curl -sL \
  -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.34(0x16082222) NetType/WIFI Language/zh_CN" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9" \
  -H "Accept-Language: zh-CN,zh;q=0.9" \
  "<URL>" -o /tmp/wx_article.html
```

关键埋点：`MicroMessenger/8.0.34`、`iPhone` 平台、`zh_CN` 语言。

### Step 2 — defuddle 智能提取 + 转 Markdown

```bash
npx defuddle parse /tmp/wx_article.html -m -j
```

输出示例（JSON）：
```json
{
  "title": "文章标题",
  "author": "作者",
  "description": "摘要",
  "content": "## Markdown 正文...",
  "wordCount": 1531,
  "published": "2025-01-01",
  "domain": "mp.weixin.qq.com"
}
```

### Step 3 — 保存为 Markdown 文件

保存路径：`~/.hermes/wechat-articles/<title-slug>.md`

格式：
```markdown
# 文章标题

**作者**: xxx
**来源**: 微信公众号
**链接**: <URL>
**抓取时间**: YYYY-MM-DD HH:MM
**字数**: 1531

---

## Markdown 正文...
```

### Step 4 — 发布到 Telegra.ph（可选）

将 Markdown 正文转换为 Telegraph 的 Node 格式（JSON 数组），POST 到 `https://api.telegra.ph/createPage`。

核心转换逻辑（Python）：

```python
import json, urllib.request, re

def publish_to_telegraph(title, author, author_url, content_md, token):
    """将微信文章发布到 Telegra.ph，返回可读链接"""
    nodes = []
    skip_set = {"李姝 李姝", "在小说阅读器读本章", "去阅读",
                "微信扫一扫", "使用小程序", "继续滑动看下一个",
                "潇湘晨报", "向上滑动看下一个"}
    for line in content_md.split("\n"):
        s = line.strip()
        if not s or s in skip_set:
            continue
        # 图片行
        img = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', s)
        if img:
            pure = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', '', s).strip()
            if not pure or pure in {"△", "▲", "图：", "—"} or len(pure) < 5:
                for alt, src in img:
                    n = {"tag": "img", "attrs": {"src": src}}
                    if alt:
                        n = {"tag": "figure", "children": [n, {"tag": "figcaption", "children": [alt]}]}
                    nodes.append(n)
                continue
        # 标题行
        if s.startswith("## "):
            nodes.append({"tag": "h3", "children": [s[3:].strip("**")]})
        elif s.startswith("**") and s.endswith("**") and len(s) > 4:
            nodes.append({"tag": "h4", "children": [s.strip("*")]})
        else:
            nodes.append({"tag": "p", "children": [s]})

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
```

## Hermes 自动执行流程

当用户发来文章链接时，自动执行完整流水线：

### 微信文章流程

1. **检测 URL**: 确认 `mp.weixin.qq.com/s/` 开头
2. **curl 抓取**（MicroMessenger UA）→ `/tmp/wx_article.html`
3. **defuddle 解析** → 提取 title/author/content/wordCount
4. **保存 Markdown** → `~/.hermes/wechat-articles/<slug>.md`
5. **发布 Telegraph** → 调用 API 发布，返回 `https://telegra.ph/...` 链接
6. **回复用户**: 标题 + 作者 + 字数 + 本地路径 + Telegraph 链接

### 非微信文章流程

**⚠️ 重要：需要保留图片时，跳过 web_extract，直接走 curl + defuddle。**

`web_extract` 会剥离所有图片引用（BBC、新闻网站等），适合纯文字摘要场景。如果用户要存档、发布 Telegraph、或保留原版面，`web_extract` 的输出不可用——图片全丢。

1. **判断是否需保留图片**：
   - 只需文字摘要 → `web_extract` 最快
   - 需保留图片 / 发布 Telegraph → 直接跳 step 2，走 curl + defuddle
2. **curl 常规 UA 抓取** → `/tmp/article.html`
3. **defuddle 解析** → `npx defuddle parse /tmp/article.html -m -j`，提取 title/author/content。若输出为空，说明页面是 JS 渲染 SPA，跳到下一步
4. **浏览器 fallback**（defuddle 无输出时）→ 对重度 JS 渲染的 SPA（Gemini 分享链接、React/Vue 单页应用等），curl 只能拿到骨架 HTML。改用 `browser_navigate` + 立即截图 `browser_vision(annotate=true, question="提取全部可见文字")`。首次加载后尽快截图——部分 SPA 有 bot 检测，滚动或延迟后内容会清空/限流。annotations 中的元素 label（如 e19 = "You said ..."）可补充截图未覆盖的长文本。
5. **保存 Markdown** → `~/.hermes/articles/<slug>.md`
6. **发布 Telegraph**（可选）→ 同上
7. **回复用户**

注意：非微信文章无法直接用 `fetch-wechat.py` 脚本（硬校验 `mp.weixin.qq.com/s/`）。用 Hermes 走手动流程或临时脚本。

生成的 Telegraph 链接会自动用微信原文链接作为 author_url，方便溯源。

## 完整 Python 脚本

见 scripts/fetch-wechat.py（基础抓取保存）和 scripts/publish-telegraph.py（Telegraph 发布）。

## 常见问题

### 微信文章常见问题

1. **滑块验证码** — 更换 UA 中微信版本号（`MicroMessenger/8.0.52`）或 iPhone 机型。保持 `MicroMessenger/` + `iPhone` + `zh_CN` 三个关键要素。

2. **npx: command not found** — `npm install -g defuddle`

3. **defuddle 输出为空** — 检查 curl 是否返回有效 HTML；部分文章有访问权限限制。

4. **频次限制** — 短时间同一公众号抓取多篇可能触发微信临时封 IP。

5. **图片防盗链** — Defuddle 保留图片 URL，但微信图床有防盗链。Telegraph 页面上图片通常可正常显示（微信白名单了 Telegra.ph 的 Referer）。

6. **Telegraph 内容格式** — 只支持 h2-h4 / p / img / figure / ul/ol + li。不支持 `<table>`、`<code>` 等复杂标签。正文中的表格会被降级为纯文本段落。

7. **Telegraph token 丢失** — 重新 `curl` 调用 `createAccount` 生成新 token。旧页面不受影响，但新页面会用新账号发布。

8. **CONTENT_TOO_BIG** — Telegraph API 对 content JSON 有 ~64KB 大小限制（约 10,000 字中文）。超长文章会报此错误。解决方案：截取正文主要部分（去掉附录/编者按/Claude 回应等非核心内容），或将文章拆为两部分分别发布 `(1/2)` / `(2/2)`。

### 非微信文章常见问题

1. **Cloudflare 防护** — 大量网站（The Atlantic、Medium、New Yorker 等）启用 Cloudflare 机器人检测。腾讯云轻量云（中国大陆）的 IP 段可能被直接硬 403 拦截（无验证挑战可点）。解决方案：找 archive.md 快照、textise 工具、或用用户提供的其他渠道链接。

2. **Paywall** — 部分新闻网站有付费墙。优先尝试 `12ft.io`/`outline.com`/`textise.iitty.com` 等 proxy 服务，但这些服务在中国大陆 VPS 也可能被 DNS 封锁。备选：尝试浏览器工具（`browser_navigate`）模拟真实用户。

3. **DNS 不可达** — 中国大陆 VPS 对部分境外域名（archive.md、textise 等）DNS 解析失败。可用 `dig @8.8.8.8` 解析 IP，再用 `curl --connect-to` 直连。

4. **JS 渲染页面（Gemini 分享链接等）** — 使用 Shadow DOM / Web Components 的 SPA（如 Gemini 分享页面），curl 只能拿到空骨架。改走浏览器 fallback（见流程图 step 4）。关键埋点：首次 `browser_navigate` 后立即截图，不要滚动——部分页面在交互后触发 bot 检测并清空内容。annotations 中的元素 labels 能捕获 accessibility tree 不可见的长文本，是截图的重要补充源。详见 `references/js-rendered-pages.md`。

## 验证清单

### 微信文章

- [ ] URL 以 `https://mp.weixin.qq.com/s/` 开头
- [ ] curl 返回 HTTP 200（MicroMessenger UA）
- [ ] defuddle 成功解析出 title + content
- [ ] 文件保存到 `~/.hermes/wechat-articles/`
- [ ] （可选）Telegraph 发布成功，返回可访问链接
- [ ] 回复中包含标题/作者/字数/本地路径/Telegraph 链接

### 非微信文章

- [ ] 判断：纯文字摘要走 web_extract，需保留图片/发布 Telegraph 走 curl+defuddle
- [ ] curl：常规浏览器 UA 抓取 → `/tmp/article.html`
- [ ] defuddle 成功解析 → 保存 markdown；若输出为空，走浏览器 fallback
- [ ] 浏览器 fallback（可选）：`browser_navigate` + `browser_vision(annotate=true)` 提取
- [ ] 文件保存到 `~/.hermes/articles/`
- [ ] 来源标注为域名或 site 字段
- [ ] （可选）Telegraph 发布成功，注意 CONTENT_TOO_BIG 限制（>~64KB 需截断或拆分）
