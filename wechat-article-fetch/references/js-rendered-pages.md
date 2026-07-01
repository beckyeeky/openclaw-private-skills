# JS 渲染页面内容提取

## 适用场景

重度依赖客户端渲染的 SPA（Shadow DOM / Web Components），包括但不限于：

- **Gemini 分享链接** (`gemini.google.com/share/*`) — Google 的 Web Components 架构
- 部分 React/Vue 单页应用
- ChatGPT 分享链接等

这些页面用 curl 只能拿到骨架 HTML，defuddle/web_extract 输出为空。需用浏览器工具提取内容。

## 通用流程

1. `browser_navigate(url)` — 加载页面
2. 立即调用 `browser_vision(annotate=true, question="提取页面上全部可见文字")` — **不要先做 snapshot 或 scroll**
3. 从 analysis 字段获取文字内容
4. 从 annotations 字段获取元素 labels（如 `e19 = "You said ..."`），它们常包含长文本片段

## 关键陷阱

### 1. 首次加载窗口很窄

部分 SPA 有 bot 检测逻辑，加载后很快（<5s）限流或清空内容。**必须在 navigate 后立即 vision**，不要做任何中间操作。

### 2. 滚动即空白

Gemini 分享页面在首次 vision 后如果执行 scroll，再次 vision 会返回全空白页。如果需要更多内容，应在同一页面上多次 vision（不同区域），或重新 navigate 重新加载。

### 3. 内容分页/折叠

长对话可能被 "Sign in" 按钮截断。未登录用户只能看到前几条消息。解决方案：要求用户登录后提供完整截图或直接导出。

### 4. Shadow DOM 不可见

`:innerText` 和 `:innerHTML` 在 Shadow DOM 中为空。不能用 JS console 提取。browser_vision 截图 + vision model 是唯一可靠的读取方式。

### 5. Annotations 补充

`browser_vision(annotate=true)` 返回的 annotations arrays 中包含交互元素 labels。这些 labels 的 `name` 字段常携带长文本（如邮件正文），是截图 analysis 未覆盖内容的重要补充。

## Gemini 分享链接特例

- 短链接模式：`g.co/gemini/share/XXXXX` → 自动 301 到 `gemini.google.com/share/XXXXX`
- 元数据出现在 heading `[ref=e6]` 中
- 对话气泡作为 `heading` 元素出现在 snapshot 中，但内容被省略显示
- vision 截图 + annotations 联合提取效果最好

## 替代方案

如果 browser_vision 不可用或有 bot 检测限制：
- 让用户安装导出插件 / 自行复制粘贴
- 找平台官方导出功能（Gemini/OpenAI share links 通常无官方导出
