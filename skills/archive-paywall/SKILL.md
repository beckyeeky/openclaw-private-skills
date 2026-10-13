---
name: archive-paywall
description: "抓取 paywall/CF 阻挡的外语文章（英语媒体为主）：自动去 archive.is/archive.today 找存档，无存档则触发保存并轮询，提取全文转 Markdown 存入 Workspace。当用户发来被付费墙、Cloudflare、地区限制挡住的新闻文章链接（FT/WSJ/NYT/Economist/Bloomberg/Guardian 等），或说'抓存档''读不到''paywall''帮我存档'时触发。archive.is 反爬可能对 curl 返回 429（随 IP/频率变化，并非必然），查询与保存一律走 browser_use。"
---

# Archive.is Paywall 抓取

核心流程：**规范化 URL → browser_use 查 archive.is 最新存档 → 核对命中（URL + 正文）→ 未命中则尝试触发保存并轮询 → Markdown 存 Workspace**。

## 站点判断

**是否可能 paywall**：先查 `references/paywall-sites.txt`（595 个已知付费墙域名，来自 bypass-paywalls-clean 社区清单）——匹配说明大概率有墙，直接走存档流程；不匹配但页面提示订阅/登录墙时同样处理。按媒体名分组版见 `references/paywall-sites-named.md`。

清单来源项目（都维护完整站点列表，清单过期时可重新抓取）：
- 主清单：`csns1/bypass-paywalls-chrome-clean-magnolia1234`（GitHub 镜像，文件 `sites.js` 是 JS 对象，用 node vm 解析）
- 原版 iamadamdev/bypass-paywalls-chrome 已被 DMCA 封禁（2024-08），不要用
- Tampermonkey 版参考：`LegeBeker/bypass-paywalls-tampermonkey`

## 第一步：规范化 URL（对应手动 bookmarklet 逻辑）

用户手动 bookmarklet 是**丢 query** 的：

```javascript
javascript:window.location.href="http://archive.is/newest/"+window.location.href.split('?')[0];
```

自动化时**不要照抄这种"整条 query 全剥"的做法**：archive.is 的 `newest/` 匹配对完整 URL 敏感，剥掉决定文章身份的参数会命中到错误的快照或直接 404。规范化规则：

- **去掉末尾 `#锚点`**（fragment 不参与服务端匹配）。
- **只去掉明确的跟踪/分享参数**：`utm_*`、`fbclid`、`gclid`、`igshid`、`__twitter_impression`、`shareId`/`cmpid` 等平台跟踪标记。
- **保留其余 query**：`?id=`、`?story=`、`?article=`、`?page=`、`?output=`、`?ref=` 等在具体站点上可能是文章身份的一部分，一律保留。
- 同时准备两个 URL：
  - `original_url`：用户给的完整 URL（原样保留，用于溯源标注）。
  - `clean_url`：去掉 fragment 与跟踪参数后的 URL（用于查询）。
- 若用 `clean_url` 查不到匹配，可再用 `original_url` 试一次；**不要**为了"跑通"而反复剥参数。

## 第二步：查存档（用 browser_use；curl 可能被 429）

```text
browser_use navigate → https://archive.is/newest/{clean_url}
```

**命中判定需结合存档页面标识的原始 URL 与正文，title 只能作辅助。** 标题变化不足以证明匹配成功；异常跳转、错误页或非文章快照均须排除。

### 短 ID（短码）存档 URL

如果用户直接给的是短码存档链接（例如 `https://archive.is/AbCdE`），直接打开；短码可能保留在地址栏，也可能跳转到带时间戳的地址。通过存档页显示的原始 URL、来源链接或页面元数据识别目标，再核对正文；不能仅因没有时间戳 URL 判为未命中。

### 最终 URL 核对

- **命中**：从最终地址（如带时间戳的存档 URL）或存档页的原始 URL 标识识别目标；核对主机、路径和决定文章身份的 query。主机别名、规范路径或查询参数变化只有在页面 canonical、实际跳转或正文证据支持时才接受，不默认将 `www.` / `m.` 视为等价。
- **未命中**：
  - 最终 URL 仍停留在 `/newest/…`；
  - 或返回的存档 URL 内嵌的原始 URL 主机名/路径与查询目标**不一致**（说明回退到了别的快照）；
  - 或最终是 404 / 错误页。
- 注意：主机名一致是必要条件，但**不够**——还要做下面的正文核对。

### 正文核对（提取前必做）

命中 URL 形态后，先看页面内容再决定是否提取：

- 正文与目标文章一致（标题、导语、正文语言与目标站点相符），不是另一个域名的注册页/广告壳/首页快照。
- 不是错误页：404、`No results`、`You may want to archive this url`、`Server Error`。
- 不是挑战/验证页：captcha、Cloudflare（`Just a moment`、`Verify you are human`）。
- 任一不满足 → 判为**未命中**，不要输出成 Markdown，也不要报告为成功。

## 第三步：触发保存 + 轮询

存档不存在时，优先用 `?run=1` 参数直接请求保存（比在页面上找按钮可靠）：

```text
browser_use navigate → https://archive.is/?run=1&url={percent_encode(clean_url)}
```

`url` 参数用**规范化后**的 `clean_url`，不要再把有效 query 剥掉。

**保存按钮只在页面上确实存在保存表单时才点**：仅当能看到一个带 URL 输入框 + 提交按钮（`Save`/`保存`）的保存表单时才点击它作为兜底。找不到这样的表单就不要臆造、也不要点无关按钮——例如 archive.is 搜索结果页只有 `action="https://archive.is/search/"` 的**搜索框**，无存档的 404 页通常也只有搜索框/"You may want to archive this url" 提示，这些都不是保存入口。

保存会进入 archive.is 的排队队列（通常 30 秒～数分钟，也可能延迟更久、被丢弃或直接失败），用 **delay 链轮询**：

1. `delay 60`（不占 shell，等待保存）
2. `browser_use navigate → https://archive.is/newest/{clean_url}`
3. 按第二步的 **URL + 正文核对**判定是否命中
4. 未命中 → 重复 `delay 60` + 重查，**最多 5 轮（约 5 分钟）**

轮询超时仍未命中：如实告知用户"已提交保存请求，当前仍未见快照"。**不要承诺稍后一定会完成**——队列可能延迟、失败或被丢弃。可以建议用户稍后重发链接（届时若已有快照会直接命中），或给出手动 bookmarklet 让用户自行重试。

## 第四步：提取正文 → 存 Markdown

命中（且正文核对通过）后：

```text
browser_use get_readable
```

- 单次 get_readable 上限 15000 字符；长文不够时 `scroll` + 再次 get_text 补充
- 评论/侧栏混在正文里，提取后清理导航、分享按钮等噪音
- 存 `/var/minis/workspace/{slug}.md`，头部格式：

```markdown
# 文章标题

**作者**: xxx
**来源**: 媒体名 (域名)
**原文**: <原始 URL>
**存档**: <archive.is 存档 URL>
**抓取时间**: YYYY-MM-DD HH:MM

---

正文...
```

- 回复用户：[文件名](minis://workspace/{slug}.md) 链接 + 内容要点速览

## 第五步：镜像域名（主域名失败时依次尝试）

archive.is 同服务多镜像，URL 格式完全一致（含短码形态），换前缀即可：

```text
https://archive.is/newest/{clean_url}
https://archive.today/newest/{clean_url}
https://archive.ph/newest/{clean_url}
https://archive.li/newest/{clean_url}
https://archive.md/newest/{clean_url}
```

## 常见问题

| 现象 | 处理 |
|---|---|
| curl 返回 429 | **可能**发生（随 IP/频率变化，并非恒真）；反正一律走 browser_use |
| 页面打开是保存表单 | 说明无存档，执行第三步 |
| `newest/` 跳到不相关快照 | 最终 URL 内嵌的原始 URL 主机/路径与目标不符，判为未命中，不要提取 |
| 存档页 title 不是文章标题 | 正常，命中判定不看 title，只核对最终 URL + 正文 |
| 保存后仍未见快照 | 仍在排队或已失败；delay 60 轮询，上限 5 轮，不要承诺必然完成 |
| 原站 CF 阻挡 | 不影响，读存档快照即可 |
| 存档页是 iframe 包裹 | browser_use 直接可用，正文仍按上述规则核对 |
| 找不到任何存档且保存失败 | 如实告知用户，可给出 archive.ph 提交页让其手动保存 |

## 验证清单

- [ ] `clean_url` 已规范化：去 fragment + 仅去跟踪参数，**保留有效 query**
- [ ] browser_use 导航 `archive.is/newest/{clean_url}`（或短码 URL）
- [ ] **URL 核对**：通过最终地址或存档页标识确认原始 URL；核对主机、路径及文章身份 query，短码保留在地址栏不构成失败
- [ ] **正文核对**：非 404 / `No results` / captcha / CF 挑战页，内容与目标文章一致
- [ ] 命中 → get_readable → 清理噪音 → Markdown 存 workspace
- [ ] 未命中 → `?run=1` 触发保存（或仅当存在真实保存表单时点按钮）→ delay 60 轮询（≤5 轮）→ 命中后提取
- [ ] 回复含 Workspace 链接 + 存档链接 + 要点速览；保存未完成时如实说明，不承诺必然完成
