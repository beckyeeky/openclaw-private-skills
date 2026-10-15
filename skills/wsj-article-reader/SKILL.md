---
name: wsj-article-reader
description: >-
  Retrieve, archive, and summarize Wall Street Journal articles that the user is
  already authorized to read, using a locally supplied WSJ/Dow Jones app access
  token. Use when the user asks to fetch, save, summarize, translate, or build
  a reading digest from a WSJ article. Never use to bypass paywalls, obtain
  articles without entitlement, or disclose credentials.
license: MIT
metadata:
  hermes:
    version: 0.3.0
    author: beckyeeky
    category: media
    tags: [wsj, dow-jones, article, graphql, archive, reading]
    triggers:
      - wsj article
      - wall street journal
      - 抓 WSJ 文章
      - WSJ 文章
      - 华尔街日报文章
    related_skills: [wechat-article-fetch]
---

# WSJ Article Reader

## Purpose

Fetch a Wall Street Journal article **only when the user is entitled to access
it**, turn it into readable Markdown, and optionally summarize, translate, or
save it locally. The content API observed in the iOS app is the Dow Jones
GraphQL gateway; article retrieval is authenticated with the user's app access
token rather than a reusable website cookie.

This skill is for a user's own subscription and reading workflow. It must not
circumvent WSJ/Dow Jones access controls, subscription checks, rate limits, or
publisher terms; it must not distribute full restricted articles to anyone who
is not entitled to read them.

## Security and entitlement rules

1. Treat `WSJ_DJ_AUTHORIZATION` as a password: never print, echo, log, include
   in an error, commit, or place it in a URL.
2. Do not store it in this repository, a skill file, shell history, generated
   report, or source archive. Keep it only in an environment variable or a
   local credential store outside the repository.
3. Use `Authorization: $WSJ_DJ_AUTHORIZATION` exactly as supplied. Do not
   attempt to manufacture, refresh, decode, alter, or share the token.
4. A `401`, `403`, paywall, or entitlement-denied response is a final access
   result. Tell the user to renew access or refresh their own token; do not try
   alternate endpoints or work around the restriction.
5. Keep retrieval low-volume and user-directed. Do not bulk-download, crawl,
   or build an unauthorized article corpus.

## Required setup

### 1. Authorization env var

The user must have a valid WSJ/Dow Jones subscription or other legitimate
access and must locally provide the current app `Authorization` header value:

```sh
# Check presence only; never echo its value.
[ -n "$WSJ_DJ_AUTHORIZATION" ] && echo set || echo not_set
```

If it is missing, ask the user to create it in their private agent environment
([Set WSJ_DJ_AUTHORIZATION](minis://settings/environments?create_key=WSJ_DJ_AUTHORIZATION&create_value=&create_note=WSJ%20iOS%20app%20Authorization%20header%20for%20shared-data.dowjones.io))
and explain that it contains the complete `Authorization` header value captured
from **their own** authenticated WSJ app request to:

```text
https://shared-data.dowjones.io/gateway/graphql
```

The token can expire or be revoked. Prompt for a fresh value on authorization
failure. Do not ask the user to paste it into chat.

### 2. Non-secret request template

Store the mutable request shape at:

```text
~/.openclaw/wsj-article-reader/template.json
```

It must contain the endpoint, `ArticleContent` operation name, persisted-query
object, and required **non-secret** app/Apollo headers. It must not contain
`Authorization`, Cookie, tokens, a full captured request URL with secrets,
response body, or article data.

**Bootstrap from the bundled example** (captured shape, iOS app `15.6.1`,
2026-08-06):

```sh
mkdir -p ~/.openclaw/wsj-article-reader
cp {baseDir}/references/template.example.json \
  ~/.openclaw/wsj-article-reader/template.json
```

**Or rebuild from a fresh local capture** (HTTP Toolkit-style dump directory
with `request_header_raw.txt`, or a raw request-header file):

```sh
python3 {baseDir}/scripts/build_template.py /path/to/capture-dir \
  -o ~/.openclaw/wsj-article-reader/template.json
```

Refresh the template when WSJ rotates the persisted-query hash or app version.
The fetch helper reads the token only from `WSJ_DJ_AUTHORIZATION`, injects it
at runtime, and overrides `Accept-Language` to `en-US,en;q=0.9`.

Runtime state and exported articles:

```text
~/.openclaw/wsj-article-reader/
  template.json
  state.json
  articles/
```

Override the runtime root with `WSJ_READER_HOME` if needed. Optionally point
`WSJ_CA_BUNDLE` at a local extra PEM CA bundle (additive only; see step 3a).

## Observed API scope

```text
GET https://shared-data.dowjones.io/gateway/graphql
```

Apollo persisted-query metadata lives in URL query parameters. Required
non-secret headers include `x-apollo-operation-name`, `x-apollo-operation-id`
(sha256 of the query), client name/version, and `x-app-version`. Entitled
content also requires the user's `Authorization` header.

| Operation | Handling |
|---|---|
| `ArticleContent` | Article body and metadata — **only** content op this skill calls. |
| `SummaryCollectionContentV2` | Home/section rails; do not fetch by default. |
| `BundledRecommendedArticles`, `RecommendedAuthors`, … | Personalization; out of scope. |
| `MarketDataStrap`, `TradingSessions`, `InstrumentsSubscription` | Market data; out of scope. |
| Analytics / Piano / Braze / Adobe / Optimizely / Permutive | Never call. |

Observed (2026-08-06) ArticleContent persisted-query sha256:

```text
4253f896c39fef877b22e45929c887bf48d34134d476f345175c1c2b7c4dbf70
```

Variables:

```json
{
  "filterByScope": "MOBILE",
  "id": "<origin id>",
  "idType": "originid"
}
```

See [`references/response-schema.md`](references/response-schema.md) for body
block types and Markdown mapping.

## Workflow

### 1. Validate the task and URL

- Confirm the user supplied a WSJ article URL or origin id (`SB…` / `WP-WSJ-…`).
- Check credential presence without revealing it.
- State when an article is unavailable due to entitlement; never promise access.

### 1a. Resolve the origin id automatically

Prefer letting the user supply only the article URL. For ordinary WSJ article
URLs the fetch helper calls the bundled browser metadata resolver first:

```sh
python3 {baseDir}/scripts/resolve_origin_id.py 'https://www.wsj.com/…'
```

The resolver reads only `__NEXT_DATA__.props.pageProps.articleData`, not other
scripts or related-story objects. Its `sourceUrl`/`canonicalUrl` must match the
requested path; `originId` and `articleTrackingMeta.articleId` must agree when
both exist. Missing dedicated data is rejected. A `/webview/<origin id>` URL
supplies the id directly, without a browser.
If the browser CLI is unavailable, the run fails with an explicit message and no
authorized request is sent — pass `--origin-id` only when you already have one.

Metadata access is public and unauthenticated. An HTTP `401`/`403` seen while
reading **public page metadata** is not an authenticated `ArticleContent`
entitlement result, and a single ordinary browser navigation is allowed to read
it. Do not solve challenges, rotate proxies, or read restricted article bodies.
A `401`/`403`/`429` from the **authorized** `ArticleContent` request remains
final (see the failure table).

### 2. Ensure template exists

If `~/.openclaw/wsj-article-reader/template.json` is missing, copy the bundled
example or run `build_template.py` on a fresh local `ArticleContent` capture.

### 3. Fetch one requested article

```sh
# By origin id
python3 {baseDir}/scripts/fetch_article.py --origin-id 'SB…'

# By WSJ URL (browser metadata resolver first, then one ArticleContent call)
python3 {baseDir}/scripts/fetch_article.py --url 'https://www.wsj.com/…'

# Offline parse of an already-authorized JSON response (no network)
python3 {baseDir}/scripts/fetch_article.py --from-json ./response.json
```

Flags:

| Flag | Meaning |
|---|---|
| `--allow-once` | Bypass only the 15-minute local cooldown for one interactive run |
| `--network-retries N` | Bounded retries for transient transport faults only (`0`–`2`, default `0`) |
| `--insecure` | Disable TLS certificate/hostname verification for this run only; explicit user request required |
| `--print-md` | Print saved Markdown to stdout after write |

The helper fetches one article serially, with a randomized 2–6 second preflight
wait and local cooldown/hour/day limits. Retries are off by default; explicitly
selected bounded retries cover transient connection and response-read faults
(including truncated transfers) for the idempotent GET only. HTTP errors and TLS
failures are never retried. Authorized redirects are refused without a second
request. No polling, recommendation, analytics, or prefetch calls are made. URL resolution is done by
the browser metadata resolver described in step 1a and sends no authorized
request of its own. See
[`references/behavior-policy.md`](references/behavior-policy.md).

### 3a. TLS trust and safe diagnostics

HTTPS certificate and hostname verification are enabled by default with
`ssl.create_default_context()`. Only an explicitly authorized `--insecure` flag
can disable them for one invocation (see 3b); no error enables that flag.

- If local trust is incomplete, fix it with a valid CA or device/proxy settings.
  Never disable verification automatically after a handshake error.
- An explicit extra CA may be supplied with `WSJ_CA_BUNDLE=/path/to/extra-ca.pem`.
  It is **appended** to the system trust store (`load_verify_locations`), never
  substituted for it, and hostname verification stays enabled. A missing,
  unreadable, empty (for example a 0-byte file), non-PEM, or unparsable bundle
  aborts the run **before any request is sent** (and before any local rate-limit
  slot is consumed).
- Transport failures are reported only as fixed safe categories: the diagnostic
  text never includes the token, the request URL/query, or headers.

| Reported category | Meaning | What to do |
|---|---|---|
| `tls_certificate_untrusted` | Certificate chain not verifiable against local trust (unknown issuer / missing intermediate) | Fix local TLS trust, then start **one new request manually** |
| `tls_handshake_failed` | Handshake failed for a non-trust reason (protocol/cipher/reset) | Check the device TLS stack/proxy, then start one new request manually |
| `network_timeout` / `network_error` | Could not reach the endpoint | Re-run later; only transient transport faults qualify for explicit bounded retries |

Retries are disabled by default. Explicit `--network-retries N` allows at most
N additional attempts for temporary transport faults; HTTP and TLS failures
remain final. Truncated body reads report `network_body_interrupted`, and
transport records include `connect` or `body` phase without response text.

### 3b. Explicit, single-run opt-outs (never defaults)

Both options below are per-invocation flags only. They are never read from an
environment variable, never written to `state.json`/`template.json`, and never
enabled automatically as a reaction to an error.

| Option | Allowed use | Hard rules |
|---|---|---|
| `--insecure` | Only when the user explicitly asks for one run despite the risk | No `--insecure` default anywhere; warning printed on stderr contains no token/URL; a certificate failure never triggers it; the hourly/day limits still apply |
| `--network-retries N` | Only to absorb transient transport faults in one run (`N` = 0–2, default 0) | Retries **only** temporary timeouts, resets and truncated reads during connection or response-body transfer for the idempotent GET, plus temporary DNS failures; never TLS verification or TLS handshake errors, never any HTTP status (401/403/429/5xx included), never entitlement/schema rejections; every real attempt is recorded and counted against the hour/day limits; the interactive cooldown gates only the first attempt of the run; waits stay short and sequential (no burst), and `N` is rejected out of range before any request |

`--insecure` risk: the certificate chain and hostname are not verified, so the
connection can be intercepted or modified, and the access token would be sent
to whoever answers. It is a last-resort, user-authorized diagnostic step, not a
fix — the correct remedy for `tls_certificate_untrusted` is repairing local TLS
trust.

Field note (2026-10): the content endpoint and the `GET` + token + template path
were confirmed working end to end once the device's TLS trust was corrected
(TLSv1.3 handshake completed, full article exported). The earlier failure was an
environment trust-store problem (`unable to get local issuer`), not an endpoint,
method, or token problem — so do not change the HTTP method or bypass
verification to "fix" TLS. TLS is fixed on the device/proxy first; the request
is then issued once, manually.

### 3c. Verify locally first (offline)

```sh
python3 {baseDir}/scripts/tests/test_wsj_reader_safety.py
```

These tests are fully offline: they cover TLS error classification and
redaction, invalid/empty CA-bundle preflight, preserved default verification,
the explicit `--insecure` opt-in (flag-only, bounded, never automatic),
`--network-retries` bounds and stop conditions, the URL → resolver integration
(including "browser unavailable" and "never take a recommended-story id"), and
the unchanged Markdown body parsing.

### 4. Save and present

Markdown is written under `~/.openclaw/wsj-article-reader/articles/`:

```markdown
# <title>

- Source: Wall Street Journal
- URL: <canonical URL>
- Author: <byline>
- Section: <section>
- Published: <timestamp>
- Updated: <timestamp>
- Origin ID: <originId>
- Retrieved: <local timestamp>

> <standfirst>

---

<article body>
```

Body mapping (observed iOS schema):

| Block | Markdown |
|---|---|
| `ParagraphArticleBody` | Paragraph; LINK/BOLD/ITALIC applied |
| `BlockquoteArticleBody` | Blockquote |
| `TaglineArticleBody` | Italic line |
| `ImageArticleBody` | Image + caption/credit |
| `AudioArticleBody` / `VideoArticleBody` | Linked media line |
| `NewsletterInsetArticleBody` | Skipped |

Report the saved path and a concise summary. Translate or produce study notes
only at the user's request. Preserve attribution and link to the original.

## Failure handling

| Result | Action |
|---|---|
| Missing `WSJ_DJ_AUTHORIZATION` | Request private local setup; never ask for it in chat. |
| `tls_certificate_untrusted` / `tls_handshake_failed` | Report the fixed category only; fix local TLS trust first, then start one new request manually. Never automatically disable verification. |
| Invalid/empty `WSJ_CA_BUNDLE` | Report the preflight error; export a valid PEM chain or unset the variable. No request was sent. |
| `--network-retries` out of range (below 0 or above 2) | Reject before any request; never silently clamp. |
| Transient fault with `--network-retries N` | Retry only connect/read timeout, truncated response body, temporary DNS failure or connection reset, up to `N` extra attempts, each recorded and rate-limited; stop when exhausted. |
| 401 / 403 / entitlement denied (authorized request) | Final result; stop. Ask the user to reauthenticate in WSJ or refresh their own token. |
| 429 rate limit | Stop; no retry, no alternate endpoint. |
| Persisted query rejected | Rebuild template from a newly captured `ArticleContent` request. |
| Response schema changed | Save no raw sensitive response; update parser only after a user-authorized sample. |
| Local cooldown / rate limit | Stop and wait; do not retry aggressively. |
| Browser metadata resolution failed | Report the resolver error (browser unavailable or ambiguous metadata); do not substitute a recommended-story id. Ask for `--origin-id` only as a last resort. |

## Agent checklist

1. `[ -n "$WSJ_DJ_AUTHORIZATION" ]` → if missing, send env deep link; stop.
2. Ensure `template.json` (copy example or `build_template.py`).
3. If `WSJ_CA_BUNDLE` is set, confirm it is a valid PEM bundle; an invalid or
   0-byte file aborts before any request.
4. Run `fetch_article.py` once with `--url` (browser resolver) or `--origin-id`.
5. On `tls_*` categories: report the category only, fix device TLS trust, then
   start one new request manually. Never automatically disable verification, never retry
   automatically.
6. Use `--insecure` only if the user explicitly asks for a single diagnostic
   run; never persist it and never let a certificate failure switch it on.
7. Use `--network-retries` (max 2) only for transient transport faults; it must
   not be used to retry HTTP or TLS failures.
8. Read the saved Markdown; summarize or translate only if asked.
9. On auth/template failure, stop; do not probe other operations.

## Non-goals

- Paywall bypassing, credential sharing, or subscription evasion.
- Bulk crawling, syndication, training datasets, or republication of restricted WSJ text.
- Modifying WSJ account, subscription, recommendation, or tracking state.
- Reusing this credential with unrelated Dow Jones properties.
- Calling any GraphQL operation other than `ArticleContent` for this skill.
