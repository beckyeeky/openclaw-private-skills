# Reference sources

## Local (this VPS)

| Path | Role |
|------|------|
| `/root/repos/TabulaBili-Loon/` | Full modern plugin: Argument, request scrub, capture exclusion, risk probe, AGENTS.md |
| `/root/repos/TabulaBili-Loon/TabulaBili.plugin` | Install entry + MitM + Script lines |
| `/root/repos/TabulaBili-Loon/AGENTS.md` | Decision log, raw 404, App access_key resign, verification |

## Community

| URL | Role |
|-----|------|
| https://hub.kelee.one/ | 可莉插件中心（安装 UX、分类、`loon://import`） |
| https://github.com/luestr/ProxyResource | 可莉资源索引 + Loon 配置模板 `Tool/Loon/Lcf/` |
| https://github.com/deezertidal/private | 大量根目录 `*.plugin` 实战格式（rewrite reject / script / MITM） |

## Sample formats observed

**deezertidal root plugins:** often `#!name=` without spaces; `[MITM]`; long `[URL Rewrite]` reject lists; compact `requires-body=1`.

**TabulaBili / 可莉-aligned:** `#!name =` with spaces; `[MitM]`; `script-path =` with spaces; `[Argument]` select/switch; remote raw scripts.

**When writing new plugins for Beck:** prefer Tabula/可莉 spacing + `[MitM]` + root install entry + `AGENTS.md`.

## License / ethics

- 可莉 / ProxyResource: CC BY-NC-SA 等限制 — 学习接口与结构，勿整包商用搬运、注意其「学习研究」声明。
- deezertidal 等仓库含解锁/破解向脚本 — **本 skill 只借用 .plugin 语法与 MitM 模式**，不指导绕过付费版权保护作为产品目标。
- 自研插件写清目标（去广告 / 去个性化 / 调试探针），保留上游致谢。
