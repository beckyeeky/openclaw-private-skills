# ArticleContent response schema (observed 2026-08-06)

Source: WSJ iOS app `15.6.1` → `GET https://shared-data.dowjones.io/gateway/graphql`  
Persisted query sha256: `4253f896c39fef877b22e45929c887bf48d34134d476f345175c1c2b7c4dbf70`

## Variables

```json
{
  "filterByScope": "MOBILE",
  "id": "<origin id>",
  "idType": "originid"
}
```

Observed origin id forms:

| Form | Example | Notes |
|---|---|---|
| `SB…` | `SB10690322230188923380204593371010783325182` | Common article origin id; also embedded in public HTML as `articleId` / bare `SB…`. |
| `WP-WSJ-…` / `WP-WSJO-…` | `WP-WSJO-0000347602` | Appears on some opinion/collection items; accepted as `originid`. |

## Root

```text
data.articleContent          Article | null
```

Entitlement denial or unknown id → `articleContent: null` or HTTP 401/403.

## Article fields used by this skill

| Field | Role |
|---|---|
| `originId` | Stable fetch id |
| `sourceUrl` | Canonical WSJ URL |
| `articleHeadline` | `TextAndDecorations` title |
| `standFirst` | `ParagraphArticleBody` dek |
| `authors[]` | `{ text, id, content… }` when present |
| `articleByline` | `TextAndDecorations`, e.g. `By Jane Doe` (fallback when `authors` empty) |
| `sectionName`, `columnName`, `page` | Section metadata |
| `publishedDateTimeUtc`, `updatedDateTimeUtc` | Timestamps |
| `languageCode` | e.g. `en-us` |
| `articleBody[]` | Ordered body blocks |

## `TextAndDecorations`

```text
textAndDecorations.flattened.text
textAndDecorations.flattened.decorations[]
  decorationType: LINK | BOLD | ITALIC | PERSON | COMPANY | BREAK | DEFAULT
  startIndex, decorationLength
  decorationMetadata (LINK → { uri, linkType, upstreamOriginId })
```

## `articleBody` typename map

| `__typename` | Markdown handling |
|---|---|
| `ParagraphArticleBody` | Paragraph; apply LINK/BOLD/ITALIC |
| `BlockquoteArticleBody` | Blockquote (`>`) |
| `TaglineArticleBody` | Italic closing line |
| `ImageArticleBody` | Image + caption/credit |
| `AudioArticleBody` | Linked audio/podcast line |
| `VideoArticleBody` | Linked video line + caption |
| `NewsletterInsetArticleBody` | Skip (no textual content in capture) |

## Public URL → origin id

Resolution is handled by `scripts/resolve_origin_id.py` (browser-rendered public
metadata only):

- only `__NEXT_DATA__.props.pageProps.articleData` is inspected;
- its `sourceUrl`/`canonicalUrl` must match the requested article path;
- `originId` and `articleTrackingMeta.articleId` must agree when both exist;
- absence of that dedicated object is rejected, even if another script has a
  single related-story `articleId`;
- a `/webview/<origin id>` URL supplies the id directly.

Related/recommended stories carry their own `originId`/`articleId` values, so no
"first match in the HTML" or "most frequent `SB…`" heuristic is used: an
ambiguous result stops the run instead of guessing. Fetch the body only
afterwards, with the user's token, through `ArticleContent` — never scrape
article HTML as a substitute for the entitled API body.
