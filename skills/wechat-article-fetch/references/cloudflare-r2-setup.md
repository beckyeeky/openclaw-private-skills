# Optional Cloudflare R2 public image mirror

Load this reference only when the user explicitly requests R2 mirroring. Configured credentials are not consent. `--images r2` uploads image copies; it never implies `--publish` (Telegraph). Uploading to a public bucket can expose images to anyone and can incur charges.

## Official service limits and billing

Verified against Cloudflare's official documentation on 2026-10-09:

- [Public development URL](https://developers.cloudflare.com/r2/buckets/public-buckets/#public-development-url): “This endpoint is intended for non-production traffic.” Also: “Public access through r2.dev subdomains is rate-limited and should only be used for development purposes.” Do not characterize it as a reliable personal/production image hosting service, and do not promise a numerical rate limit. Cloudflare does not provide one in this section.
- [Public buckets / custom domains](https://developers.cloudflare.com/r2/buckets/public-buckets/#custom-domains): use a custom domain for production delivery, caching and access-management features. Enabling a custom domain does not require enabling `r2.dev`. Do not CNAME your own hostname to `r2.dev`; Cloudflare calls that an unsupported access path.
- [R2 pricing](https://developers.cloudflare.com/r2/pricing/): Standard free tier currently includes 10 GB-month storage, 1 million Class A and 10 million Class B operations monthly; internet egress is free. Free tier does not mean a spending cap or guarantee of no charges. Verify current prices before provisioning or uploading; Infrequent Access has different charges and is not covered by that free tier.

No bucket creation, subscription activation or billing changes are necessary for local archiving. Never perform them merely to test this skill.

## Setup (only after explicit user request)

1. In Cloudflare Dashboard → R2, review subscription/billing terms before activating R2.
2. Create a dedicated **Standard** bucket. Do not put private material into a bucket intended to be public.
3. For temporary development checks only: bucket → Settings → Public Development URL → Enable; confirm public access and copy `https://pub-....r2.dev`.
4. For ongoing/production delivery: bucket → Settings → Custom Domains → connect a domain in your Cloudflare account; wait for Active. Use this URL as the public base. A custom domain does not make confidential images private by itself.
5. Create R2 S3 API credentials scoped to the target bucket with **Object Read & Write** only. Store Access Key ID and Secret Access Key securely; do not paste them into chat or commit them.
6. Set these runtime environment variables (values intentionally omitted):

```text
CF_R2_ACCOUNT_ID
CF_R2_ACCESS_KEY_ID
CF_R2_SECRET_ACCESS_KEY
CF_R2_BUCKET
CF_R2_PUBLIC_BASE_URL
# Optional; defaults to wechat
CF_R2_KEY_PREFIX
```

`CF_R2_PUBLIC_BASE_URL` must be public HTTPS without credentials, query or fragment. The S3 upload endpoint `https://<account>.r2.cloudflarestorage.com` is **not** a public delivery URL and is rejected. Minis users can use [Environment Variables](minis://settings/environments); other runtimes should use their secure environment configuration.

## Run and verify

```bash
# Explicitly requested R2 image mirror only:
python3 scripts/fetch-wechat.py 'https://mp.weixin.qq.com/s/ARTICLE' --images r2
# Add --publish only if Telegraph publication was also explicitly requested.
```

Local HTML, Markdown and available images are saved first. The default root is `$XDG_DATA_HOME/wechat-articles` or `~/.local/share/wechat-articles`; override using `WECHAT_ARTICLE_OUTPUT_DIR` or `--output-dir`. Keys look like `wechat/<title-URL-hash>/<image-file>`. Local Markdown continues using relative `assets/...` paths; only the in-memory publication copy uses successfully uploaded public URLs. Failed uploads retain original source URLs in that copy, so do not promise image availability on Telegraph.

Missing R2 configuration or upload failure yields partial-success exit status `1`, never deletes local files, and does not trigger automatic configuration or unbounded retry. A successful PUT is not proof of public image delivery; if requested, verify one exact object URL rather than the bucket root. Public bucket roots do not list objects.

## Troubleshooting and cost control

- Source image 403/non-image: the downloader already tries article/WeChat Referers and two mobile UAs with a 20 MiB cap. Report missing images; keep successful assets and original failed URLs.
- TLS certificate errors: keep certificate/hostname verification enabled. Repair the runtime CA trust store or missing server chain; do not add `CERT_NONE` or an insecure SSL context. If unresolved, report a partial image archive.
- R2 401/403: check R2 S3 credentials, bucket scope, Object Read & Write permission and Account ID (not Zone ID). Do not print credentials or request authorization headers.
- Public URL 404: check correct object key, configured custom domain/Public Development URL and public access status. An upload endpoint is not a viewing URL.
- `r2.dev` throttling: stop retry storms; it is development-only. Use a properly configured custom domain for production, not multiple development URLs to evade limits.
- Billing: review Usage/Billing regularly; set account billing alerts where available, use Standard when appropriate, bound uploads/retries, and do not assume alerts enforce a hard spend cap. Changing domains does not change storage/operation billing.
