# WeChat Article Fetch

Fetch any web article (WeChat, Medium, paywalled, etc.) via curl+defuddle → Markdown → optional Telegra.ph publishing.

## Features

- **WeChat articles**: Curl with MicroMessenger UA to bypass verification sliders
- **Non-WeChat articles**: Standard browser UA, same defuddle + Telegraph pipeline
- **Telegra.ph publishing**: Convert markdown to mobile-friendly Telegraph pages
- **JS-rendered pages**: Browser fallback for SPA/Shadow DOM pages (Gemini shares, etc.)
- **Smart image handling**: Preserves images from wechat CDN for Telegraph publishing

## Requirements

- `curl` (pre-installed on most systems)
- `node` + `npm` (pre-installed on most systems)
- `defuddle`: `npm install -g defuddle`
- Telegraph access token in `~/.hermes/telegraph_token` (for publishing)

## Directory Structure

```
wechat-article-fetch/
├── SKILL.md                  # Agent instructions
├── README.md
├── scripts/
│   ├── fetch-wechat.py       # Full pipeline: fetch → markdown → telegraph
│   └── publish-telegraph.py  # Standalone markdown-to-telegraph publisher
└── references/
    ├── telegraph-api.md      # Telegra.ph API reference
    └── js-rendered-pages.md  # Browser fallback for SPA pages
```

## Usage

```bash
# Fetch a WeChat article (full pipeline)
python3 scripts/fetch-wechat.py "https://mp.weixin.qq.com/s/XXXXX"

# Publish an existing markdown file to Telegraph
python3 scripts/publish-telegraph.py ~/.hermes/wechat-articles/title.md
```

## License

MIT
