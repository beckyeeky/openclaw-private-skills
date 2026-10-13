# Pixiv Endpoints Used by This Skill

## 1. Public novel AJAX

- Endpoint: `https://www.pixiv.net/ajax/novel/{id}`
- Purpose: Metadata, tags, series nav, embedded images; **body only when all-ages / unauthenticated-readable**.
- Authentication: None.
- **R-18 pitfall:** When `body.xRestrict === 1` (or body is present but `content` is `null`/empty), full text is gated. Title/description/tags still return. Do **not** treat empty content as "novel not found".

## 2. Pixiv OAuth token exchange

- Endpoint: `https://oauth.secure.pixiv.net/auth/token`
- Purpose: Exchange App `refresh_token` → short-lived `access_token`.
- Auth: `refresh_token` + Pixiv App client id/secret (in `scripts/lib/pixiv-api.mjs`).
- Notes: Skill verifies before save; does not persist `access_token`. Config: `~/.pixiv-novel-extractor/config.json`.

## 3. Pixiv App recommendations

- Endpoint: `https://app-api.pixiv.net/v1/novel/recommended`
- Purpose: Recommended novels for the logged-in App account.
- Auth: Bearer `access_token`.
- Token resolution: `--token-stdin` → `PIXIV_REFRESH_TOKEN` → config file.

## 4. App novel metadata (no body text)

- Endpoint: `https://app-api.pixiv.net/v2/novel/detail?novel_id={id}`
- Purpose: Caption, tags, `text_length`, `page_count`, bookmark counts.
- Auth: Bearer `access_token`.
- **Does not include novel body.** Useful only for stats / confirming access.

## 5. App novel webview (R-18 full text) — preferred auth path

- Endpoint: `https://app-api.pixiv.net/webview/v2/novel?id={id}`  
  (`webview/v1/novel?id=` also works; same payload shape.)
- Headers: App-style `Authorization: Bearer {access_token}`, `app-os`, `user-agent` (see `getAppApiHeaders` / extract script).
- Response: HTML page with an inline script assigning the payload, e.g. `window.pixiv = { value: { novel: { text, title, tags, ... }, ... } }`.
- Full text path: the strict literal parser locates the payload **member-first** (prefers `value: { … }`, falls back to the outer `window.pixiv = { … }`), string-aware, then reads **`novel.text`** (string, may contain `[newpage]` and Pixiv ruby tags). Decimal numeric keys (embedded-image ids) are supported; expressions are rejected and nothing is ever evaluated.
- Parse failures report only the byte offset and the offending construct — never a snippet of the remote body. Size budgets are UTF-8 bytes: payload ≤ 4 MiB, whole HTML ≤ 16 MiB (the wider page budget is separate so unrelated inline chrome does not cause an early rejection).
- If the payload parses but `novel.text` is missing, the cause is reported as **not determined** — this is not proof that the novel is private or deleted.
- Clean with `cleanPixivText` from `scripts/lib/pixiv-api.mjs` before writing MD.

### Dead / do-not-use for body

| Endpoint | Status | Note |
|---|---|---|
| `GET /v1/novel/text?novel_id=` | **404** | Deprecated; empty or error |
| `GET /v2/novel/text?novel_id=` | **404** | Same |
| Public ajax alone for R-18 | `content: null` | Metadata only |

## Extraction decision tree

1. Run `pixiv-novel.mjs extract <id>`.
2. If `content` non-empty → done.
3. If empty but metadata OK (or `xRestrict: 1`) → `extract-r18-webview.mjs <id>` with saved token.
4. If OAuth fails → `auth --verify` / re-auth; only then report blocked.
5. If webview 403/empty after valid token → report blocked/problem, but do **not** assert the novel is private/mypixiv/deleted unless there is direct evidence; a located payload with no `novel.text` is reported as "cause not determined".

## Implementation pointer

Runnable fallback: `scripts/extract-r18-webview.mjs` (parses webview HTML with the strict literal parser, then uses the same managed output directory rules, overwrite protection, and Markdown renderer as `extract`).
