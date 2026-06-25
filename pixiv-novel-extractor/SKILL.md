---
name: pixiv-novel-extractor
description: >
  Extract full text from public Pixiv novels from a Pixiv novel URL, share text, or bare novel ID, and export the result to Markdown or JSON. Use when the user wants to 保存 Pixiv 小说全文, parse a Pixiv novel link, fetch a public Pixiv novel by URL/ID, manage a Pixiv App refresh token once and reuse it later, or read Pixiv recommended novels through the Pixiv App API.
metadata: {"openclaw":{"emoji":"📚","privacy":"Public novel URLs and optional Pixiv refresh tokens are sent to Pixiv endpoints for extraction and recommendation lookups. Tokens are stored locally in ~/.pixiv-novel-extractor/config.json only after successful verification.","requires":{"bins":["node"]},"optional":{"env":["PIXIV_REFRESH_TOKEN"],"config":["~/.pixiv-novel-extractor/config.json"]}}}
allowed-tools: Bash(node:*)
---

# Pixiv Novel Extraction with `node`

Extract public Pixiv novel text into Markdown files, keep embedded image positions, and optionally save a Pixiv App `refresh_token` for recommendation lookups.

## Quick Start

```bash
node scripts/pixiv-novel.mjs extract "https://www.pixiv.net/novel/show.php?id=28063332"
node scripts/pixiv-novel.mjs extract "28063332" --format both
node scripts/pixiv-novel.mjs auth
node scripts/pixiv-novel.mjs recommended
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

### Extract a public novel

No login is required for public novel extraction.

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
- Public extraction does not support private or permission-restricted novels in v1.

## Agent Rules

- Prefer `extract` first when the user only wants the full text of a public Pixiv novel.
- Use `auth` only when the user explicitly wants saved token management or recommendation access.
- Do not ask the user to paste the token repeatedly once `auth` succeeds; reuse the saved config.
- Do not claim private, restricted, or login-only Pixiv novels are supported.
- Keep `SKILL.md` lean and consult [references/pixiv-endpoints.md](references/pixiv-endpoints.md) only when API behavior or token flow matters.
