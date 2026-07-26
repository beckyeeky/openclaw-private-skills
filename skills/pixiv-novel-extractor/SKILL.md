---
name: pixiv-novel-extractor
description: >
  Extract full text from Pixiv novels (all-ages public AJAX, or R-18 via App webview + refresh_token) from a URL/share text/bare ID, export Markdown or JSON. Use when the user wants to 保存/总结 Pixiv 小说全文, parse a novel link, manage a Pixiv App refresh token, or fetch App recommendations. R-18 empty-body → scripts/extract-r18-webview.mjs.
metadata: {"openclaw":{"emoji":"📚","privacy":"Public novel URLs and optional Pixiv refresh tokens are sent to Pixiv endpoints for extraction and recommendation lookups. Tokens are stored locally in ~/.pixiv-novel-extractor/config.json only after successful verification.","requires":{"bins":["node"]},"optional":{"env":["PIXIV_REFRESH_TOKEN"],"config":["~/.pixiv-novel-extractor/config.json"]}}}
allowed-tools: Bash(node:*)
---

# Pixiv Novel Extraction with `node`

Extract Pixiv novel text into Markdown files, keep embedded image positions, and optionally save a Pixiv App `refresh_token` for recommendations and **R-18 / login-gated** full text.

## Quick Start

```bash
node scripts/pixiv-novel.mjs extract "https://www.pixiv.net/novel/show.php?id=28063332"
node scripts/pixiv-novel.mjs extract "28063332" --format both
node scripts/pixiv-novel.mjs auth
node scripts/pixiv-novel.mjs recommended
# R-18 / empty body fallback (needs saved refresh_token):
node scripts/extract-r18-webview.mjs "23924083" -o /tmp/Pixiv-Novel-Skill
```

Default extract output directory:

```text
<workspace>/Pixiv-Novel-Skill/<novelId>_<slug>/
or
<system-temp>/Pixiv-Novel-Skill/<novelId>_<slug>/
```

Default recommendation output directory:

```text
<workspace>/Pixiv-Novel-Skill/recommended_<timestamp>/
or
<system-temp>/Pixiv-Novel-Skill/recommended_<timestamp>/
```

## Commands

### Extract a novel (all-ages public first)

All-ages public novels need no login:

```bash
node scripts/pixiv-novel.mjs extract "<url-or-id>"
node scripts/pixiv-novel.mjs extract "<url-or-id>" --format md
node scripts/pixiv-novel.mjs extract "<url-or-id>" --format json
node scripts/pixiv-novel.mjs extract "<url-or-id>" --format both -o novel-out
```

Supported input forms:

- bare novel ID
- standard Pixiv URL
- URL-encoded Pixiv URL
- share text that contains a Pixiv novel URL

### R-18 / empty-content fallback (auth required)

If `extract` succeeds but **metadata only** (`content` empty / `content_len 0`), the novel is almost always **R-18** (`xRestrict: 1`). Public AJAX strips body without a logged-in session.

**Do not stop.** Use saved App token + webview:

```bash
# requires prior: node scripts/pixiv-novel.mjs auth  (or PIXIV_REFRESH_TOKEN)
node scripts/extract-r18-webview.mjs "<url-or-id>" --format both -o /tmp/Pixiv-Novel-Skill
```

Token resolution matches `recommended`: `--token-stdin` → `PIXIV_REFRESH_TOKEN` → `~/.pixiv-novel-extractor/config.json`.

Details: [references/pixiv-endpoints.md](references/pixiv-endpoints.md), script `scripts/extract-r18-webview.mjs`.

### Save a refresh token once

Use this only when the user wants Pixiv App recommendations or asks to save/verify a Pixiv `refresh_token`.

```bash
node scripts/pixiv-novel.mjs auth
node scripts/pixiv-novel.mjs auth --verify
node scripts/pixiv-novel.mjs auth --show
node scripts/pixiv-novel.mjs auth --clear
```

The token is verified first, then saved to `~/.pixiv-novel-extractor/config.json`.

### Fetch recommended novels

Token resolution order:

1. `--token-stdin`
2. `PIXIV_REFRESH_TOKEN`
3. `~/.pixiv-novel-extractor/config.json`

```bash
node scripts/pixiv-novel.mjs recommended
node scripts/pixiv-novel.mjs recommended --format both
node scripts/pixiv-novel.mjs recommended --token-stdin
```

When `--token-stdin` is used, pipe only the raw token:

```bash
echo "PIXIV_REFRESH_TOKEN" | node scripts/pixiv-novel.mjs recommended --token-stdin
```

## Output Behavior

- `--format md` writes Markdown only.
- `--format json` writes structured JSON only.
- `--format both` writes both files.
- Without `-o`, extract writes into `workspace/Pixiv-Novel-Skill/...` when invoked from a workspace, otherwise into the system temp directory.
- Relative `-o` paths are rooted at the workspace or system temp directory, not inside the skill folder.
- Extracted novel files are named from the novel title, for example `测试小说.md`; when a file name already exists in the target folder, the skill appends `-2`, `-3`, and so on instead of overwriting.
- Embedded novel images stay in-place as Markdown image placeholders with a preferred public proxy URL and fallback links.
- All-ages public `extract` does not return R-18 body text; use `extract-r18-webview.mjs` when content is empty.
- Truly private / mypixiv-only / deleted novels remain unsupported.

## Pitfalls

- **R-18 empty body is not failure of the novel ID.** `ajax/novel/{id}` returns title/tags/`xRestrict:1` but `content: null` without session. Always fall back to webview path.
- **`/v1/novel/text` is dead (404).** Do not use it. App metadata `v2/novel/detail` also has **no text field** — only webview carries full text.
- **Webview HTML is not JSON.** Parse `window.pixiv` → `value.novel.text` (see script). Plain `web_extract` / browser login wall will not get R-18 body.
- Token already saved under `~/.pixiv-novel-extractor/config.json` on this host — reuse; do not re-ask unless `auth --verify` fails.

## Agent Rules

- Prefer `extract` first for any novel URL/ID.
- If output MD/JSON has empty `## Content` / empty `content`, immediately run `scripts/extract-r18-webview.mjs` with the same ID (reuse saved token). Do not tell the user the novel is unreadable until webview also fails.
- Use `auth` when token missing/invalid, for recommendations, or when user asks to save/verify a `refresh_token`.
- Do not ask the user to paste the token repeatedly once `auth` succeeds; reuse the saved config.
- Do not claim R-18 is impossible if a refresh_token is available.
- Keep `SKILL.md` lean and consult [references/pixiv-endpoints.md](references/pixiv-endpoints.md) when API behavior or token flow matters.

## Summarize for the user (玩法 / 内容)

When the user asks to 总结玩法/内容 (not just 保存全文), after a successful extract:

1. Read full cleaned text (R-18 path if needed). Pull sequel IDs from caption (`novel/########` or pixiv novel links).
2. Reply in **concise Chinese** (Beck: 简练直接). Prefer this skeleton over long prose:

| Section | What to put |
|---|---|
| **基本信息** | title, author, ID+link, tags, length/pages, prequel/sequel links |
| **玩法** | genre mechanics / fetish rules (e.g. 人格排泄步骤、触发条件、旁观结构) — not game UI |
| **内容梗概** | numbered beat sheet, spoiler-ok unless asked otherwise |
| **一句话** | single-line hook |

3. For multi-part works: one table **对照前/后篇** if both exist; offer sequel summary only if user did not already ask for it.
4. Do not dump raw novel text into chat unless they asked to 保存/导出全文.
