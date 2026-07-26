# Hermes Private Skills

> A collection of custom Hermes skills for enhanced AI workflows

[![Hermes](https://img.shields.io/badge/Hermes-Ready-blue)](https://hermes-agent.nousresearch.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 📦 Included Skills

### 1. 🎯 Trivia Quiz
Fun trivia game with inline buttons and detailed explanations

- **Features**: Interactive quiz game with educational content
- **Use Case**: Entertainment and learning
- **Location**: [`trivia-quiz/`](trivia-quiz/)

[→ Read Documentation](trivia-quiz/README.md)

---

### 2. 🖼️ Codex Image Generation
Image generation via Codex (gpt-5.4)

- **Features**: Text-to-image with bypass pipeline, reference images, Telegram delivery
- **Use Case**: Generate images from text prompts
- **Location**: [`codex-image/`](codex-image/)

[→ Read Documentation](codex-image/README.md)

---

### 3. 📖 Pixiv Novel Extractor
Download and format Pixiv novels (all-ages public AJAX + R-18 App webview)

- **Features**: Public novel extract → MD/JSON; R-18 fallback via App `refresh_token` + webview; recommended novels
- **Use Case**: Save / summarize Pixiv novel full text (including login-gated R-18)
- **Location**: [`pixiv-novel-extractor/`](pixiv-novel-extractor/)

---

### 4. 📰 WeChat Article Fetch
Fetch any web article via curl+defuddle → Markdown → optional Telegra.ph publishing

- **Features**: WeChat/MicroMessenger UA bypass, Telegraph publishing, JS-rendered page fallback
- **Use Case**: Archive articles with mobile-friendly reading links
- **Location**: [`wechat-article-fetch/`](wechat-article-fetch/)

[→ Read Documentation](wechat-article-fetch/README.md)


---

### 5. 🧩 Loon Plugin Engineering
Build/debug/publish Loon `.plugin` files (MitM, Script, Argument, raw hosting pitfalls)

- **Features**: templates for reject / request+response, raw 404 matrix, 可莉 & deezertidal reference map
- **Use Case**: Loon 插件开发、TabulaBili 类维护、远程 script-path 发布
- **Location**: [`loon-plugin/`](loon-plugin/)

---

### 6. 📚 Business Reading Curator

Source-verified English long-form business reading packs with durable history and deduplication

- **Features**: Human-origin provenance scoring, advertising-risk gates, industry rotation, SQLite history, exact/event/semantic deduplication, optional OpenAI-compatible embeddings
- **Use Case**: Recurring pharma, biotech, CDMO, healthcare, and cross-industry business reading
- **Location**: [`business-reading-curator/`](business-reading-curator/)

## 🚀 Quick Start

Each skill has its own README with detailed installation and usage instructions.

```bash
# Clone the repository
git clone https://github.com/beckyeeky/hermes-private-skills.git

# Navigate to a skill
cd hermes-private-skills/ensemble-jury

# Follow the skill's README for setup
```

## 📋 Requirements

- [Hermes](https://hermes-agent.nousresearch.com) installed and configured
- Node.js runtime environment
- Git (for cloning)

## 📄 License

All skills in this repository are licensed under the MIT License.

See individual [LICENSE](LICENSE) files in each skill directory for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 🙏 Acknowledgments

- Built for [Hermes](https://hermes-agent.nousresearch.com)
- Inspired by the Hermes community
