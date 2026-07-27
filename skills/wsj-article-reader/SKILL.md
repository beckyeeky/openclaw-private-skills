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
    version: 0.1.0
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

The user must have a valid WSJ/Dow Jones subscription or other legitimate
access and must locally provide the current app `Authorization` header value:

```sh
# Check presence only; never echo its value.
[ -n "$WSJ_DJ_AUTHORIZATION" ] && echo set || echo not_set
```

If it is missing, ask the user to create it in their private agent environment
and explain that it contains the complete `Authorization` header value captured
from **their own** authenticated WSJ app request to:

```text
https://shared-data.dowjones.io/gateway/graphql
```

The token can expire or be revoked. Prompt for a fresh value on authorization
failure. Do not ask the user to paste it into chat.

### Non-secret request template

Store the mutable request shape at:

```text
~/.openclaw/wsj-article-reader/template.json
```

It must contain the endpoint, `ArticleContent` operation name, persisted-query
query object, and required **non-secret** app/Apollo headers. It must not
contain `Authorization`, Cookie, tokens, a full captured request URL, response
body, or article data. Refresh it from a newly captured request when WSJ
changes its persisted query or app version.

The bundled helper reads the token only from `WSJ_DJ_AUTHORIZATION`, injects it
at runtime, and deliberately overrides `Accept-Language` to:

```http
Accept-Language: en-US,en;q=0.9
```

This controls language preference only; it is not authentication. Keep the
remaining App version/client headers internally consistent with the template.

Runtime state and exported articles belong outside `{baseDir}`, for example:

```text
~/.openclaw/wsj-article-reader/
  articles/
```

## Observed API scope

The iOS traffic uses:

```text
GET https://shared-data.dowjones.io/gateway/graphql
```

with Apollo persisted-query metadata in URL query parameters and headers such
as `x-apollo-operation-name`, `x-apollo-operation-id`, client name/version, and
an `Authorization` header for entitled content.

Observed operation names include:

| Operation | Intended handling |
|---|---|
| `ArticleContent` | Article body and metadata; this is the only article-content operation relevant to this skill. |
| `BundledRecommendedArticles` | Optional, user-visible recommendations; do not fetch by default. |
| `RecommendedAuthors`, `RecommendedCompanies`, `MyCompanies` | Personalization features; out of scope. |
| `MarketDataStrap`, `TradingSessions` | Public/market data; out of scope. |

Do **not** intercept or use analytics, ad-tech, experimentation, or subscription
experience endpoints (Permutive, Piano, Braze, Adobe, Optimizely, etc.).

## Workflow

### 1. Validate the task and URL

- Confirm the user supplied a WSJ article URL or a known WSJ article ID.
- State when an article is unavailable due to entitlement; never promise access.
- Check the credential is present without revealing it.

### 2. Obtain a request template safely

The GraphQL gateway uses persisted-query values that may change. Rather than
hard-code a stale hash, obtain a **fresh locally captured** `ArticleContent`
request template from the user's own authenticated session. Preserve only the
non-secret request shape in a local template, and keep the authorization value
in `WSJ_DJ_AUTHORIZATION`.

The template needs:

- endpoint and method;
- `operationName=ArticleContent`;
- persisted-query/variables query parameter structure;
- required non-secret Apollo and app-version headers.

Never commit captured headers, query variables containing identifiers, raw
responses, or tokens.

### 3. Fetch one requested article

Run the deterministic helper; it reads the non-secret local template and the
private environment token separately:

```sh
python3 {baseDir}/scripts/fetch_article.py --origin-id '<WSJ origin ID>'
```

The helper is single-request, single-threaded and applies a randomized 2–6
second preflight wait plus local cooldown/hour/day limits. It makes no retry,
polling, recommendation, analytics, or prefetch calls. See
[`references/behavior-policy.md`](references/behavior-policy.md) before any
change to its limits or timing.

Send only the requested `ArticleContent` query with the user's authorization.
If the response is an access denial, stop. If successful, extract title,
byline, publication time, canonical URL, and the article body from the returned
JSON.

### 4. Save and present

Write a Markdown file under `~/.openclaw/wsj-article-reader/articles/` using:

```markdown
# <title>

- Source: Wall Street Journal
- URL: <canonical URL>
- Author: <byline>
- Published: <timestamp>
- Retrieved: <local timestamp>

---

<article body>
```

Report the saved path and a concise summary. Translate or produce study notes
only at the user's request. Preserve attribution and link to the original.

## Failure handling

| Result | Action |
|---|---|
| Missing `WSJ_DJ_AUTHORIZATION` | Request private local setup; never ask for it in chat. |
| 401 / 403 / entitlement denied | Stop; ask the user to reauthenticate in WSJ or refresh their own token. |
| Persisted query rejected | Ask for a newly captured `ArticleContent` request template. |
| Response schema changed | Save no raw sensitive response; update a local parser only after inspecting a user-authorized sample. |
| Rate limit | Stop and wait; do not retry aggressively. |

## Non-goals

- Paywall bypassing, credential sharing, or subscription evasion.
- Bulk crawling, syndication, training datasets, or republication of restricted WSJ text.
- Modifying WSJ account, subscription, recommendation, or tracking state.
- Reusing this credential with unrelated Dow Jones properties.
