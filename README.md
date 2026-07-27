# OpenClaw Private Skills

Reusable Agent Skills for OpenClaw and other Agent-Skills-compatible runtimes.

## Install with `npx`

The [`skills`](https://skills.sh) CLI downloads this repository, discovers every
`skills/<name>/SKILL.md`, and installs the selected skills for your agent. It is
run through `npx`; do not install a separate global CLI.

```bash
# Inspect the available skills without installing them.
npx skills@latest add beckyeeky/openclaw-private-skills --list

# Install one skill for OpenClaw in the current project.
npx skills@latest add beckyeeky/openclaw-private-skills \
  --skill pixiv-novel-extractor --agent openclaw

# Install every public skill for OpenClaw in the current project.
npx skills@latest add beckyeeky/openclaw-private-skills \
  --skill '*' --agent openclaw

# Make every skill available to OpenClaw globally.
npx skills@latest add beckyeeky/openclaw-private-skills \
  --skill '*' --agent openclaw --global
```

The default install is project-local. Add `--copy` if the target environment
cannot use symlinks. Each skill documents its own runtime requirements and any
credentials it needs; installing a skill does not install its runtime
dependencies or configure external accounts.

## Included skills

| Skill | Purpose |
| --- | --- |
| [`business-reading-curator`](skills/business-reading-curator/) | Curate source-verified English business reading packs with durable history and deduplication. |
| [`codex-image`](skills/codex-image/) | Generate images through Codex and send Telegram albums. |
| [`loon-plugin`](skills/loon-plugin/) | Build, debug, package, and publish Loon `.plugin` / `.lpx` files. |
| [`pixiv-novel-extractor`](skills/pixiv-novel-extractor/) | Extract public and authenticated Pixiv novels into Markdown or JSON. |
| [`trivia-quiz`](skills/trivia-quiz/) | Run an inline-button trivia game using deterministic question data. |
| [`wechat-article-fetch`](skills/wechat-article-fetch/) | Fetch web articles into Markdown and optionally publish them to Telegra.ph. |
| [`wsj-article-reader`](skills/wsj-article-reader/) | Retrieve and archive WSJ articles the user is already authorized to read, using a local private token. |

## Repository layout

```text
skills/
  <skill-name>/
    SKILL.md       # Agent instructions and required name/description metadata
    scripts/        # Deterministic helpers, when needed
    references/     # Load-on-demand technical or domain reference material
    templates/      # Reusable output templates, when needed
```

See [AGENTS.md](AGENTS.md) before adding or changing a skill. It documents the
repository contract for agents and contributors.

## Development

Validate discovery locally before publishing:

```bash
npx skills@latest add . --list
```

This repository deliberately has no root `package.json`: `npx` resolves and
runs the published `skills` CLI, while each skill keeps only the runtime assets
it needs.

## License

Unless a skill directory states otherwise, this repository is available under
the [MIT License](LICENSE).
