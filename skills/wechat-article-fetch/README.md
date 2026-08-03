# WeChat Article Fetch

Fetch articles into a durable local Markdown archive, download embedded images with WeChat-compatible headers, and optionally publish image copies to Cloudflare R2 for external Markdown/Telegraph pages.

## Features

- **WeChat articles**: curl with MicroMessenger UA to bypass verification sliders
- **Local-first image archive**: every remote Markdown image is downloaded beside the article under `assets/<slug>/`
- **WeChat anti-hotlink handling**: retries with article/WeChat Referer and mobile User-Agent headers
- **Optional Cloudflare R2 publishing**: upload the already-saved local images using the dependency-free S3-compatible API
- **Telegra.ph publishing**: convert markdown to mobile-friendly Telegraph pages
- **JS-rendered pages**: Browser fallback for SPA/Shadow DOM pages (Gemini shares, etc.)

## Requirements

- `curl` (pre-installed on most systems)
- `node` + `npm` (pre-installed on most systems)
- `defuddle`: `npm install -g defuddle`
- Telegraph access token in `~/.hermes/telegraph_token` (optional)
- Cloudflare R2 environment variables (optional; only needed for `--images r2`)

## Usage

```bash
# Recommended default: save the article and all images locally
python3 scripts/fetch-wechat.py \
  "https://mp.weixin.qq.com/s/XXXXX" \
  --images local

# Save locally, upload image copies to R2, and use R2 URLs in Telegraph output
python3 scripts/fetch-wechat.py \
  "https://mp.weixin.qq.com/s/XXXXX" \
  --images r2

# Archive only, without attempting Telegraph publication
python3 scripts/fetch-wechat.py \
  "https://mp.weixin.qq.com/s/XXXXX" \
  --images local --no-telegraph

# Publish an existing markdown file (existing behavior)
python3 scripts/publish-telegraph.py ~/.hermes/wechat-articles/title.md
```

### Local archive layout

```text
~/.hermes/wechat-articles/
├── article-title.md
└── assets/
    └── article-title/
        ├── 001-<url-hash>.jpg
        └── 002-<url-hash>.webp
```

The Markdown uses relative paths, so move the `.md` file together with its `assets/` directory. Re-running a fetch reuses an existing asset with the same source URL hash.

## Cloudflare R2

R2 is optional. `--images r2` always keeps the local copy first; an individual upload failure does not delete or invalidate the local archive.

Required environment variables:

```text
CF_R2_ACCOUNT_ID
CF_R2_ACCESS_KEY_ID
CF_R2_SECRET_ACCESS_KEY
CF_R2_BUCKET
CF_R2_PUBLIC_BASE_URL
```

Optional:

```text
CF_R2_KEY_PREFIX=wechat
```

Use a bucket-scoped R2 token with Object Read & Write permission. `CF_R2_PUBLIC_BASE_URL` can initially be the Cloudflare-managed `https://<pub-id>.r2.dev` development URL; a custom domain can be added later without changing the bucket or upload credentials.

See the step-by-step guide:

- [`references/cloudflare-r2-setup.md`](references/cloudflare-r2-setup.md)

## Directory Structure

```text
wechat-article-fetch/
├── SKILL.md
├── README.md
├── scripts/
│   ├── fetch-wechat.py
│   ├── image_assets.py
│   └── publish-telegraph.py
└── references/
    ├── cloudflare-r2-setup.md
    ├── telegraph-api.md
    └── js-rendered-pages.md
```

## Design notes

- Local storage is the source of truth; R2 is an optional public mirror.
- Secrets are read only from environment variables and never written to article Markdown.
- Images are written through `.part` files and atomically renamed after validation.
- The R2 client uses Python's standard library and AWS Signature Version 4, so no extra S3 SDK is required.

## License

MIT
