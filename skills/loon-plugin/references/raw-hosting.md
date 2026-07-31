# Loon 插件远程托管

## 安装入口

```text
https://raw.githubusercontent.com/<user>/<repo>/main/path/Name.plugin
https://cdn.jsdelivr.net/gh/<user>/<repo>@main/path/Name.plugin
```

Deep link 中应对插件 URL 做百分号编码：

```text
loon://import?plugin=<percent-encoded-plugin-url>
```

## 原则

- GitHub raw 是否 200 只取决于仓库、分支、大小写和真实路径；`plugin/` 目录名本身不会导致 404。
- 私有仓库通常无法供 Loon 匿名订阅；使用公开仓库、自建静态托管或可访问 CDN。
- `script-path`、icon、jq/mock file 等所有资源都必须可从设备访问。
- 浮动 `main` 便于自动更新但可能受缓存影响；可复现发布用 tag/commit，更新时同步插件版本/URL。
- `.lpx` 社区托管形式需以目标 TestFlight 真机导入结果为准；不要仅凭扩展名推断内容格式。

## 发布检查

```bash
curl -sSIL "https://raw.githubusercontent.com/USER/REPO/main/path/Name.plugin" | head
curl -sSIL "https://raw.githubusercontent.com/USER/REPO/main/scripts/foo.js" | head
curl -fsSL "URL" | head
```

逐一检查：状态码、Content-Type、内容不是登录页/错误页、大小写、分支、相对资源路径。

## 缓存排障

1. 直接 GET 比较线上内容。
2. 固定 commit URL 判断是否 CDN/branch 缓存。
3. 提升插件日期/版本标识并刷新资源。
4. Loon 删除并重新拉取，查看日志。

## 社区中心

可莉中心常用 `loon://import?plugin=` 与 `.lpx` 托管。Cloudflare 可能阻止自动抓取；优先官方文档、公开仓库和用户授权导出的样本，不反复绕过反爬。
