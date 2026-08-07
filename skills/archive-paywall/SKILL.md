---
name: archive-paywall
description: "抓取 paywall/CF 阻挡的外语文章（英语媒体为主）：自动去 archive.is/archive.today 找存档，无存档则触发保存并轮询，提取全文转 Markdown 存入 Workspace。当用户发来被付费墙、Cloudflare、地区限制挡住的新闻文章链接（FT/WSJ/NYT/Economist/Bloomberg/Guardian 等），或说'抓存档''读不到''paywall''帮我存档'时触发。archive.is 反爬会 429 curl，必须用浏览器。"
---

# Archive.is Paywall 抓取

核心流程：**清理 URL → browser_use 查 archive.is 最新存档 → 命中则提取；未命中则触发保存并轮询 → Markdown 存 Workspace**。

## 站点判断

**是否可能 paywall**：先查 `references/paywall-sites.txt`（595 个已知付费墙域名，来自 bypass-paywalls-clean 社区清单）——匹配说明大概率有墙，直接走存档流程；不匹配但页面提示订阅/登录墙时同样处理。按媒体名分组版见 `references/paywall-sites-named.md`。

清单来源项目（都维护完整站点列表，清单过期时可重新抓取）：
- 主清单：`csns1/bypass-paywalls-chrome-clean-magnolia1234`（GitHub 镜像，文件 `sites.js` 是 JS 对象，用 node vm 解析）
- 原版 iamadamdev/bypass-paywalls-chrome 已被 DMCA 封禁（2024-08），不要用
- Tampermonkey 版参考：`LegeBeker/bypass-paywalls-tampermonkey`

## 第一步：清理 URL（对应手动 bookmarklet 逻辑）

```javascript
// 用户手动 bookmarklet：
javascript:window.location.href="http://archive.is/newest/"+window.location.href.split('?')[0];
// 即：去掉 query string（tracking 参数），拼上 newest/ 前缀
```

自动化时同样处理：
- `clean_url = url.split('?')[0]`（去掉全部 query 参数，含 tracking）
- 同时去掉末尾 `#锚点`
- 保留原始完整 URL 用于溯源标注

## 第二步：查存档（必须用 browser_use，curl 会被 429）

```text
browser_use navigate → https://archive.is/newest/{clean_url}
```

判断结果：
- **页面 title 变成文章标题**（不再是 archive.is/archive.today）→ 存档命中，直接进第四步
- **页面仍是 archive.is 自身标题 / 显示保存表单** → 无存档，走第三步
- **主域名不可达或报错** → 换镜像域名重试（见第五步）

## 第三步：触发保存 + 轮询

存档不存在时，优先用 `?run=1` 参数直接请求保存（比点按钮可靠）：

```text
browser_use navigate → https://archive.is/?run=1&url={clean_url}
```

或点击页面上保存按钮（表单自动带出 URL，点 `Save`/`保存`）。

保存会排队（30 秒～数分钟不等），用 **delay 链轮询**：

1. `delay 60`（不占 shell，等待保存）
2. `browser_use navigate → https://archive.is/newest/{clean_url}`
3. title 变为文章标题 → 命中，进第四步
4. 未命中 → 重复 delay 60 + 重查，**最多 5 轮（约 5 分钟）**

轮询超时仍未命中：诚实告知用户保存仍在后台排队，稍后重发链接即可直接命中；或给出手动 bookmarklet 让用户自己刷新。

## 第四步：提取正文 → 存 Markdown

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

archive.is 同服务多镜像，URL 格式完全一致，换前缀即可：

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
| curl 返回 429 | 正常，archive.is 反爬；一律走 browser_use |
| 页面打开是保存表单 | 说明无存档，执行第三步 |
| 保存后 title 不变 | 队列中，delay 60 轮询，上限 5 轮 |
| 原站 CF 阻挡 | 不影响，读存档快照即可 |
| 存档页是 iframe 包裹 | browser_use 直接可用，title/正文均正常 |
| 找不到任何存档且保存失败 | 告知用户，可用 archive.ph 提交页手动保存 |

## 验证清单

- [ ] clean_url 已去 query + 锚点
- [ ] browser_use 导航 archive.is/newest/{clean_url}
- [ ] 命中 → get_readable → 清理噪音 → Markdown 存 workspace
- [ ] 未命中 → ?run=1 触发保存 → delay 60 轮询（≤5 轮）→ 命中后提取
- [ ] 回复含 Workspace 链接 + 存档链接 + 要点速览
