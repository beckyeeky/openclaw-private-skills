# Loon plugin raw hosting

## Install entry (canonical)

```text
https://raw.githubusercontent.com/<user>/<repo>/main/<Name>.plugin
```

Deep link:

```text
loon://import?plugin=https://raw.githubusercontent.com/<user>/<repo>/main/<Name>.plugin
```

CDN fallback:

```text
https://cdn.jsdelivr.net/gh/<user>/<repo>@main/<Name>.plugin
```

## Path matrix (GitHub raw)

| Path | Typical raw result |
|------|--------------------|
| `/Name.plugin` (repo root) | 200 — **use this** |
| `/plugin/Name.plugin` | **404** often |
| `/plugin/Name.conf` | 200 often |
| `/scripts/*.js` | 200 |
| jsDelivr any path under repo | usually 200 |

## Publish checklist

```bash
# after editing plugin file
cp Name.plugin plugin/Name.plugin   # keep mirror in sync

curl -sSIL "https://raw.githubusercontent.com/USER/REPO/main/Name.plugin" | head -8
curl -sSIL "https://raw.githubusercontent.com/USER/REPO/main/scripts/foo.js" | head -8
```

- Repo must be **public** for Loon remote install (or host elsewhere).
- `script-path` URLs must stay reachable; pin branch/tag if needed.
- Prefer root install file even if you also keep `plugin/` copy for layout aesthetics.

## 可莉中心风格

- 用户向：https://hub.kelee.one/ 安装按钮 → `loon://import?plugin=https://kelee.one/Tool/Loon/Lpx/....lpx`
- 索引库：https://github.com/luestr/ProxyResource （配置模板为主；插件实体多在 kelee 托管）
- 爬虫常被 Cloudflare 403：开发时用本地已有样本 / 用户导出，勿依赖自动化扒 kelee.one
