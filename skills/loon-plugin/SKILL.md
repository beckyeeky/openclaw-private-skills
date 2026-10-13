---
name: loon-plugin
description: >-
  构建、审计、调试、迁移、打包或发布 Loon 插件（.plugin/.lpx）的完整工程技能。覆盖最新版 TestFlight：Rewrite V2（Loon 3.5.1 (978)+）、Script V2（983+）、插件元数据与 [Argument]、旧语法迁移、[Script] 全类型与 Script API、[MitM]/[Rule]/[Host]/[General]、能力边界与 build 门槛（988/1007+）、真机验证。用户提到 Loon 插件、复写、新复写语法、Rewrite Builder、MitM、Loon 脚本时触发；Surge/QX/Stash 仅在转换为 Loon 时使用。
license: MIT
metadata:
  version: 2.1.0
  official_baseline: "Rewrite V2 3.5.1 (978)+；Script V2 3.5.1 (983)+；部分 Script API 988+；[IP Rewrite]/include-tun 1007+"
  tags: [loon, plugin, rewrite-v2, script, mitm, testflight]
---

# Loon Plugin Engineering

## 权威基线与加载规则

官方对不同能力给出**不同的 build 门槛**，不要用一个数字概括全部：

| 能力 | 官方门槛 |
|---|---|
| 新 Rewrite 语法（`request`/`response`、位置参数） | Loon 3.5.1 **(978)+** |
| 旧 Rewrite 语法 | 3.5.1 **(978) 之前**，仅维护旧配置 |
| 新版 Script 语法（`script(...)` + `with`） | Loon 3.5.1 **(983)+**（默认） |
| 旧 Script 语法（`script-path=` / `http-request`） | 3.5.1 **(982) 及之前**，仅迁移参考 |
| `$utils.gzip`、`$crypto.aes.*`、`$dns.query` | Build **988+** |
| `$httpClient` 响应 `h2_trailers` | Build **931+** |
| 插件 `[General] include-tun`、`[IP Rewrite]` | Build **1007+** |

`#!loon_version` 按用到的最高能力填：只用 Rewrite V2 填 `3.5.1(978)`；用了新 Script 语法填 `3.5.1(983)`。用户提供更高 build 时，先查官方文档/生成器和该 build 日志；不要把传闻写成已发布能力。

开始任务时按需读取：

| 文件 | 何时读 |
|---|---|
| `references/capability-boundary.md` | 每次设计/审计；判断能否实现、选 Rewrite 或 Script、查 build 门槛 |
| `references/rewrite-v2.md` | 涉及复写、迁移、生成器时；含全部条件/Action/限制 |
| `references/raw-hosting.md` | 发布、安装链接、远程资源时 |
| `references/sources.md` | 需要来源或社区样本时 |
| `scripts/check-templates.py` | 改完插件/模板后做离线语法回归校验 |

官方入口：
- https://nsloon.app/docs/Plugin/
- https://nsloon.app/docs/Rewrite/rewrite_v2
- https://nsloon.app/rewrite-builder/
- https://nsloon.app/docs/Script/script_v2
- https://nsloon.app/docs/Script/
- https://nsloon.app/docs/Script/script_api

## 先做能力判定

1. 明确目标是 request、response、reject/redirect/mock、路由/DNS，还是后台/本地 App 行为。
2. 明确目标流量是 HTTP 还是 HTTPS；HTTPS 必须可 MitM。
3. 优先级：**Rewrite V2 → Script → 判定不可实现**。
   - Rewrite V2：声明式 URL/Header/Body/JSON/jq/mock，简单、低开销。
   - Script：任意算法、签名、条件读取 Body、状态、通知、主动请求、复杂二进制。
   - 不可实现：App UI/沙盒/二进制修改、TLS pinning 或端到端加密绕过、服务端授权。
4. 明确 App/Web 的真实 host/path/method/content-type；不要凭网站 API 推测 App API。
5. 对安全、付费权益、认证场景，只做用户有权控制流量的调试/隐私/互操作，不承诺绕过服务端权限。

## 插件骨架

```text
#!name = 示例插件
#!desc = 功能说明
#!author = author
#!homepage = https://example.com
#!icon = https://example.com/icon.png
#!system = iOS,iPadOS,tvOS,macOS
#!system_version = 15
#!loon_version = 3.5.1(978)
#!date = 2026-10-13
#!tag = 工具,复写
#!type = normal

[Argument]
enabled = switch,true,type=boolean,tag=启用
region = select,"CN","US",type=string,tag=地区
price = input,9.99,type=number,tag=价格

[Rewrite]
response if ${enabled} == true && ${url} ~= /^https:\/\/api\.example\.com\/profile$/ && ${response.status} == 200 then response.json.replace("data.price", ${price})

[Script]
# 仅在 Rewrite 无法表达时添加；默认用新版语法（983+）
# request if ${url} ~= /\/api\// then script("request.js") with requires_body=true, tag="Request"

[MitM]
hostname = api.example.com
```

插件可包含 `[General] [Rule] [Rewrite] [Host] [Script] [MitM] [Argument]`（Build 1007+ 另可含 `[IP Rewrite]`）。`#!type` 为 `normal` 或 3.5.0 (969)+ 的 `parser`。插件规则只能用 `DIRECT`、`REJECT` 系列、`PROXY`，省略默认 DIRECT。

## Rewrite V2 工作流

基本格式（必须单行）：

```text
<request|response> if <condition> then <action> [| <action> ...]
```

> 阶段关键字只有 **`request`** / **`response`**；Action 只用**位置参数**。官方原文：「开发阶段曾使用过但未正式发布的 `http-request`、`http-response` 和命名参数写法不属于兼容范围。」写错会被 Loon 在加载时按配置错误**整条拒绝**。

1. 在官方 [Rewrite 生成器](https://nsloon.app/rewrite-builder/) 选择阶段。
2. 组合 `==` / `~=`、`&&` / `||` / 括号和 `as name` 捕获。
3. 选择 Action：URL/redirect、reject 系列、request/response Header、Body regex、JSON/jq、mock——**全部位置参数**。
4. 检查阶段限制：条件不能读 Body；响应变量仅 `response`；一条普通 Rewrite 不能同时含请求和响应 Action；`response.body.mock` 写在 `response` 阶段（Loon 会在请求发出前提前生成响应），且受限组合（一条只能一个 mock，除 Mock 外只可搭配 `response.header.*`，条件与 Mock 参数不能引用响应变量）。
5. 检查类型：字符串双引号；数字不加引号；switch 是 Boolean；input/select 需 `type=number` 才是 Number。
6. 多 Action 左→右；多条均会执行且后项可覆盖前项；本地配置优先插件。
7. HTTPS 补 `[MitM]`；真机加载看配置/运行日志。

不要只凭生成器判断有效：它只在浏览器本地生成文本，不执行，也不了解实际流量。

## Script 工作流

脚本类型：`request`、`response`、`cron`、`network-changed`、`generic`。**默认使用新版语法（3.5.1 (983)+）**。

`with` 是**可选**的（官方原文：「没有字段时省略整个 `with`。」）：`then script("x.js")` 合法。不需要字段时省略 `with`，不生成空 `with`。静态检查允许 `then` 后多空白；这不替代真机校验。`with` 字段区分大小写、只允许小写 snake_case。

Canonical（新版）：

```text
[Script]
request if ${url} ~= /^https:\/\/api\.example\.com\/v1\/feed/i && ${request.method} == "POST" then script("https://example.com/request.js", {${mode}}) with tag="请求处理", timeout=20, requires_body=true

response if ${url} ~= /^https:\/\/api\.example\.com\/v1\/feed/i && ${response.status} == 200 then script("https://example.com/response.js", {${notify}}) with tag="响应处理", timeout=20, requires_body=true
```

迁移参考（旧语法，仅 3.5.1 (982) 及之前）：

```text
http-request ^https:\/\/api\.example\.com\/v1\/feed script-path=request.js,argument="mode=scrub",tag=请求处理,timeout=10
http-response ^https:\/\/api\.example\.com\/v1\/feed script-path=response.js,argument={notify},enabled={enabled}
```

官方对应关系：`script-path=` → `script("…")`；`argument="x"` → `script("…", "x")`；`argument={a,b}` → `script("…", {${a}, ${b}})`；`requires-body=` → `with requires_body=`；`binary-body-mode=` → `with binary_body_mode=`；`img-url=` → `with img_url=`；`enabled=` → `with enable=`；`timeout=` 默认从 10 变为 20（Request/Response）。

契约：
- 每条执行路径恰好一次 `$done`；异步回调完成后再 `$done`。
- `$done()` / `$done({})`（**现行 API**，来源 `/docs/Script/script_api` §11）：
  - `$done()` 用于**结束**普通 / cron / generic 脚本（§11.1「结束普通、Cron 或 Generic 脚本」）。
  - HTTP 脚本要**放行原请求/响应、不做修改（no-op）**时用 `$done({})`（§11.2「放行原请求或响应」）。
  - 「`$done()` = 中断请求」的措辞只出现在**旧版** `/docs/Script/`（自述适用 Loon 3.5.1 (982) 及之前的 Script 语法，仅用于维护旧配置）；现行 API 页未使用该措辞，其现行是否仍表现为中断**本仓未在真机确认**。写新脚本以「结束 / 放行」语义为准，勿把旧版措辞当现行契约。
- request 修改 `{url,headers,body,h2_trailers,node,policy}`；可返回 `{response:{...}}` 直接响应。
- response 修改 `{status|statusCode,headers,body,h2_trailers}`。
- 未传字段保留，空对象/空字符串用于清除。
- Body 需 `requires_body=true`；二进制用 `binary_body_mode=true` / Uint8Array。
- 参数：`script("x.js", {${a}, ${b}})` → `$argument.a`（保留声明类型）；第二个参数是字符串/原始字符串时 `$argument` 为 String；省略为 `null`。
- **Response Script 必须包含 URL Guard**（`${url} ~= …` 且为必要条件）；Script 的 URL 正则不支持 `as` 命名捕获。
- 不打印 Cookie/token；通知节流；存储 key 加插件命名空间；慎用会清空全部脚本存储的 `$persistentStore.remove()`。

Script API 全表和 build 门槛（931/988/612/660/662/715）见能力边界文件。

## 冲突与执行顺序

- Rewrite V2 同阶段所有命中项执行，不是首条即停；后项可能覆盖先项。
- 新旧 Rewrite 可混排，按顺序执行，不自动迁移。
- 本地 Rewrite 优先于插件 Rewrite。
- Rewrite 与 Script 的禁用关系：Request 阶段产生终止响应时 Request/Response Script 均不执行；Request Body Rewrite 或 Request Body Mock 命中时 Request Script 不执行；Response Body Rewrite 命中时 Response Script 不执行；只改 Request Header 的 Rewrite 不新增禁用。
- 同一请求/响应最多命中一条 Request Script、一条 Response Script（按配置顺序取第一条）；两条都写时缩窄正则或做互斥排除。
- 每条 Script `tag` 唯一；每个解密 host 纳入 `[MitM]`。

## 调试顺序

1. **配置是否加载**：版本门槛、单行 Rewrite、阶段关键字（`request`/`response`）、位置参数、参数类型/正则语法、远程文件 200。
2. **流量是否可见**：HTTP/HTTPS、MitM 证书、hostname、TLS pinning/QUIC、自定义加密。
3. **是否命中**：真实 URL/method/header/content-type 与正则；区分 App/Web。
4. **阶段是否正确**：请求/响应变量是否用在正确阶段；`response.body.mock` 是否写在 `response` 阶段；Response Script 是否有 URL Guard。
5. **Body 是否可处理**：requires_body、JSON 是否有效、压缩/二进制、jq/jq_file 路径。
6. **是否被覆盖**：本地 > 插件、从上到下、多个 Action、其它插件/脚本。
7. **业务是否接受**：签名、鉴权、Content-Length/Encoding、服务端业务码。
8. 保留 no-op 对照、稳定日志前缀和最小复现，逐项恢复。

## 发布

推荐结构：

```text
repo/
├── Foo.plugin
├── scripts/
├── resources/       # jq/mock 文件
└── README.md
```

- 所有 script 路径、icon、jq/mock file 引用在目标安装环境可访问。
- 对每个远程 URL 做 HEAD/GET 验证；私有仓库通常不能匿名订阅。
- 安装：`loon://import?plugin=<percent-encoded-plugin-url>`。
- GitHub raw 路径是否可用取决于真实仓库路径和访问状态；不要宣称某个目录名天然 404。
- 可提供 jsDelivr 等镜像，但调试缓存时优先固定 commit URL 或更新版本号。

## 验收清单

- [ ] 目标处于 Loon 网络层能力边界内
- [ ] `#!loon_version` 与所用能力匹配（Rewrite V2 = `3.5.1(978)`；新 Script 语法 = `3.5.1(983)`；用到 988+ API 时更高）
- [ ] 元数据、系统门槛、type 正确（`#!date` / `#!loon_version` 属**本仓发布规范**：官方元数据表未标任何必填字段，缺失不算 Loon 语法错误；`#!loon_version` 仅用于声明能力门槛）
- [ ] Argument 类型与引用一致（`switch` 显式写默认值；数值用 `type=number`）
- [ ] 优先 Rewrite；Script 有明确必要性
- [ ] Rewrite 单行、阶段只用 `request`/`response`、Action 全位置参数、变量/捕获合法
- [ ] reject 使用 `reject`/`reject_img`/`reject_dict`/`reject_array`/`reject_video`
- [ ] `response.body.mock` 写在 `response` 阶段并满足组合限制
- [ ] HTTPS host 完整加入 `[MitM]`
- [ ] Script 使用新版 `script(...)`+`with`（除非维护旧配置）；Response Script 有 URL Guard；每路径一次 `$done`，Body/binary 配置正确
- [ ] 无敏感日志，状态/通知有命名空间与节流
- [ ] 无顺序覆盖和重复命中冲突
- [ ] 远程资源可访问
- [ ] `python3 scripts/check-templates.py` 离线校验通过（仅静态检查，不代表 Loon 接受）
- [ ] 在目标 TestFlight build 真机命中并检查日志

## Bundled templates

- `templates/minimal-reject.plugin`：最小 Rewrite V2 拒绝示例（`request` 阶段 + `reject_img`）
- `templates/request-response.plugin`：Argument + Script V2 骨架（983+）
- `templates/script-request.js`
- `templates/script-response-observe.js`
- `scripts/check-templates.py`：离线静态校验脚本（见下）

## 离线语法回归校验

`scripts/check-templates.py` 对 `templates/*.plugin` 与内置正/反例做**纯文本静态检查**，覆盖本技能文档化的规则：阶段关键字、位置参数、`header.del`、reject 系列、mock 阶段与组合、Script V2 `with` 字段（`with` 本身**可省略**；`then` 后允许多空白）。

- 判为**错误**（计入退出码 1）的只有会导致整条规则被拒的写法；以下只输出**非致命提示（advisory，不影响退出码）**：
  - 缺 `#!date` / `#!loon_version`：**本仓发布规范建议**（团队约定），官方元数据表未标注任何必填字段，**不是 Loon 语法错误**，退出码仍为 0。
  - MitM 段落名大小写：官方文档 `[Mitm]`（`/docs/Plugin/` 完整示例）与 `[MitM]`（`/docs/MitM/`）**并存**，官方未声明大小写敏感；静态检查**不把任何大小写判为非法**（含 `[MITM]`），真机兼容性本仓未验证，不得据此声称兼容。
- 用法：`python3 scripts/check-templates.py`（校验模板）；`python3 scripts/check-templates.py --self-test`（跑内置正/反例）。
- `--self-test` 含对应回归：**无 `with` 的官方正例**、`then` 后多空白、缺 `#!date` 的最小插件、`[MITM]`/`[Mitm]`/`[MitM]` 三种大小写。
- **它不是 Loon 解析器**，只做文本启发式匹配，也不替代真机加载；通过校验 ≠ Loon 一定接受。真正有效仍以官方文档 + 目标 TestFlight build 真机日志为准。
