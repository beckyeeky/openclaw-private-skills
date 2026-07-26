---
name: loon-plugin
description: >-
  Use when building, debugging, packaging, or publishing Loon plugins (.plugin/.lpx):
  header metadata, [Argument]/[Script]/[MitM]/[URL Rewrite]/[Rule], http-request/response
  scripts, raw hosting pitfalls, and patterns from 可莉/社区 + TabulaBili-Loon. Not for Surge/QX-only modules unless converting.
license: MIT
metadata:
  hermes:
    version: 1.0.0
    author: beckyeeky / Hermes
    platforms: [linux, macos, windows]
    tags: [loon, plugin, mitm, ios, bilibili, proxy, rewrite]
    related_skills: [github, hermes-agent-skill-authoring]
---

# Loon Plugin Engineering

## Overview

Ship **installable Loon plugins** that rewrite traffic (reject / URL rewrite / request scrub / response JSON patch). Optimize for process predictability: correct section layout, MitM hostnames, non-colliding scripts, and **raw install URLs that actually 200**.

Primary golden sample in this environment: `/root/repos/TabulaBili-Loon` (public: `beckyeeky/TabulaBili-Loon`).

Reference libraries (read for patterns; respect their licenses / disclaimers):

| Source | What to take |
|--------|----------------|
| [hub.kelee.one](https://hub.kelee.one/) / [luestr/ProxyResource](https://github.com/luestr/ProxyResource) | 可莉插件中心 UX、安装深链 `loon://import?plugin=`、App 向 MitM、`.lpx` 托管习惯 |
| [deezertidal/private](https://github.com/deezertidal/private) | 根目录海量 `*.plugin` 真机格式、`[URL Rewrite] - reject`、`[Script]`/`[MITM]` 写法 |
| TabulaBili-Loon `AGENTS.md` | Argument、request 清洗 + response 探针、GitHub raw `plugin/*.plugin` 404 坑 |

## When to Use

- 用户要做/改 **Loon 插件**、`.plugin` / `.lpx`、远程 `script-path`
- 调试「插件无效」：未 MitM、只匹配 Web 未匹配 App、脚本互抢 `$done`
- 发布到 GitHub raw / jsDelivr / `loon://import`
- 把 Chrome 扩展/Surge 模块 **降级** 到 Loon 网络层能力

**Don't use for:** 纯分流订阅、WireGuard 节点、与 Loon 无关的桌面 mitmproxy 开发（除非只借概念）。

## Workflow (do in order)

### 1. Scope the capability

| Goal | Loon primitive | Notes |
|------|----------------|-------|
| 拦广告请求 | `[URL Rewrite] … - reject` | 轻；要 hostname 进 MitM 才稳 |
| 302 换目标 | `[URL Rewrite] … 302` | 见 B-Search 风格 |
| 改请求 Cookie/Query/Header | `http-request` + `$done({headers,url})` | `requires-body=false` 默认 |
| 改/读 JSON 响应 | `http-response` + body | `requires-body=true` |
| 二进制/proto | `binary-body-mode=true` | Spotify 类；别当 JSON 解析 |
| 用户开关 | `[Argument]` select/switch | Loon ~3.2.1(733)+ UI 更稳 |
| 存状态 | `$persistentStore` | 模式、指纹、节流时间戳 |
| 通知 | `$notification.post` | 必须节流 |

**完成标准：** 写清「改 request / response / reject / 只观测」四选一主路径，以及 **App vs Web** 目标。

### 2. Scaffold repo layout

```text
MyPlugin/
├── AGENTS.md                 # AI/人接手：决策+坑（强烈建议）
├── README.md                 # 用户安装
├── LICENSE
├── MyPlugin.plugin           # 【安装入口】根目录
├── plugin/
│   ├── MyPlugin.plugin       # 与根目录同步副本
│   └── MyPlugin.local.plugin # 本地 script-path 调试
└── scripts/
    ├── main-request.js
    └── main-response.js      # 可选
```

**完成标准：** 根目录存在可安装 `.plugin`；`scripts/` 与 `script-path` URL 一致。

### 3. Write plugin header + sections

Header keys (社区常见；空格风格二选一，**单文件内统一**):

```text
#!name = 显示名
#!desc = 一句话
#!author = you
#!homepage = https://github.com/...
#!icon = https://.../icon.png
#!openUrl = https://github.com/...
#!tag = a,b
#!system = iOS,iPadOS,macOS
#!loon_version = 3.2.1(733)
#!date = YYYY-MM-DD
```

Section order (recommended):

1. `#` comments (modes / non-goals)
2. `[Argument]` (if any)
3. `[Rule]` / `[URL Rewrite]` (if any)
4. `[Script]`
5. `[MitM]` or `[MITM]` — **可莉/Tabula 用 `[MitM]`**；deezertidal 常用 `[MITM]`，多数版本两者可认，**新插件跟可莉：`[MitM]`**

Canonical Script line (spaces around `=` like Tabula/可莉):

```text
http-request ^https:\/\/api\.example\.com\/v1\/feed script-path = https://raw.githubusercontent.com/USER/REPO/main/scripts/x.js, requires-body = false, timeout = 10, tag = MyPlugin Feed, argument = [{mode}]
```

Response:

```text
http-response ^https:\/\/api\.example\.com\/v1\/feed script-path = https://raw.githubusercontent.com/USER/REPO/main/scripts/y.js, requires-body = true, timeout = 10, tag = MyPlugin Observe, argument = [{notify}]
```

`[Argument]` examples:

```text
[Argument]
mode = select,"refresh","pure","origin",tag=模式,desc=说明
notify = switch,true,tag=通知,desc=异常时通知
```

Pass into script: `argument = [{mode},{notify}]` → 脚本读 `$argument`.

**完成标准：** 每条 Script 有唯一 `tag`；每个会解密的 host 出现在 `[MitM] hostname =`。

### 4. Script contracts (JS)

Always end with **exactly one** `$done(...)` path.

```js
// request: pass-through
$done({});

// request: rewrite
$done({ headers: newHeaders, url: newUrl });

// response: pass-through (observe only)
$done({});

// response: body patch (string body)
$done({ body: JSON.stringify(obj) });
```

Globals (Loon script env): `$request`, `$response`, `$argument`, `$persistentStore`, `$notification`, `$done`, `console.log`.

**Mutual exclusion:** 同一 URL 不要挂两个都会改写并 `$done` 的脚本。采集脚本用 **负向前瞻排除** 主路径（见 Tabula `tabulabili-capture.js` 正则）。

**App 登录态：** 常在 Query `access_key` + Cookie + 鉴权头；只删 Cookie 不够。去 `access_key` 后要按 appkey secret **重算 `sign`**（MD5），secret 会过期 → 预留更新表。

**被动探针：** response 只读 `code`/items，**不改 body**；`-352` 等业务码常在 HTTP 200 body 里；通知 30min 节流；**永不打印 Cookie 明文**。

**完成标准：** 主路径脚本在「origin 关功能」时 `$done({})`；日志带稳定前缀如 `[MyPlugin]`。

### 5. Host & publish raw

| Path | raw.githubusercontent | 说明 |
|------|------------------------|------|
| `/MyPlugin.plugin`（**根目录**） | ✅ | **唯一官方安装入口** |
| `/plugin/MyPlugin.plugin` | ❌ 常 **404** | GitHub raw 对 `plugin/*.plugin` 异常 |
| `/plugin/MyPlugin.conf` | ✅ 常可用 | 可作镜像扩展名 |
| `/scripts/*.js` | ✅ | script-path 放这里 |
| jsDelivr `gh/USER/REPO@main/...` | ✅ 可绕过 | 备用 CDN |

安装 URL:

```text
https://raw.githubusercontent.com/USER/REPO/main/MyPlugin.plugin
https://cdn.jsdelivr.net/gh/USER/REPO@main/MyPlugin.plugin
loon://import?plugin=https://raw.githubusercontent.com/USER/REPO/main/MyPlugin.plugin
```

发布前：

```bash
curl -sSIL "https://raw.githubusercontent.com/USER/REPO/main/MyPlugin.plugin" | head -5
curl -sSIL "https://raw.githubusercontent.com/USER/REPO/main/scripts/xxx.js" | head -5
# 改插件内容后同步根目录与 plugin/ 副本
cp MyPlugin.plugin plugin/MyPlugin.plugin
```

私有仓库 → Loon 拉不到 raw → 对安装场景应 **public** 或改自建/CDN。

**完成标准：** 安装 URL 与 script-path **全部 HTTP 200**；根目录与 `plugin/` 副本一致。

### 6. Verify on device

1. Loon 装插件 → 开 MitM → 信任证书  
2. 触发真实 App/Safari 流量  
3. 脚本日志搜 `tag` / `[MyPlugin]`  
4. **无效时二分：** MitM hostname → 正则是否命中（App feed vs Web）→ 是否被其它插件抢改 → mode=origin 对照  
5. 去广告(response) 与 去身份(request) 可并存；异常时先关其它 B 站/同域脚本  

**完成标准：** 日志至少一次命中；用户可感知行为或探针有明确 code。

## Templates

Load with `skill_view(name='loon-plugin', file_path='templates/...')`:

| File | Use |
|------|-----|
| `templates/minimal-reject.plugin` | 纯 reject + MitM |
| `templates/request-response.plugin` | Argument + request 改写 + response 探针骨架 |
| `templates/script-request.js` | 请求侧最小脚本 |
| `templates/script-response-observe.js` | 被动观测响应 |
| `references/raw-hosting.md` | raw/jsDelivr/loon import 速查 |
| `references/sources.md` | 参考仓库与本地路径 |

## Patterns cheat sheet

### Reject ad URL

```text
[URL Rewrite]
^https?:\/\/api\.example\.com\/ad\/ - reject

[MitM]
hostname = api.example.com
```

### Request scrub cookie (refresh-style)

- pure: delete Cookie  
- refresh: keep only device ids (`buvid3`/`buvid4` 类)  
- origin: no-op  

### Capture vs clean split

- Clean: narrow regex on feed URL  
- Capture: broad host regex with `(?!feed|rcmd)` exclusion  
- Never both `$done` rewrite on same URL  

### Risk / health probe

- Match same feed URLs as clean  
- `http-response` + `requires-body=true`  
- Classify `code===0 && n>0` / `-352` / empty / other  
- Throttle notifications  

## Common Pitfalls

1. **安装入口放在 `plugin/*.plugin`** → raw 404；放根目录。  
2. **只写 Web API、用户测 App** → 日志零命中；先抓真实 host/path。  
3. **MitM 漏 hostname** → 脚本永不跑。  
4. **两脚本抢同一 URL** → 行为未定义；排除正则。  
5. **App 只删 Cookie 不去 access_key** → 仍个性化/仍登录态。  
6. **去 access_key 不重签** → 4xx / 业务失败。  
7. **把 HTTP 200 + body.code=-352 当网络成功** → 探针要解析 JSON。  
8. **私有 repo raw** → Loon 无法订阅。  
9. **可莉 Cloudflare 拦爬虫** → 用已 clone 的样本 / 用户导出 / 社区镜像，别死磕 kelee.one curl。  
10. **宣传成破解/去广告抄可莉** → 分清目标与许可（可莉 CC BY-NC-SA；Tabula MIT）。

## Verification Checklist

- [ ] `#!name` / `#!desc` / author / homepage 齐全  
- [ ] `[MitM] hostname` 覆盖所有 script 正则 host  
- [ ] 根目录 `.plugin` 与 `plugin/` 副本同步  
- [ ] raw + 每个 `script-path` 返回 200  
- [ ] 无双脚本同 URL 改写冲突  
- [ ] 请求脚本有 origin/no-op 路径  
- [ ] 响应改写才 `requires-body=true`；观测不改 body  
- [ ] 日志前缀稳定；通知有节流；无 Cookie 明文  
- [ ] README 安装 URL + 用户验证步骤；AGENTS.md 记决策  

## One-shot: new plugin from zero

1. Copy `templates/request-response.plugin` → `Foo.plugin`；改 name/desc/regex/hosts  
2. Copy `templates/script-*.js` → `scripts/`；改 store key 前缀  
3. 填真实 `script-path` raw URL（先 push 空脚本也行）  
4. `cp Foo.plugin plugin/Foo.plugin`  
5. 真机 MitM + 日志验证  
6. 写 README 安装链；需要维护则写 AGENTS.md  

本地参考实现：

```bash
ls /root/repos/TabulaBili-Loon/
# TabulaBili.plugin  scripts/  AGENTS.md
```
