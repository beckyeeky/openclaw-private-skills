# Optional Telegraph publication

Read only for an explicit request to publish publicly. Never infer consent from a token file or environment variable. Fetcher and standalone publisher require `--publish`; R2 additionally requires `--images r2`. Do not create a Telegraph account during archive tests.

## Credentials and request

Use `TELEGRAPH_ACCESS_TOKEN` or `TELEGRAPH_TOKEN_PATH`. For migration only, the legacy `~/.hermes/telegraph_token` is a fallback **after explicit publication consent**. Tokens are credentials, not harmless identifiers; never log or embed them in archives.

[Official API](https://telegra.ph/api): `createAccount` creates an account/token; `createPage` creates a public page using that token. Scripts POST JSON to `https://api.telegra.ph/createPage` with `access_token`, `title`, `author_name`, `author_url` and `content` (Node array). A token's presence does not authorize the operation.

## Limits and caveats

- API content limit is 64 KB; title limit is 256 characters. Do not silently truncate an archive. A publication error must preserve the local source and report failure; split manually only if requested.
- The bundled Markdown-to-Node converter is intentionally simple, not a complete Markdown renderer. Validate published layout when publication is actually requested; supported tags are documented in the API.
- Local `assets/...` references are not publicly accessible. Standalone publishing rejects non-HTTPS Markdown image URLs. Use `fetch-wechat.py --images r2 --publish` only when both actions were requested, or prepare an existing Markdown copy with public HTTPS image URLs.
- Without R2 mirroring, fetch publication uses original image URLs. WeChat hotlink protection or Telegraph behavior can still break them; no image whitelist or guaranteed compatibility is assumed.
- Failed image uploads fall back to original source URLs in the publication copy, while the local archive stays unchanged. Exit `1` indicates partial/external failure; do not call it fully successful.
- Rate limits and availability can change. Do not use unbounded retries. Both scripts bound API calls with a network timeout.

```bash
python3 scripts/fetch-wechat.py 'https://mp.weixin.qq.com/s/ARTICLE' --publish
python3 scripts/publish-telegraph.py prepared-public-images.md --publish
```

The standalone publisher reads this skill's JSON-scalar YAML frontmatter and legacy bold metadata headers. Arbitrary third-party YAML is not supported. It does not edit the original Markdown.
