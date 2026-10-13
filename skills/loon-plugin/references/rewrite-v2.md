# Rewrite V2 完整速查（Loon 3.5.1 (978)+）

官方文档：https://nsloon.app/docs/Rewrite/rewrite_v2
官方生成器：https://nsloon.app/rewrite-builder/（仅在浏览器本地生成，不上传配置；不执行配置，须在 Loon 看日志验证）

> **两个致命约定（先说清楚）**
>
> 1. **阶段关键字只有 `request` / `response`。** 官方原文：「开发阶段曾使用过但未正式发布的 `http-request`、`http-response` 和命名参数写法不属于兼容范围。」写成 `http-request` / `http-response` 会被判为配置错误。
> 2. **所有 Action 只使用位置参数。** 官方原文：「参数必须按照方法声明中的顺序填写，不允许填写参数名称。」`redirect(status=302, location="…")` 无效，必须 `redirect(302, "…")`。
>
> 官方「配置检查」明确：**参数数量、参数类型或正则错误属于配置错误，会在加载时拒绝整条 Rewrite**，不会留到运行时。因此上述两类写法会导致整条规则不可用。

## 语法

```text
<phase> if <condition> then <action> [| <action> ...]
```

- 每条必须单行。
- `phase` 为 `request`（请求发出前）或 `response`（收到响应 Header 后）。
- 一条普通 Rewrite **不能同时包含请求 Action 和响应 Action**，请求/响应通常分成两条写。
- 多个 Action 用 `|` 连接，从左到右执行。

官方「执行阶段」表：

| 阶段 | 执行时机 | 可用数据 |
|---|---|---|
| `request` | 请求发出前 | URL、请求方法、请求 Header |
| `response` | 收到响应 Header 后 | 请求数据、响应状态码、响应 Header |

```text
request if ${url} ~= /^https:\/\/example\.com/ then request.header.set("X-Test", "request")
response if ${url} ~= /^https:\/\/example\.com/ then response.header.set("X-Test", "response")
```

## 条件表达式

比较：`==`（类型一致的精确比较）、`~=`（正则查找匹配）。
逻辑：`&&`、`||`、`()`。优先级：比较 > `&&` > `||`。同时用 `&&` / `||` 时用括号明确意图。
`~=` 是「查找匹配」，需要整串匹配时自行加 `^` / `$`。

内置变量：

| 变量 | 类型 | request | response |
|---|---|---|---|
| `${url}` | String | ✓ | ✓ |
| `${request.method}` | String | ✓ | ✓ |
| `${request.header['name']}` | String 或 null | ✓ | ✓ |
| `${response.status}` | Number | — | ✓ |
| `${response.header['name']}` | String 或 null | — | ✓ |

- Header 名查找不区分大小写；变量表达式里的 Header 名用**单引号**：`${request.header['User-Agent']}`。
- `request` 阶段不能引用尚未生成的响应变量。
- 当前版本**不支持在 `if` 条件中读取 Body**（`${request.body}` / `${response.body}` / JSON Key Path 均不可用）。需要读 Body 条件时改用 Script。

### Header 值类型

存在时是 String，不存在是 `null`，存在但为空是 `""`（不等于 `null`）。

```text
request if ${request.header['X-Optional']} == null then reject(403)
request if ${request.header['X-Optional']} == "" then reject(403)
```

`==` 右值可选类型：String `"CN"`、Null `null`、Variable `${region}`、Template `"Bearer ${token}"`、Raw String `` `literal ${region}` ``。
`~=` 右值必须是 Regex。
**Number / Boolean 不能直接与 Header 比较**；插件变量用于 Header 比较时也必须是 String。

### 正则

格式 `/pattern/flags`，支持 `i`（忽略大小写）、`m`（多行）、`s`（点号匹配换行）。
正则字面量中**不展开** `${...}`；需要动态正则时把变量直接放在 `~=` 右侧：`request if ${url} ~= ${urlPattern} then …`。

### 值与字符串

| 类型 | 示例 |
|---|---|
| String | `"hello world"`（必须双引号） |
| Number | `200`、`9.99` |
| Boolean | `true`、`false` |
| Null | `null` |
| Regex | `/^https:\/\/example\.com/i` |

`9.99` 是 Number，`"9.99"` 是 String。

双引号字符串支持 `${...}` 模板与转义：`\"`、`\\`、`\n`、`\r`、`\t`、`\${`（字面量 `${`）。
反引号原始字符串：不处理反斜杠转义、不展开 `${...}`，逗号/等号/括号/双引号都是普通字符；**两个连续反引号表示一个字面量反引号**。固定 JSON/HTML 用它最省事。
新版语法不按空格拆行，**不再需要 `\x20`**。

### 插件参数

```text
[Argument]
enabled = switch,true,tag=启用
price = input,9.99,type=number,tag=价格
region = select,"CN","US","JP",tag=地区
level = select,1,2,3,type=number,tag=等级

[Rewrite]
response if ${enabled} == true && ${level} == 2 && ${request.header['X-Region']} == ${region} then response.json.replace("data.price", ${price})
```

- `input` / `select` 默认 String；要返回数字用 `type=number`；`switch` 是 Boolean。
- 参数只作为有类型数据使用，不会被重新解析成条件或 Action，也不会二次展开。
- 本地 Rewrite 没有参数来源，只能用内置变量和本条正则捕获。

### 条件正则捕获

在 `~=` 后加 `as <name>` 保存捕获：

```text
request if ${url} ~= /^https:\/\/api\.shop\.com\/item\/(\d+)/ as item then request.header.set("X-Item-ID", "${item.1}")
```

`${item.0}` 完整匹配，`${item.1}` 起为捕获组。

使用限制（加载时校验）：

- `as` 只能用于 `~=` 正则条件。
- 捕获名在同一条 Rewrite 中唯一。
- 捕获名不能与插件参数重名。
- 捕获下标不能超过正则的捕获组数量。
- 被 Action 引用的捕获条件必须经过表达式的**所有成功路径**，不能只位于 `||` 的可选分支中。

```text
# 有效
request if (${request.method} == "GET" || ${request.method} == "POST") && ${url} ~= /item\/(\d+)/ as item then request.header.set("X-Item", "${item.1}")

# 无效：捕获只在一个可选分支
request if ${url} ~= /item\/(\d+)/ as item || ${request.header['X-Debug']} == "true" then request.header.set("X-Item", "${item.1}")
```

若正则整体匹配成功但被引用的可选捕获组没有值，**该 Action 运行失败并跳过，后续 Action 继续**。

### 条件捕获 vs Action 捕获

| 来源 | 声明 | 引用 |
|---|---|---|
| `if` 条件正则 | `~= /.../ as item` | `${item.0}`、`${item.1}`，作用于本条 Rewrite 的 Action |
| Action 自带正则（Header/Body Replace） | Action 的 Regex 参数 | `$0`、`$1`，只作用于该 Action 的替换参数 |

`$n` 不是通用变量，不能跨 Action 使用；`url.replace("$1")` 是无效配置。

## Action 全表（全部位置参数）

```text
url.replace(String)
redirect(Number, String)
reject(Number[, String])
reject_img(Number)
reject_dict(Number)
reject_array(Number)
reject_video(Number)

request.header.add(String, String)
request.header.set(String, String)
request.header.del(String)
request.header.replace(String, Regex, RegexReplacement)
response.header.add/set/del/replace(同上)

request.body.replace(Regex, RegexReplacement)
response.body.replace(Regex, RegexReplacement)

request.json.add(String, Any)
request.json.delete(String)
request.json.replace(String, Any)
request.json.jq(String)
request.json.jq_file(String)
response.json.add/delete/replace/jq/jq_file(同上)

request.body.mock(String, String[, Boolean])
request.body.mock_file(String, String[, Boolean])
response.body.mock(String, String[, Number[, Boolean]])
response.body.mock_file(String, String[, Number[, Boolean]])
```

可选参数**只能从最右侧开始省略**；声明里的 `[...]` 表示尾部可选，不是要写进配置的字符。

### 批量数组参数

Header、Body 正则替换、JSON 修改支持一次配置多组，用数组表示：

```text
request if ${url} ~= /api/ then request.header.set(["X-A", "X-B"], ["1", "2"])
response if ${url} ~= /api/ then response.body.replace([/false/, /disabled/], ["true", "enabled"])
response if ${url} ~= /api/ then response.json.add(["data.a", "data.b"], [1, true])
```

支持批量的 Action：`request/response.header.add/set/del/replace`、`request/response.body.replace`、`request/response.json.add/delete/replace`。

规则：

- 同一个 Action 的参数必须**全数组或全单值**，不能混用。
- 数组长度必须一致，按相同下标配对执行。
- 数组不能为空、不能嵌套。
- 每个元素仍需符合该位置的类型。
- 每个 JSON Key Path 单独校验。

### URL 修改

```text
request if ${url} ~= /^https:\/\/old\.example\.com(\/.*)$/ as urlMatch then url.replace("https://new.example.com${urlMatch.1}")
request if ${url} ~= /^http:\/\/example\.com/ then redirect(302, "https://api.example.com")
```

- `url.replace` / `redirect` 的条件中必须有且只有**一个所有成功路径都经过的 `${url} ~= /.../`** 必选 URL 正则，它就是替换/重定向的范围；未命中的 URL 部分保留。
- 该 URL 正则不能位于 `||` 的可选分支。
- `url.replace` 参数中**不能使用 `$n`**；需要捕获时用 `as` + `${名称.n}`。
- `redirect` 状态码当前仅支持 **302 / 307**。
- 例：`http://example.com/item/123?region=CN` 用上面的 redirect 生成 `https://api.example.com/item/123?region=CN`。

### Reject（系列，不要再拼成魔法字符串）

| Action | 响应内容 |
|---|---|
| `reject(status)` | 指定状态码、空 Body |
| `reject(status, body)` | 指定状态码和 UTF-8 文本 |
| `reject_img(status)` | 1×1 GIF |
| `reject_dict(status)` | JSON 对象 `{}` |
| `reject_array(status)` | JSON 数组 `[]` |
| `reject_video(status)` | 空白视频 |

- 状态码必须是 100–599 的整数。
- `reject(200, "{}")` 返回**普通文本**；需要 JSON Content-Type 时用 `reject_dict(200)` / `reject_array(200)`。
- 不存在 `body="empty"|"image"|"json-object"|"json-array"|"video"` 这种取值，它们分别对应 `reject(status)`、`reject_img`、`reject_dict`、`reject_array`、`reject_video`。

```text
request if ${url} ~= /^https:\/\/example\.com\/ads/ then reject_dict(200)
request if ${url} ~= /^https:\/\/example\.com\/blocked/ then reject(451, "Unavailable for legal reasons")
```

### Header

```text
request if ${url} ~= /^https:\/\/example\.com/ then request.header.add("X-Loon", "true")
request if ${url} ~= /^https:\/\/example\.com/ then request.header.set("User-Agent", "Loon")
request if ${url} ~= /^https:\/\/example\.com/ then request.header.del("Cookie")
request if ${url} ~= /^https:\/\/example\.com/ then request.header.replace("User-Agent", /iPhone OS (\d+)/, "iPhone OS $1")
```

响应对应 `response.header.*`。参数顺序：`add/set` = 名称、值；`del` = 名称（**官方名称是 `del`，不是 `delete`**）；`replace` = 名称、正则、替换内容。
`header.replace` 的替换内容支持当前 Action 的 `$0`–`$n`，也支持 `${...}` 变量。

### Body 正则替换

```text
request if ${url} ~= /^https:\/\/example\.com/ then request.body.replace(/"price":\s*([0-9.]+)/, "\"originalPrice\":$1")
response if ${url} ~= /^https:\/\/example\.com/ then response.body.replace(/"enabled":\s*(false)/, "\"enabled\":true")
```

参数顺序：`Regex, RegexReplacement`。替换内容里的 `$0`/`$1…$n` 来自该 Action 自带正则，也允许 `${...}`。

### JSON

```text
request if ${url} ~= /^https:\/\/example\.com/ then request.json.add("data.price", 9.99)
request if ${url} ~= /^https:\/\/example\.com/ then request.json.delete("data.ads")
request if ${url} ~= /^https:\/\/example\.com/ then request.json.replace("data.price", ${price})
request if ${url} ~= /^https:\/\/example\.com/ then request.json.jq(".data.ads = []")
request if ${url} ~= /^https:\/\/example\.com/ then request.json.jq_file("request-filter.jq")
```

响应对应 `response.json.*`。

- 参数顺序：`add` = Key Path、值；`delete` = Key Path；`replace` = Key Path、值；`jq` = 内联 JQ；`jq_file` = **插件资源文件**（独立方法，不是 `jq(file=…)`）。
- 仅当 Body 是有效 JSON 时生效。
- Key Path 点分，数组下标 `[n]`，如 `data.apps[0].appName`。
- 值可以是 String / Number / Boolean / null / 变量。

### Mock 请求 Body

```text
request if ${url} ~= /^https:\/\/example\.com/ then request.body.mock("json", `{"price":9.99}`)
request if ${url} ~= /^https:\/\/example\.com/ then request.body.mock_file("json", "request_body.json")
request if ${url} ~= /^https:\/\/example\.com/ then request.body.mock("png", "iVBORw0KGgo...", true)
```

参数顺序：`request.body.mock(内容类型, 内联 Body[, Base64])`；`request.body.mock_file(内容类型, 资源文件[, Base64])`。Base64 默认 false。

### Mock 响应 Body —— 写作 `response` 阶段

```text
response if ${url} ~= /^https:\/\/example\.com/ then response.body.mock("json", `{"code":0}`, 200)
response if ${url} ~= /^https:\/\/example\.com/ then response.body.mock_file("json", "response_body.json", 200)
response if ${url} ~= /^https:\/\/api\.example\.com\/v1\/profile$/ then response.body.mock_file("json", "https://raw.githubusercontent.com/owner/repo/main/mock/profile.json", 200)
response if ${url} ~= /^https:\/\/example\.com\/avatar$/ then response.body.mock_file("png", "https://cdn.example.com/mock/avatar.base64", 200, true)
```

- 参数顺序：`response.body.mock(内容类型, 内联 Body[, 状态码[, Base64]])`；`response.body.mock_file(内容类型, 文件或远程 URL[, 状态码[, Base64]])`。状态码默认 200，Base64 默认 false；**要设 Base64 必须先写状态码**。
- `mock_file` 的文件参数**可以是远程 URL**（含 CDN 图片等二进制）。
- **阶段归属**：官方原文——「`response.body.mock(...)` 是特殊情况：**配置阶段仍写作 `response`**，但 Loon 会在请求发往上游前提前生成响应。」不要再把它写到 `request` 阶段。
- 含响应 Mock 的 Rewrite 组合限制：
  1. 一条 Rewrite 只能包含一个 `response.body.mock` 或 `response.body.mock_file`。
  2. 除 Mock 外，只能搭配 `response.header.*` Action。
  3. `if` 条件和 Mock 参数**不能引用** `${response.status}` / `${response.header['name']}`（响应此时尚未生成）。
  4. Loon 先生成 Mock 响应，再按配置顺序执行全部 Header Action。
  5. 最终会移除 `Transfer-Encoding`，并按实际 Body 重设 `Content-Length`。
- Mock Body 支持的内容类型：`json, text, text/event-stream, css, html, javascript, plain, png, gif, jpeg, tiff, svg, mp4, form-data`。中大型数据建议用 `*_file`。

## 执行规则

- 同一阶段**所有命中**的 Rewrite 按配置顺序执行，不是首条即停；后写可覆盖先写。
- 来源优先级：**本地配置 > 插件**；同一来源按从上到下。
- 同条 Rewrite 的多个 Action 左→右执行；某个 Action 运行失败时**保留此前修改、跳过该 Action 并记录错误、继续后续 Action**。
- 参数数量/类型/正则属于**配置错误**，加载时拒绝整条 Rewrite。

## 旧语法迁移

旧 Rewrite 语法（3.5.1 (978) 之前）仅用于维护旧配置，可与新语法混用，解析后进入同一执行序列，不自动迁移。

| 旧 Action | 新 Action |
|---|---|
| `header` | `url.replace(...)` |
| `302`、`307` | `redirect(...)` |
| `reject`、`reject-200` | `reject(...)` |
| `reject-img` | `reject_img(...)` |
| `reject-dict` | `reject_dict(...)` |
| `reject-array` | `reject_array(...)` |
| `reject-video` | `reject_video(...)` |
| `header-add`、`header-replace`、`header-del` | `request.header.*` |
| `response-header-*` | `response.header.*` |
| `request-body-replace-regex` | `request.body.replace(...)` |
| `response-body-replace-regex` | `response.body.replace(...)` |
| `request-body-json-*` | `request.json.*` |
| `response-body-json-*` | `response.json.*` |
| `mock-request-body` | `request.body.mock(...)` |
| `mock-response-body` | `response.body.mock(...)` |

- 旧 `header` / `302` / `307` 替换内容中的 `$n` 来自行首 URL 正则；转换时 Loon 会为该正则生成捕获名并把 `$n` 转成 `${名称.n}`。Action 自带正则的 `$n` 保持不变。
- 旧语法一行中连续填写的多组同类操作会合并为批量数组参数；只有一组时仍输出单值。

## 生成器工作流

1. 选请求/响应阶段。
2. 添加条件与 AND/OR 条件组；正则按需启用 i/m/s 与 `as` 捕获。
3. 添加 Action 并按执行顺序排列。
4. 可勾选输出 `[Rewrite]` 段落标题，复制结果。
5. 补 `[Argument]`、插件元数据、HTTPS `[MitM] hostname` 和外部 jq/mock 文件。
6. Loon 3.5.1 (978)+ 加载，检查配置错误和运行日志。

生成器页面标注 `LOON TOOL 3.5.1 (978)+`，输出示例为 `request if … then request.header.set("X-Loon", "true") | request.header.del("Cookie")`。生成器只在浏览器本地生成文本、不执行配置，**不能只凭它判断有效**。

## 何时改用 Script

需要以下任一能力时改用 Script（新版语法见 `references/capability-boundary.md`）：条件读取 Body、任意算法/签名、跨请求持久状态、通知、主动 HTTP 请求、复杂二进制处理、错误恢复逻辑。否则优先 Rewrite V2。
