# Loon 插件能力边界（TestFlight / 3.5.1 (978)+）

> 官方文档当前明确的新能力基线：Loon 3.5.1 (978)+。若用户给出更高 TestFlight build，以该 build 的内置提示/日志和官方文档为准，不猜测未公开能力。

## 插件容器

插件是可复用子配置，可包含：`[General]`、`[Rule]`、`[Rewrite]`、`[Host]`、`[Script]`、`[Mitm]`、`[Argument]`。

元数据：`#!name`、`#!desc`、`#!author`、`#!homepage`、`#!icon`、`#!system`、`#!system_version`、`#!loon_version`、`#!tag`、`#!type`。

`#!type`（3.5.0 (969)+）：
- `normal`：普通插件。
- `parser`：资源解析器，可在节点、规则、配置订阅页面选择。

`[Argument]`（Build 733+）：
- `input`：String；可用 `type=number` 变 Number。
- `select`：String；可用 `type=number` 变 Number；首项为默认值。
- `switch`：Boolean，默认 false。
- 脚本：`argument=[{name},{region}]` 后读 `$argument.name`。
- Cron：`cron {cronExpression} ...`。
- 启停：`enable={enabled}`。
- Rewrite V2：`${name}`。
- 参数只能作为数据，不能生成语法，不能二次展开。

插件规则策略只允许 `DIRECT`、`REJECT` 系列、`PROXY`；省略策略默认 `DIRECT`。`PROXY` 由用户选择策略组。

## 三层能力及选择

| 层 | 能做 | 做不到/限制 | 优先场景 |
|---|---|---|---|
| Rewrite V2 | URL、条件匹配、重定向/拒绝；请求/响应 Header、Body 正则、JSON、jq、Mock | 只处理 HTTP 与已 MitM 的 HTTPS；条件不能读 Body；没有任意 JS、存储、通知、主动网络请求 | 声明式修改，优先使用 |
| HTTP Script | 任意 JS 处理请求/响应；字符串或 Uint8Array；持久化、通知、额外请求 | 受超时、内存和脚本生命周期约束；仍需 HTTP/HTTPS MitM；无原生 App UI/文件系统任意访问 | Rewrite 无法表达的算法、签名、复杂结构 |
| Rule/Host/General | 分流、DNS/Host、TUN 例外等配置 | 不修改应用层 Body；插件规则策略受限 | 路由与解析 |

原则：**能用 Rewrite V2 就不用脚本；需动态算法/跨请求状态/通知/外部请求才用 Script。**

## Rewrite V2 边界

- 在规则匹配前执行。
- `http-request`：URL、method、请求 Header；可修改请求，也可直接 mock 响应。
- `http-response`：以上请求信息 + status、响应 Header；可修改响应。
- 条件当前不能读取 request/response Body。
- `response.body.mock()` 虽生成响应，但必须写在 `http-request`，请求不会发出。
- 同阶段所有命中项均执行：本地配置优先于插件；同来源从上到下。
- 同行多个 Action 从左到右；运行失败保留之前修改、跳过失败项并继续。参数/类型/正则配置错误会拒绝整条。
- 新旧 Rewrite 可混用，进入同一顺序；不会自动迁移旧语法。
- HTTPS host 必须在 `[Mitm] hostname = ...` 且用户安装并信任证书；证书固定、QUIC/HTTP3、应用自定义加密可能导致无法解密，这不是插件语法可绕过的边界。

完整语法见 `references/rewrite-v2.md`。

## Script 类型

### `http-request`
请求发出前。参数：`script-path`、`tag`、`requires-body`、`binary-body-mode`、`timeout`（默认 10s）、`argument`、`enable`。

对象：`$request.url/method/headers/body/h2_trailers`（trailers Build 927+），`$response` 为 undefined。

- `$done()`：中断请求。
- `$done({})`：原样继续。
- `$done({url,headers,h2_trailers,node,body})`：修改请求；未提供字段保留原值，空值清除。
- `$done({response:{status,headers,body}})`：直接响应。

### `http-response`
收到响应后。额外对象：`$response.status/headers/body/h2_trailers`。Body 需 `requires-body=true`；trailers Build 927+。

- `$done()`：中断。
- `$done({})`：原样继续。
- `$done({status,headers,h2_trailers,body})`：修改响应。

### 其他类型
- `cron`：5 段（分时日月周）或 6 段（秒分时日月周）。
- `network-changed`：网络变化触发；多条只执行第一条。
- `generic`：App 内手动触发，可带节点/策略组/规则上下文。

## Script API 清单

- 基础：`console.log`、`setTimeout`。
- 运行信息：`$loon`、`$script.name/startTime`。
- 配置：`$config.getConfig()`、`getConfig(policy,select)`（实际是切换）、`getSubPolicies`、`getSelectedPolicy`、`setRunningModel(0|1|2)`。
- 存储：`$persistentStore.write/read/remove`（字符串；`remove()` 清除脚本 API 保存的全部本地数据，慎用）。
- 通知：`$notification.post(title,subtitle,content,attach,delay)`；attach 可含 `openUrl`、`mediaUrl`、`clipboard`。
- HTTP：`$httpClient.get/post/head/delete/put/options/patch`；参数含 `timeout`、headers、body、`body-base64`、node、`binary-mode`、`auto-redirect`（660+）、`auto-cookie`（662+）、`alpn`（715+）。响应 `h2_trailers` Build 931+。
- 工具：`$utils.geoip`、`ipasn`、`ipaso`、`ungzip`。
- generic：`$environment.params.node/nodeInfo`。
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
- 生成器：https://nsloon.app/rewrite-builder/
- 脚本类型：https://nsloon.app/docs/Script/
- Script API：https://nsloon.app/docs/Script/script_api
