# Loon 插件能力边界（TestFlight / 3.5.1 (978)+ 起分层）

> 官方文档对不同能力给出**不同 build 门槛**，不要用一个数字概括全部。下表按官方文档标注整理；用户给出更高 TestFlight build 时，以该 build 的内置提示/日志和官方文档为准，不猜测未公开能力。

| 能力 | 官方门槛 | 来源 |
|---|---|---|
| 新 Rewrite 语法（`request`/`response`、位置参数） | Loon 3.5.1 **(978)+** | `/docs/Rewrite/rewrite_v2` |
| 旧 Rewrite 语法 | 3.5.1 **(978) 之前**，仅维护旧配置 | `/docs/Rewrite/` |
| 新版 Script 语法（`script(...)` + `with`） | Loon 3.5.1 **(983)+** | `/docs/Script/script_v2` |
| 旧 Script 语法（`script-path=` / `http-request`） | 3.5.1 **(982) 及之前**，仅维护旧配置 | `/docs/Script/` |
| `$utils.gzip`、`$crypto.aes.encrypt/decrypt`、`$dns.query` | Build **988+** | `/docs/Script/script_api` |
| `$httpClient` 响应 `h2_trailers` | Build **931+** | `/docs/Script/script_api` |
| `$httpClient` `body-base64` | Build **612+** | `/docs/Script/script_api` |
| `$httpClient` `auto-redirect` | Build **660+** | `/docs/Script/script_api` |
| `$httpClient` `auto-cookie` | Build **662+** | `/docs/Script/script_api` |
| `$httpClient` `alpn` | Build **715+** | `/docs/Script/script_api` |
| `[Argument]` | Build **733+** | `/docs/Plugin/` |
| `#!type` = `normal` / `parser` | **3.5.0 (969)+** | `/docs/Plugin/` |
| 插件 `[General] include-tun`、`[IP Rewrite]` | Build **1007+** | `/docs/Plugin/` |

## 插件容器

插件是可复用子配置，可包含：`[General]`、`[IP Rewrite]`（Build 1007+，仅插件可用）、`[Rule]`、`[Rewrite]`、`[Host]`、`[Script]`、`[MitM]`、`[Argument]`。

MitM 段落名在官方文档中**两种大小写并存**：`/docs/Plugin/` 的完整示例写作 **`[Mitm]`**，`/docs/MitM/` 写作 **`[MitM]`**；官方从未声明该段落名大小写敏感，也未声明 `[MITM]` 非法（社区样本多用全大写）。**静态检查不把任何大小写判为非法**；本仓文档统一写 `[MitM]` 只是**团队书写约定**，并非「官方唯一正确写法」。各大小写（尤其 `[MITM]`）的真机兼容性**本仓未验证**，不得据此声称兼容。

元数据：`#!name`、`#!desc`、`#!author`、`#!homepage`、`#!icon`、`#!system`、`#!system_version`、`#!loon_version`、`#!date`、`#!tag`、`#!type`。
官方元数据表把上述字段**平铺列出，未标注任何必填字段**（`#!type` 省略默认 `normal`、`#!system` 省略表示全部支持），全文无 `必填/required` 表述。因此缺 `#!date` / `#!loon_version` **不是 Loon 语法错误**；本仓要求新插件补齐二者，属**发布规范（团队约定）**而非官方要求。
`#!date` 为插件版本日期（如 `2026-10-09`，按原样显示，无版本门槛作用）；官方完整示例中与 `#!loon_version` 并列出现。
`#!type`（3.5.0 (969)+）：`normal` 普通插件；`parser` 资源解析器，可在节点、规则、配置订阅页面选择。省略默认 `normal`。

## `[Argument]`（Build 733+）

声明格式：`参数名 = 控件类型,默认值或可选值,type=值类型,tag=标题,desc=说明`。

| 控件 | 默认值 | 支持类型 | 省略 `type=` |
|---|---|---|---|
| `input` | 可省略 | string、number | string |
| `select` | **第一个候选值为默认值** | string、number | string |
| `switch` | **填写 `true` 或 `false` 作为默认值**（官方示例均显式给出） | boolean | boolean |

- `input` / `select` 不会按内容推断类型：`input,123` 仍是字符串；数值必须声明 `type=number`。
- 类型名不区分大小写；不支持 `integer` / `float` / `bool` 等别名。
- 引用：Script V2 用 `script("x.js", {${a}, ${b}})`，`with enable=${enabled}`；Rewrite V2 用 `${name}`。
- Cron：`cron ${cronExpression} then script(...)`。
- 参数只作为有类型数据使用，不能生成语法，也不会二次展开。

## `[General]` 与 `[IP Rewrite]`（Build 1007+）

- `[General] include-tun`（Build 1007+）：只接受带明确前缀长度的 IPv4 CIDR，不接受域名/裸 IP/IPv6；不与 `bypass-tun` 相互覆盖，冲突时同掩码以 include 优先、不同掩码以更具体者优先。
- `[General] ipv6-vif`：插件显式声明 `off` 从 Build 1007+ 生效。
- `[IP Rewrite]`（Build 1007+，仅插件）：`目的 IPv4 = reflect|reject|drop`；命中后不再进入规则/策略/HTTP Rewrite/Script/MitM。不支持参数绑定。存在非法项或重复声明时整个模块不发布动作。
- 未列出的 General 参数不会通过插件应用。

插件规则策略只允许 `DIRECT`、`REJECT` 系列、`PROXY`；省略策略默认 `DIRECT`。`PROXY` 由用户选择策略组。

## 三层能力及选择

| 层 | 能做 | 做不到/限制 | 优先场景 |
|---|---|---|---|
| Rewrite V2 (978+) | URL、条件匹配、重定向/拒绝；请求/响应 Header、Body 正则、JSON、jq、Mock | 只处理 HTTP 与已 MitM 的 HTTPS；条件不能读 Body；无任意 JS、存储、通知、主动请求 | 声明式修改，优先使用 |
| Script V2 (983+) | 任意 JS 处理请求/响应；字符串或 Uint8Array；持久化、通知、额外请求 | 受超时、内存与脚本生命周期约束；仍需 HTTP/HTTPS MitM；无原生 App UI/文件系统任意访问 | Rewrite 无法表达的算法、签名、复杂结构 |
| Rule/Host/General/IP Rewrite | 分流、DNS/Host、TUN 例外、IP 层动作 | 不修改应用层 Body；插件规则策略受限 | 路由、解析、IP 层 |

原则：**能用 Rewrite V2 就不用脚本；需动态算法/跨请求状态/通知/外部请求才用 Script。**

## Rewrite V2 边界（978+）

- 在规则匹配前执行。
- `request`：可读 URL、method、请求 Header；可修改请求，也可生成 Mock 响应。
- `response`：额外可读 status、响应 Header；可修改响应。
- 一条普通 Rewrite 不能同时包含请求 Action 和响应 Action。
- 条件当前**不能读取 Body**。
- `response.body.mock(...)` 配置阶段写作 `response`，但 Loon 会在请求发往上游前提前生成响应（不是写在 `request` 阶段）。
- 同阶段所有命中项均执行：本地配置优先于插件；同来源从上到下。
- 同行多 Action 左→右；运行失败保留之前修改、跳过失败项并继续。**参数/类型/正则配置错误会拒绝整条 Rewrite**（含使用未发布的 `http-request`/`http-response` 或命名参数写法）。
- 新旧 Rewrite 可混用，进入同一顺序；不会自动迁移旧语法。
- HTTPS host 必须在 `[MitM] hostname = ...` 且用户安装并信任证书；证书固定、QUIC/HTTP3、应用自定义加密可能导致无法解密，这不是插件语法可绕过的边界。

完整语法见 `references/rewrite-v2.md`。

## Script（新版语法 983+ 为默认）

统一 Action：`script(<path>[, <argument>]) [with <options>]`。

```text
request  if <condition> then script("request.js"[, "arg" | {${a}, ${b}}]) [with ...]
response if <condition> then script("response.js"[, ...]) [with ...]
cron <cron-expression> then script("cron.js"[, ...]) [with ...]
network-changed then script("network.js"[, ...]) [with ...]
generic then script("tool.js"[, ...]) [with ...]
```

- `<cron-expression>` 支持 5 段（分 时 日 月 周）或 6 段（秒 …）；插件可用 String 参数动态提供：`cron ${cron} then script(...)`。
- 脚本路径必须是**非空固定字符串**（本地/相对/远程 URL），不能含变量或模板。
- 第二个参数决定 `$argument` 类型：省略 → `null`；String / Raw String → String；插件对象 `{${a}, ${b}}` → Object（只能列当前插件已声明参数、不可为空、不可重复；`script("p.js", {})`、`{"CN", 2}`、`{${url}}` 无效）。
- **一条规则只能有一个 `script(...)`**，不支持 Rewrite 的 `|` 管道。

`with` 字段（小写 snake_case，未知字段使该规则无效）。**`with` 整体可省略**：官方原文「没有字段时省略整个 `with`。」（例：`response if … then script("success.js")` 合法）；`then` 后允许多个空白（官方：「新版语法不会按空格拆分整行」）：

| 字段 | 类型 | 默认值 | 适用范围 |
|---|---|---|---|
| `enable` | Boolean / 插件 Boolean | `true` | 全部 |
| `tag` | String | 由脚本路径派生 | 全部 |
| `img_url` | String | 无 | 全部 |
| `timeout` | Number / 插件 Number 或数字 String | Request/Response **20**，其他 **300** | 全部 |
| `debug` | Boolean / 插件 Boolean | `false` | 全部 |
| `requires_body` | Boolean | `false` | Request / Response |
| `binary_body_mode` | Boolean | `false` | Request / Response |

- `enable` / `timeout` / `debug` 可引用类型匹配的插件参数；`tag` / `img_url` / `requires_body` / `binary_body_mode` 不接受变量。
- 缺值回退：动态 `enable` → `true`，`timeout` → 20/300，`debug` → `false`（每次回退输出 Warn）；条件/Cron 参数缺值时该条无效。
- 旧语法 `script-path=`、`requires-body=`、`binary-body-mode=` 仅作为 **3.5.1 (982) 及之前** 的迁移参考（见 SKILL.md）。

### 匹配与执行

- HTTP **第一条命中**：Request / Response 各最多选一条，按配置顺序取第一条完整命中；Request 与 Response 互不占用对方命中位置。
- **Response URL Guard 必须存在且为必要条件**：每条 Response Script 的条件必须包含 `${url} ~= …`，且不能只放在 `||` 分支。
- 条件用与 Rewrite V2 相同的 `==` / `~=` / `&&` / `||` / `()`；但 Script 的 URL 正则**不支持 `as` 命名捕获**（需在 JS 中自行 `match`）。
- 暂不支持：Request/Response Body 内容条件、`!=` / `!~` / 逻辑非 / 大小比较 / 集合操作符。
- 与 Rewrite 的禁用关系：Request 阶段产生终止响应时 Request/Response Script 均不执行；Request Body Rewrite 或 Request Body Mock 命中时 Request Script 不执行；Response Body Rewrite 命中时 Response Script 不执行；只改 Request Header 的 Rewrite 不新增禁用。

## Script 运行时对象与 API

### Request Script
`$request.url/method/headers/body/h2_trailers`；`$response` 为 undefined。
- 结束 / 放行（**现行 API**，`/docs/Script/script_api` §11）：`$done()` 结束脚本（§11.1「结束普通、Cron 或 Generic 脚本」）；HTTP 脚本要**不修改地放行原请求（no-op）**用 `$done({})`（§11.2「放行原请求或响应」）。旧版 `/docs/Script/`（≤3.5.1 (982)）把 `$done()` 记为「中断请求」，现行 API 页未用该措辞，**本仓未真机确认**。
- `$done({url, headers, body, h2_trailers, node, policy})` 修改请求；未提供字段保留原值，空值清除（官方提示：提供 headers 时应先复制原 Header）。
- `$done({response:{status, headers, body}})` 直接生成响应，跳过上游。

### Response Script
额外 `$response.status/headers/body/h2_trailers`。Body 需 `requires_body=true`。
- `$done()` 结束脚本、`$done({})` **不修改地放行原响应**（同 `/docs/Script/script_api` §11.1/§11.2；旧版 `/docs/Script/` 记作「中断」，未真机确认）。
- `$done({status|statusCode, headers, body, h2_trailers})` 修改响应；Loon 会按协议处理 `Content-Length`/`Transfer-Encoding`/`Content-Encoding`。

### 其他类型
`cron`、`network-changed`（一次网络变化执行所有已启用项）、`generic`（App 内手动触发，可返回 `{title, content}`）。

### API 清单与 Build 门槛

- 基础：`console.log`、`setTimeout`、`setInterval`、`$done`。
- 运行信息：`$loon`、`$script.name/startTime`、`$argument`、`$environment`（`params.node`/`nodeInfo`）。
- 配置（读）：`$config.getConfig()`（**无参数**，同步返回配置摘要 JSON **字符串**，需 `JSON.parse`）；`$config.getSubPolicies(policyName, callback)`（异步，回调收 JSON 字符串）；`$config.getSelectedPolicy(policyName)`。
- 配置（写，会改全局运行状态）：`$config.setSelectPolicy(policyName, selectName)`（同步切换策略组，支持等长数组批量，返回 true/false）；`$config.setRunningModel(0|1|2)`。旧别名 `getPolicy` = `getSelectedPolicy`，`getSubPolicys` = `getSubPolicies`。
- 存储：`$persistentStore.write/read/remove`（字符串；`remove()` 清除脚本 API 保存的全部本地数据，慎用）。
- 通知：`$notification.post(title, subtitle, content, attach, delay)`；`attach` 可含 `openUrl`、`mediaUrl`、`clipboard`；`mediaUrl` 支持 Data URI 或不带前缀的纯 Base64（PNG/JPEG/GIF/WebP）。
- HTTP：`$httpClient.get/post/head/delete/put/options/patch`；参数 `timeout`（默认 5000ms）、`headers`、`body`、`body-base64`（612+）、`node`、`binary-mode`、`auto-redirect`（660+）、`auto-cookie`（662+）、`insecure`、`alpn`（715+）；响应 `h2_trailers`（931+）。
- 工具：`$utils.geoip`、`ipasn`、`ipaso`、`ungzip`；`$utils.gzip`（**988+**）。
- 加密：`$crypto.aes.encrypt/decrypt`（**988+**）。
- DNS：`$dns.query(options, callback)`（**988+**）。
- 完成：异步结束后必须调用 `$done()`，且每条执行路径只完成一次。

## 明确不属于插件能力

- 不能修改 App 本地数据库、界面、沙盒文件或二进制代码；网络层看不到的数据不能改。
- 不能绕过 TLS 证书固定、自定义端到端加密或服务端鉴权；只能修改可见流量。
- 不能保证第三方 API 字段长期稳定；必须抓包、日志验证。
- 插件不是常驻后台服务；Cron/网络变化受 iOS 与 Loon 生命周期约束。
- Rewrite/Script 不能凭空提供服务端权益；客户端字段修改不等于服务端授权。
- 不声称兼容 Surge/Quantumult X/Stash 私有语法；转换时逐项映射并降级。

## 官方来源

- 插件：https://nsloon.app/docs/Plugin/
- Rewrite V2：https://nsloon.app/docs/Rewrite/rewrite_v2
- Rewrite（旧版）：https://nsloon.app/docs/Rewrite/
- 脚本（新版 983+）：https://nsloon.app/docs/Script/script_v2
- 脚本（旧版 ≤982）：https://nsloon.app/docs/Script/
- Script API：https://nsloon.app/docs/Script/script_api
- 生成器：https://nsloon.app/rewrite-builder/
- MitM：https://nsloon.app/docs/MitM/
- Scheme：https://nsloon.app/docs/Scheme/
