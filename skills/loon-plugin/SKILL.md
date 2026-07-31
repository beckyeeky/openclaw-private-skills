---
name: loon-plugin
description: >-
  构建、审计、调试、迁移、打包或发布 Loon 插件（.plugin/.lpx）的完整工程技能。覆盖最新版 TestFlight / Loon 3.5.1 (978)+：插件元数据与 [Argument]、Rewrite V2 和官方生成器、旧 Rewrite 迁移、[Script] 全类型与 Script API、[Mitm]/[Rule]/[Host]/[General]、能力边界、真机验证。用户提到 Loon 插件、复写、新复写语法、Rewrite Builder、MitM、Loon 脚本时触发；Surge/QX/Stash 仅在转换为 Loon 时使用。
license: MIT
metadata:
  version: 2.0.0
  official_baseline: "Loon 3.5.1 (978)+"
  tags: [loon, plugin, rewrite-v2, script, mitm, testflight]
---

# Loon Plugin Engineering

## 权威基线与加载规则

以官方文档标注的 **Loon 3.5.1 (978)+**（当前 TestFlight 新 Rewrite 基线）为准。用户提供更高 build 时，先查官方文档/生成器和该 build 日志；不要把传闻写成已发布能力。

开始任务时按需读取：

| 文件 | 何时读 |
|---|---|
| `references/capability-boundary.md` | 每次设计/审计；判断能否实现、选 Rewrite 或 Script |
| `references/rewrite-v2.md` | 涉及复写、迁移、生成器时；含全部条件/Action/限制 |
| `references/raw-hosting.md` | 发布、安装链接、远程资源时 |
| `references/sources.md` | 需要来源或社区样本时 |

官方入口：
- https://nsloon.app/docs/Plugin/
- https://nsloon.app/docs/Rewrite/rewrite_v2
- https://nsloon.app/rewrite-builder/
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
#!tag = 工具,复写
#!type = normal

[Argument]
enabled = switch,true,tag=启用
region = select,"CN","US",tag=地区
price = input,9.99,type=number,tag=价格

[Rewrite]
http-response if ${enabled} == true && ${url} ~= /^https:\/\/api\.example\.com\/profile$/ && ${response.status} == 200 then response.json.replace(path="data.price", value=${price})

[Script]
# 仅在 Rewrite 无法表达时添加

[Mitm]
hostname = api.example.com
```

插件可包含 `[General] [Rule] [Rewrite] [Host] [Script] [Mitm] [Argument]`。`#!type` 为 `normal` 或 3.5.0 (969)+ 的 `parser`。插件规则只能用 `DIRECT`、`REJECT` 系列、`PROXY`，省略默认 DIRECT。

## Rewrite V2 工作流

基本格式（必须单行）：

```text
<http-request|http-response> if <condition> then <action> [| <action> ...]
```

1. 在官方 [Rewrite 生成器](https://nsloon.app/rewrite-builder/) 选择阶段。
2. 组合 `==` / `~=`、`&&` / `||` / 括号和 `as name` 捕获。
3. 选择 Action：URL、redirect、reject、request/response Header、Body regex、JSON、jq、mock。
4. 检查阶段限制：条件不能读 Body；响应变量仅 response；`response.body.mock` 必须 request 阶段。
5. 检查类型：字符串双引号；数字不加引号；switch 是 Boolean；input/select 需 `type=number` 才是 Number。
6. 多 Action 左→右；多条均会执行且后项可覆盖前项；本地配置优先插件。
7. HTTPS 补 `[Mitm]`；真机加载看配置/运行日志。

不要只凭生成器判断有效：它只在浏览器本地生成文本，不执行，也不了解实际流量。

## Script 工作流

脚本类型：`http-request`、`http-response`、`cron`、`network-changed`、`generic`。

Canonical：

```text
[Script]
http-request ^https:\/\/api\.example\.com\/v1\/feed script-path=https://example.com/request.js,tag=请求处理,requires-body=false,binary-body-mode=false,timeout=10,argument=[{enabled}],enable={enabled}
http-response ^https:\/\/api\.example\.com\/v1\/feed script-path=https://example.com/response.js,tag=响应处理,requires-body=true,binary-body-mode=false,timeout=10
```

契约：
- 每条执行路径恰好一次 `$done`；异步回调完成后再 `$done`。
- `$done()` 中断；`$done({})` 原样继续，不要混淆。
- request 修改 `{url,headers,body,h2_trailers,node}`；可返回 `{response:{...}}`。
- response 修改 `{status,headers,body,h2_trailers}`。
- 未传字段保留，空对象/空字符串用于清除。
- Body 需 `requires-body=true`；二进制用 `binary-body-mode=true` / Uint8Array。
- 参数 `argument=[{x}]` 后按 `$argument.x` 读取；旧自由字符串参数可读 `$argument`。
- 不打印 Cookie/token；通知节流；存储 key 加插件命名空间；慎用会清空全部脚本存储的 `$persistentStore.remove()`。

Script API 全表和 build 门槛见能力边界文件。

## 冲突与执行顺序

- Rewrite V2 同阶段所有命中项执行，不是首条即停；后项可能覆盖先项。
- 新旧 Rewrite 可混排，按顺序执行，不自动迁移。
- 本地 Rewrite 优先于插件 Rewrite。
- 两个 HTTP Script 命中同一请求时可能互相覆盖；缩窄正则或做互斥排除。
- Rewrite 与 Script 同时修改同字段时必须真机验证顺序；若无必要，不叠加。
- 每条 Script `tag` 唯一；每个解密 host 纳入 `[Mitm]`。

## 调试顺序

1. **配置是否加载**：版本门槛、单行 Rewrite、参数类型/正则语法、远程文件 200。
2. **流量是否可见**：HTTP/HTTPS、MitM 证书、hostname、TLS pinning/QUIC、自定义加密。
3. **是否命中**：真实 URL/method/header/content-type 与正则；区分 App/Web。
4. **阶段是否正确**：请求/响应变量、mock 响应是否放 request。
5. **Body 是否可处理**：requires-body、JSON 是否有效、压缩/二进制、jq 文件路径。
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

- 所有 `script-path`、icon、jq/mock file 引用在目标安装环境可访问。
- 对每个远程 URL 做 HEAD/GET 验证；私有仓库通常不能匿名订阅。
- 安装：`loon://import?plugin=<percent-encoded-plugin-url>`。
- GitHub raw 路径是否可用取决于真实仓库路径和访问状态；不要宣称某个目录名天然 404。
- 可提供 jsDelivr 等镜像，但调试缓存时优先固定 commit URL 或更新版本号。

## 验收清单

- [ ] 目标处于 Loon 网络层能力边界内
- [ ] `#!loon_version = 3.5.1(978)`（若使用 Rewrite V2）
- [ ] 元数据、系统门槛、type 正确
- [ ] Argument 类型与引用一致
- [ ] 优先 Rewrite；Script 有明确必要性
- [ ] Rewrite 单行、阶段/变量/捕获/Action 均合法
- [ ] HTTPS host 完整加入 MitM
- [ ] Script 每路径一次 `$done`，Body/binary 配置正确
- [ ] 无敏感日志，状态/通知有命名空间与节流
- [ ] 无顺序覆盖和重复命中冲突
- [ ] 远程资源可访问
- [ ] 在目标 TestFlight build 真机命中并检查日志

## Bundled templates

- `templates/minimal-reject.plugin`：最小拒绝示例（使用前按 V2 更新/核验）
- `templates/request-response.plugin`：Argument + Script 骨架
- `templates/script-request.js`
- `templates/script-response-observe.js`
