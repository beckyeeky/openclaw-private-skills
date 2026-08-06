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
    version: 0.2.0
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

Override the runtime root with `WSJ_READER_HOME` if needed.

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

### 2. Ensure template exists

If `~/.openclaw/wsj-article-reader/template.json` is missing, copy the bundled
example or run `build_template.py` on a fresh local `ArticleContent` capture.

### 3. Fetch one requested article

```sh
# By origin id
python3 {baseDir}/scripts/fetch_article.py --origin-id 'SB…'

# By WSJ URL (resolves public articleId / SB… marker, then one ArticleContent call)
python3 {baseDir}/scripts/fetch_article.py --url 'https://www.wsj.com/…'

# Offline parse of an already-authorized JSON response (no network)
python3 {baseDir}/scripts/fetch_article.py --from-json ./response.json
```

Flags:

| Flag | Meaning |
|---|---|
| `--allow-once` | Bypass only the 15-minute local cooldown for one interactive run |
| `--print-md` | Print saved Markdown to stdout after write |

The helper is single-request, single-threaded and applies a randomized 2–6
second preflight wait plus local cooldown/hour/day limits. It makes no retry,
polling, recommendation, analytics, or prefetch calls. URL resolution may
perform **one** unauthenticated GET of the public article HTML solely to read
`articleId` / `SB…`; it does not use HTML as the article body. See
[`references/behavior-policy.md`](references/behavior-policy.md).

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
| 401 / 403 / entitlement denied | Stop; ask the user to reauthenticate in WSJ or refresh their own token. |
| Persisted query rejected | Rebuild template from a newly captured `ArticleContent` request. |
| Response schema changed | Save no raw sensitive response; update parser only after a user-authorized sample. |
| Rate limit / local cooldown | Stop and wait; do not retry aggressively. |
| URL origin id not found | Ask for `--origin-id` from the app or a fresher URL. |

## Agent checklist

1. `[ -n "$WSJ_DJ_AUTHORIZATION" ]` → if missing, send env deep link; stop.
2. Ensure `template.json` (copy example or `build_template.py`).
3. Run `fetch_article.py` once with `--url` or `--origin-id`.
4. Read the saved Markdown; summarize or translate only if asked.
5. On auth/template failure, stop; do not probe other operations.

## Non-goals

- Paywall bypassing, credential sharing, or subscription evasion.
- Bulk crawling, syndication, training datasets, or republication of restricted WSJ text.
- Modifying WSJ account, subscription, recommendation, or tracking state.
- Reusing this credential with unrelated Dow Jones properties.
- Calling any GraphQL operation other than `ArticleContent` for this skill.
