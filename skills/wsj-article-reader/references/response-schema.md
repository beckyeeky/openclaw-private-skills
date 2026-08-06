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

Unauthenticated HTML for a WSJ article URL often includes the origin id as:

- `"articleId":"SB…"`
- bare `SB\d{20,}`

Use only to resolve the id the user already opened; then fetch `ArticleContent` with their token. Do not scrape full article HTML as a substitute for the entitled API body.
