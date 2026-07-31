# Rewrite V2 完整速查（Loon 3.5.1 (978)+）

官方文档：https://nsloon.app/docs/Rewrite/rewrite_v2  
官方生成器：https://nsloon.app/rewrite-builder/（仅在浏览器本地生成，不上传配置；不执行配置，须在 Loon 看日志验证）

## 语法

```text
<phase> if <condition> then <action> [| <action> ...]
```

每条必须单行。`phase` 为 `http-request` 或 `http-response`。

## 条件

比较：`==`（精确）、`~=`（正则查找）。逻辑：`&&`、`||`、`()`；优先级：比较 > `&&` > `||`。

内置变量：
- 两阶段：`${url}`、`${request.method}`、`${request.header['name']}`。
- 仅响应：`${response.status}`、`${response.header['name']}`。
- Header 名不区分大小写，不存在为 null。
- 条件不能读取 Body。

值：String（必须双引号）、Number、Boolean、null、Regex `/pattern/ims`。双引号字符串会展开变量并支持 `\"`、`\\`、`\n`、`\r`、`\t`、`\${`；反引号原始字符串不转义、不展开，连续两个反引号代表字面量反引号。新版不按空格拆行，不需 `\x20`。

正则字面量不展开变量；动态正则写 `${url} ~= ${urlPattern}`。

捕获：
```text
${url} ~= /item\/(\d+)/ as item
```
`${item.0}` 完整命中，`${item.1}` 起为捕获组。名称同条唯一、不可与插件参数重名；下标不得越界；捕获必须经过全部成功路径，不能仅放在 `||` 可选分支。可选组未命中会令引用它的 Action 失败，但后续 Action 继续。

## Action 全表

### URL
```text
url.replace(pattern=/old/, replacement="new")
redirect(status=302, location="https://new.example.com")
```
- `redirect` status 仅 302/307。
- redirect 条件必须有且仅有一个**必选 URL 正则**；location 替换该 URL 正则的命中范围，不一定是整条 URL。

### Reject（固定组合）
```text
reject(status=404, body="empty")
reject(status=200, body="empty"|"image"|"json-object"|"json-array"|"video")
```
含义：空 Body、1×1 GIF、`{}`、`[]`、空白视频。

### Header
```text
request.header.add(name="X", value="v")
request.header.set(name="X", value="v")
request.header.delete(name="X")
request.header.replace(name="X", pattern=/old/, replacement="new")
```
响应对应 `response.header.*`。add 可重复添加，set 覆盖，delete 删除，replace 只替换值中命中部分。

### Body 正则
```text
request.body.replace(pattern=/old/, replacement="new")
response.body.replace(pattern=/old/, replacement="new")
```

### JSON
```text
request.json.add(path="data.price", value=9.99)
request.json.delete(path="data.ads")
request.json.replace(path="data.price", value=${price})
request.json.jq(filter=".data.ads = []")
response.json.jq(file="response-filter.jq")
```
响应对应 `response.json.*`。仅有效 JSON 生效。Key Path 点分，数组 `[n]`；value 支持 String/Number/Boolean/null/变量。jq 接 `filter` 或插件内 `file`。

### Mock
```text
request.body.mock(type="json", data=`{"price":9.99}`)
request.body.mock(type="json", file="request_body.json", base64=false)
response.body.mock(type="json", data=`{"code":0}`, status=200)
```
- `data` 与 `file` 二选一；大数据用插件文件。
- `base64` 默认 false；response status 默认 200。
- type：`json,text,css,html,javascript,plain,png,gif,jpeg,tiff,svg,mp4,form-data`。
- `response.body.mock` 必须在 `http-request` 阶段，直接结束请求。

## 插件参数

```text
[Argument]
enabled = switch,true,tag=启用
price = input,9.99,type=number,tag=价格
region = select,"CN","US",tag=地区

[Rewrite]
http-response if ${enabled} == true then response.json.replace(path="data.price", value=${price})
```
input/select 默认 String；`type=number` 才是 Number；switch 是 Boolean。

## 组合与顺序

```text
http-request if ${url} ~= /^https:\/\/api\.example\.com/ then request.header.set(name="X-Loon", value="true") | request.header.delete(name="Cookie")
```
同条 Action 左→右；同阶段所有命中 Rewrite 按配置序执行。本地配置 > 插件。后写可覆盖先写。

## 旧语法迁移

| 旧 | V2 |
|---|---|
| `header` | `url.replace(...)` |
| `302` / `307` | `redirect(...)` |
| `reject-*` | `reject(...)` |
| `header-*` | `request.header.*` |
| `response-header-*` | `response.header.*` |
| `request-body-replace-regex` | `request.body.replace(...)` |
| `response-body-replace-regex` | `response.body.replace(...)` |
| `request-body-json-*` | `request.json.*` |
| `response-body-json-*` | `response.json.*` |
| `mock-request-body` | `request.body.mock(...)` |
| `mock-response-body` | `response.body.mock(...)` |

旧语法仍兼容并可混用，Loon 不自动迁移。

## 生成器工作流

1. 选请求/响应阶段。
2. 添加条件和 AND/OR 条件组；正则按需启用 i/m/s 与 `as` 捕获。
3. 添加 Action 并按执行顺序排列。
4. 可勾选输出 `[Rewrite]` 段落标题，复制结果。
5. 补 `[Argument]`、插件元数据、HTTPS `[Mitm] hostname` 和外部 jq/mock 文件。
6. Loon 3.5.1 (978)+ 加载，检查配置错误和运行日志；生成器本身不验证真实流量。

## 何时改用 Script

需要以下任一能力：条件读取 Body、任意算法/签名、跨请求持久状态、通知、主动 HTTP 请求、复杂二进制处理、错误恢复逻辑。否则优先 Rewrite V2。
