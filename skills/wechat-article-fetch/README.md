# WeChat Local Article Archiver

A local-only-by-default WeChat archive: original raw HTML, metadata-bearing Markdown and downloaded images. Optional Telegraph publication and R2 public image mirroring are separate, explicit opt-ins. The stable skill name remains `wechat-article-fetch`.

## Requirements and usage

Python 3.10+, curl, Node.js and npm. Extraction runs `npx --yes defuddle@0.19.4 parse ... -m -j`; the exact release was verified at [npm registry](https://registry.npmjs.org/defuddle/0.19.4). First run may fetch npm dependencies. No Telegraph/R2 credentials are required for local archiving.

```bash
python3 scripts/fetch-wechat.py 'https://mp.weixin.qq.com/s/ARTICLE'
python3 scripts/fetch-wechat.py 'https://mp.weixin.qq.com/s/ARTICLE' --output-dir ./archives
# Each external action requires its own explicit flag:
python3 scripts/fetch-wechat.py 'https://mp.weixin.qq.com/s/ARTICLE' --images r2
python3 scripts/fetch-wechat.py 'https://mp.weixin.qq.com/s/ARTICLE' --publish
python3 scripts/fetch-wechat.py 'https://mp.weixin.qq.com/s/ARTICLE' --images r2 --publish
# Existing Markdown must already use public HTTPS image URLs:
python3 scripts/publish-telegraph.py article.md --publish
```

Only WeChat URLs are automated (`/s/ID` and `/s?...`); this CLI does not fetch arbitrary websites or solve CAPTCHAs. Referer/mobile UA retries improve image compatibility, not guaranteed access.

## Storage and failure semantics

Output directory precedence: `--output-dir`, `WECHAT_ARTICLE_OUTPUT_DIR`, `$XDG_DATA_HOME/wechat-articles`, then `~/.local/share/wechat-articles`.

```text
wechat-articles/
├── title-<URL-sha256-prefix>-<raw-sha256-prefix>.html
├── title-<URL-sha256-prefix>-<raw-sha256-prefix>.md
└── assets/title-<URL-sha256-prefix>/001-<image-url-hash>.jpg
```

Frontmatter records title, source URL, UTC fetch time, author and publication date (`unknown` when absent). Original response bytes are retained; raw HTML is untrusted and should not be executed. Changing raw content creates a new snapshot; repeating identical input reuses the filename atomically. Different source URLs avoid same-title overwrites. Hashes are 16 hex characters for article/revision identity; exact URL identity deliberately does not strip query parameters. Image cache identity is source URL, not refreshed remote bytes.

Move HTML, Markdown and `assets/` together. Image download errors retain the original remote URL and make the archive partial. The 20 MiB cap, bounded anti-hotlink retries and unique atomic `.part` files protect downloads. HTTP 200 challenge/deletion pages, missing titles and insufficient bodies fail validation rather than masquerading as success. Structured short/image articles are accepted; borderline extraction needs manual inspection.

R2 uploads begin only **after** local HTML, Markdown and successful images have been saved. Missing R2 settings, failed uploads or failed Telegraph calls leave these files intact. Exit codes: `0` completed, `1` partial images or external failure with local archive retained, `2` fetch/validation/storage failure.

## Optional publication and compatibility

- Credentials never enable publication. `--images r2` alone does not create a Telegraph page; `--publish` alone does not mirror to R2.
- `--no-telegraph` is a backward-compatible, redundant local-default flag; combining it with `--publish` is rejected.
- Old archives are untouched. To retain the previous location explicitly set `WECHAT_ARTICLE_OUTPUT_DIR=~/.hermes/wechat-articles` (expand `~` normally or quote it; the script expands it).
- Telegraph credentials: `TELEGRAPH_ACCESS_TOKEN`, then `TELEGRAPH_TOKEN_PATH`; legacy `~/.hermes/telegraph_token` fallback is read only after explicit publication.
- Standalone publication now requires `--publish`, understands new frontmatter and legacy headers, and rejects relative image paths. The simple Telegraph renderer is not a full Markdown implementation.
- R2 public endpoints must be HTTPS and cannot contain credentials/query/fragment or be S3 API endpoints. `r2.dev` is **rate-limited, development-only**, not suitable for production delivery.

Load details as needed: [R2 setup, billing, troubleshooting and official sources](references/cloudflare-r2-setup.md), [Telegraph](references/telegraph-api.md), [browser fallback](references/js-rendered-pages.md).

## Tests (no network, uploads or publication)

```bash
python3 -m compileall -q scripts
PYTHONPATH=scripts python3 -m unittest discover -s scripts -p 'test_*.py' -v
PYTHONPATH=scripts python3 scripts/test_image_assets.py
python3 scripts/fetch-wechat.py --help
python3 scripts/publish-telegraph.py --help
```

Repository discovery only: `npx skills@latest add . --list` from the repository root. This does not install/update the local skill.

## License

MIT
