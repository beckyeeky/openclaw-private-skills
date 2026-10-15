# WSJ Article Reader behavior policy

This policy applies to retrieval through a user's own authorized WSJ/Dow Jones
account. Its purpose is to keep the tool a deliberate, low-volume reading aid,
not a crawler.

## Default operating mode

- Fetch only an article URL or origin ID explicitly supplied by the user.
- Fetch one article per invocation; no prefetch, recommendation expansion,
  pagination, search harvesting, or concurrent requests.
- A WSJ article URL is resolved to the current article's origin id by the
  bundled resolver. It reads only `__NEXT_DATA__.props.pageProps.articleData`,
  validates its `sourceUrl`/`canonicalUrl` path against the requested article,
  and requires `originId` and `articleTrackingMeta.articleId` to agree when both
  exist. No recursive metadata search or whole-page regex is used; missing
  dedicated data is rejected. It sends no authorized request. If
  the browser is unavailable or the metadata is ambiguous, the run stops with an
  explicit error instead of guessing; require `--origin-id` only as a last
  resort.
- Preserve publisher access decisions. A `401`, `403`, entitlement denial, or
  paywall response ends the run immediately.
- Do not call analytics, advertising, experimentation, push, or personalization
  services merely to imitate a mobile app.
- Do not call GraphQL operations other than `ArticleContent`.

## Rate limits

The fetcher enforces these conservative local limits:

| Limit | Default |
|---:|---:|
| Concurrent article requests | 1 |
| Minimum time between successful/attempted requests | 15 minutes |
| Maximum requests per rolling hour | 6 |
| Maximum requests per rolling day | 20 |
| Automatic retries after 401/403/429/5xx | 0 |
| Automatic retries after TLS verification/handshake failure | 0 |

A user may explicitly lower a waiting period for one interactive request, but
must not disable the hourly/day limits or use the tool for bulk retrieval.

## TLS trust and bounded transport retries

Certificate and hostname verification are always on by default
(`ssl.create_default_context()`, i.e. the platform trust store). Verification is
never disabled implicitly: no `CERT_NONE`, no unverified context, and no
hostname-check bypass in any normal path.

- `WSJ_CA_BUNDLE` may point at an explicit local extra PEM CA bundle. It is
  **appended** to the system trust store, never substituted, and hostname
  verification stays enabled. A missing, unreadable, empty (for example a 0-byte
  file), non-PEM, or unparsable bundle aborts the run before any request is sent
  and before any rate-limit slot is consumed.
- Transport failures are reported only as fixed safe categories
  (`tls_certificate_untrusted`, `tls_handshake_failed`, `network_timeout`,
  `network_error`). The message never contains the access token, the request
  URL/query, or headers.
- `--insecure` disables certificate and hostname verification for **one
  explicitly requested run**. It is never enabled by an environment variable, a
  config file, or a previous run, and a certificate failure never triggers it.
  The stderr warning contains no token or URL. Treat it as a user-authorized
  diagnostic last resort; the correct remedy for a trust failure is repairing
  local TLS trust.
- `--network-retries N` (default `0`, maximum `2`; out-of-range values are
  rejected before any request) retries transient timeouts/resets during connection
  and response-body reading, truncated body transfers for the idempotent GET,
  and temporary DNS failures (`EAI_AGAIN`/`EAI_FAIL`). It never retries TLS
  verification or TLS handshake failures, any HTTP status (401/403/429/5xx
  included), entitlement results, or schema/persisted-query rejections. Each
  real attempt is recorded in `state.json` and counted against the hourly/daily
  limits; the 15-minute interactive cooldown gates only the first attempt of a
  run, and waits between attempts stay short and sequential (no burst, no
  parallelism).

After a TLS or network fix, start a single new request manually. There is no
unattended retry loop.

## Timing

When a request is allowed, the script chooses one small randomized preflight
wait (default 2–6 seconds). If the user explicitly allowed `--network-retries`,
each retry waits a further short randomized backoff (a few seconds) with no
burst and no parallelism. This is pacing, not an attempt to evade publisher
controls.

## Local state and privacy

Runtime files live outside the skill repository:

```text
~/.openclaw/wsj-article-reader/
  template.json       # non-secret GraphQL request shape
  state.json          # timestamps/status only
  articles/           # user-authorized exports
```

`state.json` stores only UTC timestamps, a short article identifier, and the
outcome of each attempt: an HTTP status or a fixed transport category such as
`tls_certificate_untrusted` / `network_error`. It never stores Authorization
values, cookies, full request URLs, response bodies, titles, or article text.

## Public metadata vs authorized endpoint denials

These are different results and must not be conflated:

- While reading **public page metadata** (browser resolver), an HTTP `401`/`403`
  or a missing id is a metadata problem. A single ordinary browser navigation is
  permitted to read public metadata; do not solve challenges, rotate proxies, or
  extract a restricted article body, and never substitute a related-story id.
- A `401`/`403`/`429` (or any other error status) from the **authorized
  `ArticleContent` request** is a publisher access decision: it is final, and it
  is never retried or routed around.

## Stop conditions

Stop without retrying when any of these occur:

- `401`, `403`, access/entitlement denial, or a publisher paywall result;
- `429` rate limit, and any other HTTP error status;
- an unknown persisted-query or schema failure;
- a TLS trust or handshake failure (`--insecure` is never used to continue);
- a transport failure outside transient connect/read timeout, truncated body,
  temporary DNS failure or connection reset, or one exceeding the explicit
  `--network-retries` budget;
- any redirect: the authorized transport refuses it before a second request;
- local rate limit reached (hourly/daily).

On an authorization or template failure, ask the user to refresh their own WSJ
App session and generate a new local non-secret template. Never alter, decode,
or attempt to refresh the authorization token.
