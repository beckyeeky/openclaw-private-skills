---
name: wechat-article-fetch
description: "Fetch web articles into durable Markdown archives, download embedded images locally with anti-hotlink handling, and optionally publish image copies to Cloudflare R2 for external reading pages. Use when the user asks to fetch, archive, preserve images from, or publish a WeChat or other web article."
license: MIT
metadata:
  hermes:
    version: 4.0.0
    author: Hermes Agent
    category: media
    tags: [wechat, weixin, article, scraping, curl, defuddle, telegraph, cloudflare, r2, images]
    triggers:
      - fetch article
      - wechat article
      - 抓取文章
      - 微信文章
      - 保存图片
      - 图片归档
    related_skills: []
---

# 文章抓取 + 本地图片归档 + Cloudflare R2

## 核心原则

这项技能采用**本地优先、R2 可选**的架构：

- 默认下载正文里的远程图片，并把它们保存到文章 Markdown 旁边的 `assets/<slug>/`；
- Markdown 使用相对图片路径，因此文章和 `assets/` 目录一起移动即可离线阅读；
- R2 只是对外发布用的公共镜像，不是唯一存储；
- 即使 R2 或外部发布失败，也必须保留本地 Markdown 和已经下载的图片；
- 禁止把 GitHub 私有 raw URL、带 token 的下载 URL、R2 S3 API endpoint 或任何凭据写入 Markdown/Telegraph。

公众号图片的防盗链处理方式是：**带文章/微信 Referer 下载一次，然后自己保存**。不要把原始 `mmbiz.qpic.cn` URL 当作长期图床。

## 入口

脚本必须通过 `{baseDir}` 解析，不能假设固定 checkout 路径：

```bash
# 默认：抓取文章 + 保存本地图片 + 保存本地 Markdown
python3 {baseDir}/scripts/fetch-wechat.py \
  "https://mp.weixin.qq.com/s/XXXXX" --images local

# 本地保存后上传 R2；Telegraph 发布版使用 R2 公共图片 URL
python3 {baseDir}/scripts/fetch-wechat.py \
  "https://mp.weixin.qq.com/s/XXXXX" --images r2

# 只做本地归档，不尝试 Telegraph
python3 {baseDir}/scripts/fetch-wechat.py \
  "https://mp.weixin.qq.com/s/XXXXX" --images local --no-telegraph
```

`--images local` 是默认值。`--images r2` 只有在 R2 环境变量已配置且确实需要外部图片 URL 时才使用。

## 本地归档格式

默认输出目录：

```text
~/.hermes/wechat-articles/
├── 文章标题.md
└── assets/
    └── 文章标题/
        ├── 001-<source-url-hash>.jpg
        ├── 002-<source-url-hash>.webp
        └── ...
```

Markdown 位于 `~/.hermes/wechat-articles/` 根目录，因此相对引用：

```markdown
![图片说明](assets/文章标题/001-xxxxxxxxxx.jpg)
```

文件名包含顺序号和源 URL 哈希：

- 同一文章重复抓取时复用已有图片，不重复下载；
- 不使用不稳定的远程图片文件名；
- 下载先写成 `.part`，校验通过后原子改名；
- 默认单图上限 20 MiB；
- 失败图片保留原远程 URL，正文和其他图片继续处理。

## 抓取与防盗链流程

### 微信文章

1. 检查 URL 的 host 是 `mp.weixin.qq.com`，path 以 `/s/` 开头；
2. 用 curl + iPhone/MicroMessenger/zh_CN User-Agent 抓取 HTML；
3. 用 `npx defuddle parse ... -m -j` 提取 Markdown；
4. 提取 Markdown 图片；
5. 图片请求依次尝试文章 URL 和 `https://mp.weixin.qq.com/` Referer，并在失败时切换移动 Safari UA；
6. 检查 Content-Type / magic bytes / 文件大小；
7. 写入 `assets/<slug>/`，把成功图片改成相对路径；
8. 生成本地 Markdown；
9. 如使用 `--images r2`，再上传已落盘的本地文件；
10. 有 Telegraph token 时才尝试发布 Telegraph。

### 普通网页

用户只要文字摘要时可以使用纯文本网页抽取；只要用户要求保留图片、归档或发布，就必须使用 curl + defuddle，并执行同样的本地图片保存和相对路径改写流程。JS SPA 在 curl 没有正文时才使用浏览器 fallback。

## Cloudflare R2 配置

详细的低复杂度操作教程在：

```text
{baseDir}/references/cloudflare-r2-setup.md
```

教程优先使用 Cloudflare 管理的 `r2.dev` 公共开发 URL，不要求一开始配置域名。以后换自定义域名只需修改 `CF_R2_PUBLIC_BASE_URL`。

### 环境变量

必需：

```text
CF_R2_ACCOUNT_ID
CF_R2_ACCESS_KEY_ID
CF_R2_SECRET_ACCESS_KEY
CF_R2_BUCKET
CF_R2_PUBLIC_BASE_URL
```

可选：

```text
CF_R2_KEY_PREFIX=wechat
```

推荐的 R2 Token 权限是只针对目标 bucket 的 **Object Read & Write**。`CF_R2_PUBLIC_BASE_URL` 必须是公共 `r2.dev` 地址或自定义域名，例如：

```text
https://pub-xxxxxxxxxxxxxxxx.r2.dev
```

不能填写：

```text
https://<account-id>.r2.cloudflarestorage.com
```

后者是上传用的 S3 API endpoint，不是读图用的公开地址。

### R2 上传规则

- 使用 Python 标准库实现 AWS Signature Version 4，不额外依赖 boto3；
- key 默认形如 `wechat/<article-slug>/<filename>`；
- 上传失败按图片逐张记录，不能撤销本地文件；
- Telegraph 发布版只使用公共 R2 URL，不使用本地相对路径；
- 凭据只从环境变量读取，不打印值，不写入生成文件。

## Telegraph

Telegraph 页面只能引用公网 HTTPS 图片 URL，不能引用 `assets/...` 相对路径。

- `--images r2`：本地保存完成后，Telegraph 发布版使用 R2 公共 URL；
- `--images local`：本地归档完整，但 Telegraph 发布版暂时保留公众号原 URL，图片显示取决于 Telegraph/微信图床的兼容性；
- 不把 Telegraph `/upload` 当作可靠依赖；当前主路径是 R2 公共 URL；
- Telegraph 的 `createPage` 内容仍受大小限制，超长文章需要截断或拆分；
- `scripts/publish-telegraph.py` 用于已有 Markdown，已有图片 URL 必须是公网 HTTPS URL。

## 自动执行规则

当用户发来微信公众号链接并要求抓取、保存、阅读或保留图片时：

1. 默认用本地优先流程，不等待用户额外确认；
2. 默认选择 `--images local`；
3. 如果用户已经配置 R2，且明确要求外部发布/公共图片 URL，选择 `--images r2`；
4. R2 配置缺失时，不反复尝试，也不要求用户粘贴 secret 到聊天；指出缺失的环境变量，并给出环境变量设置入口；
5. 结束时报告标题、作者、字数、本地 Markdown 路径、图片发现/本地保存/R2 上传/失败数量和外部链接；
6. 不承诺 Telegraph 图片一定可用，失败时仍交付本地归档。

## 依赖与文件

- `curl`、`node`、`npm`、`defuddle`；
- `scripts/fetch-wechat.py`：抓取、解析、本地归档、可选 R2、可选 Telegraph；
- `scripts/image_assets.py`：图片下载、格式识别、缓存、Markdown 改写、R2 SigV4 客户端；
- `scripts/publish-telegraph.py`：把已有公网图片 Markdown 发布到 Telegraph；
- `references/cloudflare-r2-setup.md`：R2 面板逐步教程；
- `references/telegraph-api.md`：Telegraph API 约束；
- `references/js-rendered-pages.md`：JS 页面 fallback。

## 验证清单

在技能目录执行：

```bash
python3 -m py_compile scripts/fetch-wechat.py scripts/image_assets.py scripts/publish-telegraph.py
PYTHONPATH=scripts python3 scripts/test_image_assets.py
python3 scripts/fetch-wechat.py --help
```

发布前还要执行：

```bash
npx skills@latest add . --list
```

`npx skills@latest add . --list` 只做 discovery 检查，不要用它修改用户已安装的技能。

## 常见故障

- **公众号图片 403/非图片响应**：先确认文章 URL 可访问；脚本已经尝试两种 Referer 和两种移动 UA。保留失败 URL，后续可补下载。
- **R2 401/403**：检查 token 类型、bucket 范围、Object Read & Write 权限，以及 Account ID（不是 Zone ID）。
- **R2 URL 404**：确认已开启 Public Development URL，访问的是具体对象路径，且 URL 前缀没有多余斜杠。
- **公开 bucket 根目录空白**：正常，R2 不提供根目录列表；直接访问具体对象 URL。
- **账单担忧**：使用 Standard，不开 Infrequent Access；不要让脚本无限重试；定期检查 R2 Usage/Billing。免费额度以 Cloudflare 当前价格页为准。
