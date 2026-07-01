# Telegra.ph API 参考

Telegra.ph 是 Telegram 官方发布的极简发布平台，API 无需认证（只需一个无状态 token）。

## 创建账号（仅一次）

```http
POST https://api.telegra.ph/createAccount
Params: short_name, author_name?, author_url?
Returns: { ok: true, result: { access_token, short_name, author_name, author_url, auth_url } }
```

Token 永久有效，保存到 `~/.hermes/telegraph_token`。

## 创建页面

```http
POST https://api.telegra.ph/createPage
Body (JSON): {
  access_token: string,
  title: string,
  author_name?: string,
  author_url?: string,
  content: Node[],          // 需要是 JSON array, 非 string
  return_content?: boolean
}
Returns: { ok: true, result: { path, url, title, description, author_name, ... } }
```

**注意**: `content` 必须是 JSON 数组（Node 对象），不是字符串！URL 参数传会被截断——必须用 POST 发 JSON body。

## 支持的 Node 类型

| tag | children | attrs |
|-----|----------|-------|
| `p`, `h2`, `h3`, `h4` | 字符串数组（文本） | — |
| `img` | — | `{ src: string }` |
| `figure` | Node 数组（含 img + figcaption） | — |
| `figcaption` | 字符串数组 | — |
| `ul`, `ol` | li 节点数组 | — |
| `li` | p 节点数组 | — |
| `pre` | code 节点数组 | — |
| `code` | 字符串数组 | — |
| `blockquote` | p 节点数组 | — |
| `aside` | p 节点数组 | — |
| `hr` | — | — |
| `br` | — | — |
| `a` | 字符串 | `{ href: string }` |
| `strong`, `em`, `s`, `u`, `del`, `sub`, `sup` | 字符串 | — |

## 注意事项

- **不支持**: `<table>`, `<form>`, `<input>`, `<iframe>`, `<video>`, `<audio>`, `<canvas>`, `<svg>`
- **不支持**: CSS 样式、自定义字体、颜色
- **路径最大 64 字符**（URL slug）
- **title 最大 256 字符**
- 图片必须 HTTPS，建议来自微信图床 `mmbiz.qpic.cn`（Telegra.ph 有白名单）
- 调用频率限制：未公开，但合理使用（每秒 < 1 请求）不会触发
