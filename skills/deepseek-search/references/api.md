# DeepSeek Search API reference

Verified against the official guide at
<https://api-docs.deepseek.com/guides/search/> on 2026-10-18. The skill was
built offline: no live request and no billable call was made while creating it.
Prices, limits, and schemas can change; re-check the official guide before
relying on them for cost-sensitive work.

## Endpoints

| Operation | Method and URL |
| --- | --- |
| Search | `POST https://api.deepseek.com/v1/tools/search` |
| Fetch | `POST https://api.deepseek.com/v1/tools/fetch` |

Both endpoints:

- Require `Authorization: Bearer <DEEPSEEK_API_KEY>`.
- Accept and return JSON (`Content-Type: application/json`).
- Are called with a positive per-request timeout.
- Are subject to the official pricing and rate limits below.

The API base is fixed in this skill. There is no option to send the bearer
token to a custom base URL, and the client refuses redirects so credentials
cannot be forwarded to another origin.

## Search request

```json
{
  "query": "deepseek api search",
  "count": 10,
  "ori_question": "What does the DeepSeek search API return?",
  "localization": "203.0.113.7",
  "need_content": true
}
```

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `query` | string | yes | 1–128 Unicode characters, not empty or whitespace-only. Search operators are passed through as text. |
| `count` | integer | no | 1–50; default `10`. |
| `ori_question` | string | no | 1–128 Unicode characters. `null` is treated as not provided; this client omits the field when unused. |
| `localization` | string | no | Optional IPv4 or IPv6 address used to localize results; the service default is an empty string. |
| `need_content` | boolean | no | Ask for page content in `content`; when false the service returns an empty `content` string. Omitted by default. |

`query` is measured in Unicode code points by this client, not UTF-8 bytes.
Whitespace-only queries are rejected locally.

### Search operators

Operators are part of the query string and are interpreted by the service:

| Operator | Meaning | Example |
| --- | --- | --- |
| `site:` | Restrict to a site | `site:api-docs.deepseek.com tools` |
| `-site:` | Exclude a site | `deepseek -site:example.com` |
| `-word` | Exclude a word | `deepseek -ads` |
| `-"phrase"` | Exclude an exact phrase | `deepseek -"press release"` |
| `"phrase"` | Require an exact phrase | `"search api"` |
| `lang:` | Language filter, comma-separated (`zh`, `en`, …) | `deepseek lang:zh,en` |
| `after:` | Results after a date | `deepseek after:2025-01-01` |
| `before:` | Results before a date | `deepseek before:2026-01-01` |

The client does not parse or rewrite these operators; syntax errors are
whatever the service reports (often HTTP 400 or fewer results).

## Search response

The response is a JSON object with a `results` array. An empty array is a
normal, successfully billed-empty result and must not be treated as an error.

Each result contains:

| Field | Type | Description |
| --- | --- | --- |
| `rerank_score` | number | Relevance score from 0 to 3 combining relevance, authority, and freshness; 1.5 or above is considered high quality. |
| `title` | string | Page title. |
| `url` | string | Page URL. |
| `snippet` | string | Short excerpt, typically 100–200 characters, intended for display. |
| `summary` | string | Generated summary. |
| `content` | string | Page content, typically when `need_content` is true; empty when it is false. |
| `site_name` | string | Site or publisher name. |
| `site_icon` | string | Icon URL. |
| `date` | string | Publication or crawl date supplied by the service. |
| `authority` | number | Numeric authority indicator supplied by the service. |

Example:

```json
{
  "results": [
    {
      "rerank_score": 0.91,
      "title": "DeepSeek API Docs",
      "url": "https://api-docs.deepseek.com/",
      "snippet": "Official API documentation.",
      "summary": "Entry point for the DeepSeek API documentation.",
      "content": "# DeepSeek API Docs\n\n...",
      "site_name": "api-docs.deepseek.com",
      "site_icon": "https://api-docs.deepseek.com/favicon.ico",
      "date": "2026-01-01",
      "authority": 3
    }
  ]
}
```

The CLI requires `results` to be an array and each item to be an object with a
string `title` and an absolute `http`/`https` `url`. Optional fields are not
type-checked beyond being present, so callers must tolerate missing or null
optional values. A response that fails these basic checks is rejected as an
invalid response instead of being reported as success.

## Fetch request

```json
{
  "url": "https://api-docs.deepseek.com/guides/search/"
}
```

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `url` | string | yes | `http` or `https`; a host is required; no embedded credentials; at most 8192 characters. |

The client rejects other schemes (`file:`, `ftp:`, …), missing hosts, embedded
`user:password@` credentials, whitespace/control characters, invalid ports,
and URLs over 8192 characters before any request is sent.

## Fetch response

```json
{
  "title": "Search | DeepSeek API Docs",
  "content": "# Search\n\nMarkdown body ..."
}
```

The CLI requires a string `title` and a non-empty string `content`. Fetch is
for one page at a time; there is no crawling, link following, or bulk mode.

## Authentication and key handling

- The key is read only from the `DEEPSEEK_API_KEY` environment variable. It is
  not accepted as a command-line argument, so it does not appear in shell
  history or the process list.
- The client checks key presence and rejects empty values, whitespace, control
  characters, and non-ASCII characters before building a request.
- The key is never printed on success or failure. Error records contain only a
  stable code, a fixed message, an optional HTTP status, and a retryable flag.
- Server response bodies are never included in error output. A server can
  reflect request data (including a key) in an error page, so raw bodies are
  not safe to print.
- The `Authorization` header is added as an unredirected header and all
  redirects are refused.

Check presence without printing the value:

```sh
[ -n "$DEEPSEEK_API_KEY" ] && echo set || echo not_set
```

## Errors

| Status | Meaning | Client behavior |
| --- | --- | --- |
| `400` | Invalid headers/body or invalid field value | Final; no retry. |
| `401` | API key missing or invalid | Final; check the key. |
| `402` | Insufficient balance | Final; check the account balance. |
| `403` | Request rejected by the fetch security policy | Final; do not retry unchanged. |
| `404` | Fetch could not retrieve usable page content (unavailable URL, policy block, target-site error, unsupported content type, no extractable Markdown) | Final; try another URL if appropriate. |
| `408` | Reading the request body timed out | Bounded retry. |
| `413` | Request body too large | Final; reduce the request. |
| `429` | Search/Fetch QPS or per-domain fetch limit exceeded | Bounded retry; `Retry-After` is honored when it is an integer. |
| `500` | Internal server error | Bounded retry. |
| `504` | Downstream request timed out | Bounded retry. |
| other `5xx` | Server error | Bounded retry. |
| `3xx` | Redirect | Blocked; never followed; reported as `redirect_blocked`. |

Other non-2xx statuses are final. Network failures (DNS, connection reset,
timeout, truncated protocol response, non-certificate TLS failure) are retried
within the same bounds. TLS certificate verification failures are final and
never retried or bypassed.

### Retry policy

- Default `--retries 2` (up to 3 attempts); allowed range `0–5`.
- Delays are exponential: 0.5 s, 1 s, 2 s, 4 s, 8 s, capped at 8 s per wait.
- Total wait is capped at 20 s; a retry that would exceed the cap is not made.
- An integer `Retry-After` is honored, clamped to 0.5–8 s.
- Retries apply only to `408`, `429`, `5xx`, and transient network failures.
- Business errors (`400`, `401`, `402`, `403`, `404`, `413`), redirects, certificate
  verification failures, schema failures, and local validation errors are
  never retried.

### Client exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success; JSON written to stdout or the requested file. |
| `1` | Unexpected internal failure (sanitized). |
| `2` | Invalid arguments or local validation failure; no request sent. |
| `3` | Missing or invalid `DEEPSEEK_API_KEY`; no request sent. |
| `4` | Final HTTP error (including blocked redirect). |
| `5` | Network failure, timeout, TLS verification failure, or retries exhausted. |
| `6` | Invalid response schema, non-JSON body, or response too large. |
| `7` | Output file exists or could not be written. |

On failure, stdout is empty and stderr contains one JSON object:

```json
{
  "error": {
    "code": "http_error",
    "message": "DeepSeek API authentication failed (HTTP 401). Check DEEPSEEK_API_KEY and whether the key is active.",
    "retryable": false,
    "status": 401
  }
}
```

## Pricing and rate limits

Official pricing for the search guide: **US$0.75 per 1,000 successful,
non-empty requests**, covering both search and fetch. A request is billable
only when it returns HTTP 200 and produces a result (search must return a
non-empty `results` array; fetch must return page content). Empty search
results, failures, and timeouts are not charged according to the official
guide. Billing is per request, not per token or per returned result; `count`
does not change the per-request price.

- The CLI does not make requests free. Every successful non-empty request can
  incur the official charge regardless of which script or client sent it.
- The official guide notes that server-side calls made through DeepSeek
  Harness, Claude Code, or Codex have had a temporary free period ending at
  00:00 Beijing time on 2026-11-01. That integration-specific arrangement does
  not make direct API calls from this skill free and must not be generalized.
- Promotional credits, harness discounts, or account-specific offers are not
  part of the general contract and must not be presented as the normal price.
- Search and fetch are read-only APIs.
- Each endpoint is limited to **5 QPS**. The limits are account-level, apply
  independently to search and fetch, and are separate from model concurrency
  limits.
- Fetch additionally has a per-domain rate limit. The verified contract does
  not publish its numeric threshold; throttle per domain, avoid bursts, and
  honor `429`/`Retry-After`.
- This client sends one request per invocation and performs no prefetching,
  polling, crawling, or parallel fan-out.

## Local limits

- Response bodies are read up to 5 MiB; larger responses are rejected.
- No streaming, pagination loop, caching, or automatic follow-up search.
- Output is JSON; `--output` uses exclusive creation and never overwrites. The
  destination (existing file, missing parent directory) is checked before the
  request, so an unusable path costs nothing.
- The client does not extract images, PDFs, or JavaScript-rendered content; it
  only reports what the service returns.
- The client cannot bypass paywalls, access controls, robots restrictions, or
  regional blocks.
- Standard urllib behavior applies to the host environment: proxy variables
  (for example `HTTPS_PROXY`) are honored, and a TLS-terminating proxy must be
  trusted by the local trust store. TLS verification is never disabled by this
  client, so a proxy with an untrusted certificate fails closed rather than
  sending the key in clear text.
- The client cannot detect a compromised local Python installation, a patched
  `ssl` module, or a malicious CA installed on the device.
