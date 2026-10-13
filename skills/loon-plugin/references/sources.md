# Reference sources

## 官方（权威，匿名公开）

| URL | 用途 |
|-----|------|
| https://nsloon.app/docs/Plugin/ | 插件元数据、`[Argument]`、`[General]`、`[IP Rewrite]`、发布 |
| https://nsloon.app/docs/Rewrite/rewrite_v2 | Rewrite V2 全语法（3.5.1 (978)+） |
| https://nsloon.app/docs/Rewrite/ | Rewrite 旧语法（978 之前，仅维护旧配置） |
| https://nsloon.app/docs/Script/script_v2 | Script V2（3.5.1 (983)+，默认语法） |
| https://nsloon.app/docs/Script/ | Script 旧语法（≤982，仅维护旧配置） |
| https://nsloon.app/docs/Script/script_api | Script API 与 build 门槛 |
| https://nsloon.app/rewrite-builder/ | Rewrite 生成器（仅浏览器本地生成，不执行） |
| https://nsloon.app/docs/MitM/ | `[MitM] hostname` |
| https://nsloon.app/docs/Scheme/ | `loon://import?plugin=encode(url)` |

## 社区（仅作格式参考，非权威）

| URL | Role |
|-----|------|
| https://hub.kelee.one/ | 可莉插件中心（安装 UX、分类、`loon://import`） |
| https://github.com/luestr/ProxyResource | 可莉资源索引 + Loon 配置模板 `Tool/Loon/Lcf/` |
| https://github.com/deezertidal/private | 大量根目录 `*.plugin` 实战格式（rewrite reject / script / MITM） |

## Sample formats observed

**deezertidal root plugins:** often `#!name=` without spaces; `[MITM]`（全大写；官方文档 `[Mitm]`（Plugin 示例）与 `[MitM]`（MitM 页）并存、未声明大小写敏感，本仓不判其非法，兼容性未真机验证）; long `[URL Rewrite]` reject lists; compact `requires-body=1`（旧语法）.

**TabulaBili / 可莉-aligned:** `#!name =` with spaces; `[MitM]`; 新版 `script(...)` / `with`；`[Argument]` select/switch; remote raw scripts.

**When writing new plugins:** prefer official spacing + MitM 段落（本仓约定 `[MitM]`；官方两处分别写作 `[Mitm]`/`[MitM]`，大小写不判非法）+ 根目录安装入口；新 Rewrite 用 `request`/`response` + 位置参数，新 Script 用 `script(...)` + `with`（`with` 可省略）。

> 私有参考样本（一个真实 Loon 插件项目，含 `[Argument]`、请求清洗、风控探针与真机验证日志）不写进本仓、不落盘路径；需要时向维护者索取，按 `{baseDir}` 约定引用，**不要假设任何固定 checkout 路径**。
