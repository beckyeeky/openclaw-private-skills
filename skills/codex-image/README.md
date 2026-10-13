# Codex Image Generation

Image generation via OpenAI's Codex CLI backend. Codex is the only automatic
engine; if it fails, `generate.py` reports the error and stops. Gemini is
available as a manual opt-in only.

## Features

- **Primary engine**: Codex (`scripts/generate.py`, `gpt-5.4`)
- **Gemini**: manual opt-in only (`scripts/gemini-generate.py`) — never
  selected automatically and never used as a fallback
- **Reference images**: pass one existing image explicitly as a style/character
  reference (path only, no auto-discovery)
- **Retry**: up to 3 attempts, only for 401 (token refresh), 429 and 5xx.
  Content-filter and other errors are **not** retried — see `SKILL.md` for the
  retry table and for the optional, agent-driven moderation-navigation
  pipeline (`scripts/bypass_pipeline.py`)
- **Telegram delivery**: `scripts/send_album.py` posts a photo album
  (requires `TELEGRAM_BOT_TOKEN`)

## Requirements

- Codex CLI installed and authenticated (`codex login status`, credentials at
  `~/.codex/auth.json`)
- Python 3 (stdlib only for `generate.py`; `requests` for `send_album.py`)

## Directory Structure

```
codex-image/
├── SKILL.md              # Agent instructions
├── README.md
├── LICENSE
├── scripts/
│   ├── generate.py        # Main generation script (Codex)
│   ├── bypass_pipeline.py # Opt-in moderation-navigation pipeline
│   ├── gemini-generate.py # Gemini fallback (opt-in only)
│   └── send_album.py      # Send a photo album to Telegram
├── references/
│   ├── codex-device-auth.md
│   ├── gemini-image-gen.md
│   ├── multi-reference-stitching.md
│   ├── shell-quoting.md
│   └── telegram-reference-images.md
└── tests/
    └── test_generate_offline.py  # Offline contract tests (no credentials, no network)
```

## Usage

Prefer stdin JSON — the prompt never appears in `ps`, shell history or logs.
Relative paths below are relative to `{baseDir}`.

```bash
# Generate image
echo '{"prompt": "a cat in space"}' | python3 scripts/generate.py

# With reference image
echo '{"prompt": "make it cyberpunk", "reference": "./ref.jpg"}' | python3 scripts/generate.py

# From a JSON file
python3 scripts/generate.py --prompt-file /tmp/prompt.json

# Telegram album (2–10 photos)
TELEGRAM_BOT_TOKEN="xxx" python3 scripts/send_album.py --chat-id "-100123456" pic1.png pic2.png
```

`stdout` is JSON only (one object per run); log lines go to stderr. Prompts are
validated on their UTF-8 byte length (max 64 KiB) and input is read with a
bounded read (64 KiB prompt + 1 MiB overhead), so a document that fits the
budget is parsed in full and never truncated mid-parse. A document past the
budget is dropped before parsing and reported as `input_too_large`, because its
prompt size cannot be determined; an unpaired surrogate escape in the prompt is
rejected as `invalid_input` rather than crashing.

The positional-argv form (`python3 scripts/generate.py "a cat in space"`) still
works but is deprecated: it leaks the prompt into `ps` and shell history.

## Tests

```bash
python3 -m unittest discover -s skills/codex-image/tests -v
```

The tests are fully offline: they use a temporary `HOME` with a dummy
`auth.json`, block outbound calls, and never generate an image.

## License

MIT
