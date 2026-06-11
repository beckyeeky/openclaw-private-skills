---
name: codex-image
description: Image generation via Codex (gpt-5.4). No filter bypass. Secure prompt/stdin.
version: 2.0.0
author: Hermes Agent
license: MIT
category: creative
tags: [image-generation, codex, openai, gpt-5.4, telegram]
triggers:
  - generate image with codex
  - codex image generation
  - codex图片生成
  - 用codex生成图片
metadata:
  hermes:
    tags: [image-generation, codex, openai, gpt-5.4]
    related_skills: [stable-diffusion]
---

# Codex Image Generation Skill v2.0.0

**Core rule:** Codex (gpt-5.4) is the only image generation engine. If it fails, **report the error** — no automatic fallback. Gemini is manual opt-in only.

## Security & Design Changes (v2.0.0)

- **Prompt from stdin JSON** — no argv leakage. Prompt never appears in `ps`, shell history, or process listing.
- **No filter bypass** — removed all synonym substitution, logical framing, and foreground dilution strategies.
- **No hardcoded credentials** — Codex token read from `~/.codex/auth.json`; Telegram token from env vars only.
- **Secure output** — images saved to `~/.hermes/codex-images/` with UUID filenames, `0700` directory, `0600` file perms.
- **Simple retry** — max 3 attempts, only on 401/429/5xx. No 11-attempt filter bypass loop.
- **stdout = JSON only** — structured output for scripting. Stderr for log messages (no prompt text).

## Usage

### Preferred: stdin JSON

```bash
echo '{"prompt": "a cat in space"}' | python3 generate.py

# With reference image
echo '{"prompt": "make it cyberpunk", "reference": "/path/to/image.jpg"}' | python3 generate.py

# Multi-word, any characters — no shell escaping needed
echo '{"prompt": "电影级冷暖光对冲, 玻璃感晕染唇釉"}' | python3 generate.py
```

### Alternative: --prompt-file

```bash
cat > /tmp/prompt.json << 'EOF'
{"prompt": "a cat in space", "reference": "/path/to/ref.jpg"}
EOF
python3 generate.py --prompt-file /tmp/prompt.json
```

### Deprecated: positional argv

```bash
python3 generate.py "a cat in space"
```

⚠️ Positional prompts appear in `ps` listings and shell history. Use stdin JSON instead.

## Output

The script prints a single JSON line to stdout:

```json
{"status": "ok", "path": "/root/.hermes/codex-images/abc123.png", "prompt_sha256": "a1b2...", "size_bytes": 123456, "model": "gpt-5.4"}
```

On failure:
```json
{"status": "error", "error": "description", "code": "error_code", "prompt_sha256": "a1b2..."}
```

Use the `path` field for the MEDIA protocol: `MEDIA:/root/.hermes/codex-images/abc123.png`

## Python API

```python
from generate import generate_image, save_image_secure

result = generate_image("your prompt", reference_b64=ref_b64, ref_mime="image/jpeg")
if result and result.get("image_b64"):
    path = save_image_secure(result["image_b64"])
```

## Reference Images

Reference images must be **explicitly passed** — no auto-discovery from global caches.

With stdin JSON (preferred):
```bash
echo '{"prompt": "use this style", "reference": "/path/image.jpg"}' | python3 generate.py
```

With positional prompt:
```bash
python3 generate.py "use this style" --reference /path/image.jpg
```

The script validates MIME types from magic bytes (not extension), rejects symlinks, and enforces a 20MB size limit.

## Gemini Image Generation — Manual Opt-in Only

Use only when the user explicitly asks for Gemini.

```bash
# Basic generation
uv run /root/.hermes/skills/image-generation/codex-image/scripts/gemini-generate.py \
  --prompt "your description" --filename "/tmp/gemini_out.png"

# 2K resolution
uv run ... --prompt "..." --filename "/tmp/gemini_out.png" --resolution "2K"

# Edit existing image
uv run ... --prompt "edit instructions" --filename "/tmp/gemini_edited.png" \
  --input-image "/path/in.png" --resolution "2K"
```

**Requirements:** `GEMINI_API_KEY` env var.
**Caveat:** No reference image support.

## Telegram Photo Albums

```bash
# env vars required (no hardcoded tokens)
TELEGRAM_BOT_TOKEN="xxx" python3 scripts/send_album.py \
  --chat-id "-100123456" --thread-id 55 \
  pic1.png pic2.png pic3.png --caption "My album"
```

- Max 10 photos per album
- Token from `TELEGRAM_BOT_TOKEN` env var, chat_id from `--chat-id` or `CHAT_ID` env var
- No shell injection — uses `requests` params, not string building

## Retry Behavior

| Condition | Retry | Max |
|-----------|-------|-----|
| 401 (token expired) | Auto-refresh + retry | 3 |
| 429 (rate limit) | Exponential backoff (2s, 4s, 8s) | 3 |
| 5xx (server error) | Exponential backoff | 3 |
| Content filtered / other 4xx | **No retry** | 1 |
| Network error | **No retry** | 1 |

All retry counts include the initial attempt.

## Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| `no_auth` | No Codex token in ~/.codex/auth.json | Run `codex login --device-auth` |
| `auth_stale` | Token refresh chain broken | Run `codex login --device-auth` |
| `http_429` | Rate limited | Wait and retry |
| `invalid_input` | Bad JSON or no prompt | Check stdin format |
| `ref_not_found` | Reference file doesn't exist | Check path |
| `ref_symlink` | Reference is a symlink | Pass real file |
| `prompt_too_large` | >64 KiB prompt | Shorten prompt |
| `save_failed` | Could not write output | Check disk space/permissions |
