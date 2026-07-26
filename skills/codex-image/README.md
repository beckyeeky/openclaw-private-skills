# Codex Image Generation

Image generation using OpenAI's Codex (gpt-5.4) primarily. Gemini available as manual opt-in only.

## Features

- **Primary engine**: Codex (gpt-5.4) via CLI
- **Fallback**: Gemini Pro Image (manual opt-in only)
- **Reference images**: Use existing images as style/character reference
- **Auto-retry**: 4 strategies × 3 variants when content filters trigger
- **Telegram delivery**: Direct photo sending via Hermes

## Requirements

- Codex CLI installed and authenticated (`codex login status`)
- Python 3

## Directory Structure

```
codex-image/
├── SKILL.md              # Agent instructions
├── README.md
├── LICENSE
├── scripts/
│   ├── generate.py       # Main generation script (Codex)
│   ├── gemini-generate.py # Gemini fallback (opt-in only)
│   ├── send_album.py     # Send photo album to Telegram
│   └── send_album.mjs    # JS variant of album sender
└── references/
    ├── content-filter-strategy.md
    ├── debug-notes.md
    ├── gemini-image-gen.md
    ├── multi-reference-stitching.md
    ├── shell-quoting.md
    └── telegram-reference-images.md
```

## Usage

```bash
# Generate image
python3 scripts/generate.py "a cat in space"

# With reference image
python3 scripts/generate.py "make it cyberpunk" --reference ./ref.jpg

# With verbose output
python3 scripts/generate.py "portrait" --verbose
```

## License

MIT
