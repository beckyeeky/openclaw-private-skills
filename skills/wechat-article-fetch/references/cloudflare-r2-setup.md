# WeChat Article Fetch 图片归档与 Cloudflare R2 配置教程

这份教程只做两件事：

1. **每篇文章默认保存一份本地副本**，公众号图片下载到 Markdown 旁边的 `assets/` 目录；
2. **可选把本地图片上传到 Cloudflare R2**，用公开 URL 给 Telegraph 或其他 Markdown 页面引用。

R2 不是必须项。即使 R2 没配好，`--images local` 仍然可以独立工作；启用 R2 时，脚本仍先写本地文件，单张上传失败也不会丢掉本地图片。

---

## 一、默认本地归档（不需要 Cloudflare）

```bash
python3 scripts/fetch-wechat.py \
  "https://mp.weixin.qq.com/s/文章ID" \
  --images local \
  --no-telegraph
```

文件会保存为：

```text
~/.hermes/wechat-articles/
├── 文章标题.md
└── assets/
    └── 文章标题/
        ├── 001-xxxxxxxxxx.jpg
        ├── 002-xxxxxxxxxx.webp
        └── ...
```

Markdown 使用相对路径：

```markdown
![图片说明](assets/文章标题/001-xxxxxxxxxx.jpg)
```

所以 Markdown 和 `assets/` 目录需要一起移动或备份。脚本按图片 URL 的哈希去重；重复运行同一文章时会复用已有文件，不会重复下载。

### 微信图片下载策略

脚本给公众号图片请求附带：

- `Referer: https://mp.weixin.qq.com/` 或原文章 URL；
- iPhone + MicroMessenger User-Agent；
- 失败时自动换 Referer / Safari User-Agent 重试。

下载时会检查图片格式，并默认拒绝超过 20 MiB 的单张文件。临时文件使用 `.part` 后缀，下载完成后才改名，避免中途失败留下“假图片”。

---

## 二、Cloudflare R2 的最低复杂度配置

### 你需要准备什么

- 一个 Cloudflare 账号；
- 一个 R2 bucket；
- 一组只允许访问这个 bucket 的 R2 S3 API 凭据；
- 一个公共访问地址：先用 Cloudflare 的 `r2.dev` 开发地址即可，不必先买域名。

R2 当前 Standard 免费额度（按月）包括：

- 10 GB-month 存储；
- 100 万次 Class A 操作；
- 1000 万次 Class B 操作；
- Internet 出站流量免费。

对公众号文章图片这种小规模个人图床，通常足够入门。免费额度不是“绝对不会扣费”的保证：超过额度、选择 Infrequent Access、或账号产生其他 Cloudflare 付费项目，仍可能计费。建议开通后设置账单提醒，并定期看 R2 Usage。

### 第 1 步：开通 R2

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)；
2. 左侧进入 **Storage & databases → R2**；
3. 点 **Overview**；
4. 第一次使用时按页面提示完成 checkout / 添加 R2 subscription。

这一步通常是“开通订阅”，不是立即付费购买容量。R2 按实际用量月结，免费额度会先抵扣。

### 第 2 步：创建 bucket

1. 在 R2 Overview 点 **Create bucket**；
2. Bucket 名称建议使用：`wechat-images`；
3. Location / Jurisdiction 先保持默认；
4. 选择 **Standard** storage；
5. 创建。

不要在 bucket 根目录放需要保密的文件。之后这个 bucket 会配置成公开读取，上传凭据只给脚本使用。

### 第 3 步：打开一个公共访问地址

先用最简单的 `r2.dev`，不用域名、不用 DNS：

1. 打开 `wechat-images` bucket；
2. 进入 **Settings**；
3. 找到 **Public Development URL**；
4. 点 **Enable**；
5. 在确认框里输入 `allow`；
6. 复制 Cloudflare 给出的地址，例如：

```text
https://pub-xxxxxxxxxxxxxxxx.r2.dev
```

这个地址只用于个人/非生产访问，Cloudflare 会对 `r2.dev` 做速率限制；正是本教程这种低流量个人图床的入门用途。以后如果需要自定义域名和更强缓存，再换 Custom Domain，不需要改变 bucket 或脚本上传方式。

测试地址（对象尚未上传前会 404 是正常的）：

```text
https://pub-xxxxxxxxxxxxxxxx.r2.dev/test.txt
```

### 第 4 步：创建只用于这个 bucket 的 API Token

1. 回到 R2 Overview；
2. 在 Account Details 找到 **API Tokens**，点 **Manage**；
3. 创建一个 **User API token**（如果你的账号权限没有这个选项，再按页面允许的 Account API token 操作）；
4. Permission 选择 **Object Read & Write**；
5. Bucket 范围选择 `wechat-images`，不要选择所有 bucket；
6. 创建；
7. 立即保存显示的两项：
   - Access Key ID；
   - Secret Access Key。

Secret Access Key 只显示一次。不要把它发到聊天、提交 Git、写进 README，也不要写进 `.env` 后提交到仓库。

### 第 5 步：找到 Account ID

在 Cloudflare Dashboard 的 R2 Overview / Account Details 中复制 Account ID。它通常是一串 32 位十六进制字符。

### 第 6 步：配置环境变量

本技能需要以下变量：

```text
CF_R2_ACCOUNT_ID=你的 Account ID
CF_R2_ACCESS_KEY_ID=你的 Access Key ID
CF_R2_SECRET_ACCESS_KEY=你的 Secret Access Key
CF_R2_BUCKET=wechat-images
CF_R2_PUBLIC_BASE_URL=https://pub-xxxxxxxxxxxxxxxx.r2.dev
CF_R2_KEY_PREFIX=wechat
```

在 OpenClaw / Minis 里，建议把它们放到运行环境变量设置，不要提交 `config.yaml`：

[打开环境变量设置](minis://settings/environments)

变量名可以逐个创建。`CF_R2_SECRET_ACCESS_KEY` 的备注建议写成：`Cloudflare R2 upload secret for wechat-article-fetch`。

在普通终端里也可以临时设置（只对当前 shell 有效）：

```bash
export CF_R2_ACCOUNT_ID='...'
export CF_R2_ACCESS_KEY_ID='...'
export CF_R2_SECRET_ACCESS_KEY='...'
export CF_R2_BUCKET='wechat-images'
export CF_R2_PUBLIC_BASE_URL='https://pub-xxxxxxxxxxxxxxxx.r2.dev'
export CF_R2_KEY_PREFIX='wechat'
```

### 第 7 步：上传一篇文章图片

```bash
python3 scripts/fetch-wechat.py \
  "https://mp.weixin.qq.com/s/文章ID" \
  --images r2
```

行为是：

```text
公众号图片
  ├─ 下载到 ~/.hermes/wechat-articles/assets/文章标题/
  └─ 上传到 R2: wechat/文章标题/001-哈希.jpg
```

本地 Markdown 仍然引用 `assets/...`，而 Telegraph 发布版会引用：

```text
https://pub-xxxxxxxxxxxxxxxx.r2.dev/wechat/文章标题/001-哈希.jpg
```

如果某张图上传失败，脚本会打印失败数量，但本地文件仍然保留。R2 模式需要完整配置；缺少变量时会明确列出缺少哪些变量并退出，不会误把私密凭据写入文章。

---

## 三、关于自定义域名

初期**不需要自定义域名**。`r2.dev` 可以先跑通完整链路。

以后想换成：

```text
https://img.example.com
```

需要：

1. 把 `example.com` 添加到同一个 Cloudflare 账号；
2. 在 bucket → Settings → Custom Domains → Add；
3. 输入 `img.example.com`；
4. 让 Cloudflare 自动创建 DNS 记录；
5. 等状态变成 Active；
6. 把 `CF_R2_PUBLIC_BASE_URL` 改成 `https://img.example.com`。

不需要重新上传图片，也不需要重新创建 API Token。

---

## 四、故障排查

### 图片本地保存失败

- 确认原文里的图片 URL 仍是 `https://mmbiz.qpic.cn/...`；
- 确认下载请求没有被网络环境拦截；
- 查看脚本输出的失败数量；
- 文章 Markdown 仍会生成，失败图片会保留原始 URL，方便以后手动补下载。

### R2 上传返回 401 / 403

按顺序检查：

1. Access Key ID 和 Secret Access Key 是否来自 R2 API Token；
2. Token 权限是否为 `Object Read & Write`；
3. Token 是否只勾选了正确的 `wechat-images` bucket；
4. `CF_R2_ACCOUNT_ID` 是否为 R2 Account ID，而不是 Zone ID；
5. bucket 名称是否完全一致。

### R2 图片 URL 404

- 确认 Public Development URL 已经 Enable；
- URL 前缀不要带多余的 `/`；
- 路径应包含 `wechat/...`；
- 上传完成后等待几十秒再测试；
- `r2.dev` 根目录不提供文件列表，直接访问具体对象 URL。

### 账单担忧

- 使用 Standard，不要选 Infrequent Access；
- 不要让网站或脚本无限重试；
- 不要开启公开目录索引；
- 定期查看 R2 Usage / Billing；
- 文章图片控制在合理大小，下载时本技能默认单张上限 20 MiB。

---

## 五、推荐的实际工作方式

先只使用：

```bash
--images local
```

确认几篇文章的本地归档都正常后，再配置 R2，使用：

```bash
--images r2
```

这样即使 Cloudflare 面板、Token 或网络有问题，你仍然拥有完整的本地文章和图片；R2 只是给外部发布提供一份公共副本，而不是唯一存储。
