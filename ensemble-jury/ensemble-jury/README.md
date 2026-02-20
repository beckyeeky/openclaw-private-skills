# Ensemble Jury

> Multi-model ensemble analysis with blind review mechanism

[![OpenClaw](https://img.shields.io/badge/OpenClaw-Skill-blue)](https://openclaw.ai)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## ⚖️ Overview

Ensemble Jury is an OpenClaw skill that implements a "blind review" mechanism similar to academic peer review. It gathers intelligence, solicits independent answers from multiple top-tier models, and uses Claude as a separate arbitrator to synthesize a final, unbiased, comprehensive answer.

### Key Features

- **Intelligence Gathering**: Real-time data via Perplexity & Google Search
- **Blind Review**: 4 independent reviewers (Kimi, Gemini Pro, DeepSeek Reasoner, GPT-5.2)
- **Independent Arbitration**: Claude Sonnet 4.6 as the neutral judge
- **Anonymous Evaluation**: Reviewers don't know each other's existence

## 🚀 Quick Start

```bash
# Using activation keywords
ensemble How will quantum computing impact cryptography?
multi-model Analyze China's AI development in 2025
盲审 评估当前全球经济形势

# Or run directly
node scripts/ensemble.mjs "Your question here"
```

## 📋 Requirements

- **Node.js**: Runtime environment
- **OpenClaw**: Must be installed and configured
- **Skills**: `perplexity-safe`, `google-search`
- **Agents**: `kimi`, `gemini`, `deepseek`, `gpt-5.2`, `claude`

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Phase 1: Intelligence Gathering (Parallel)             │
│  ├── Perplexity Search                                  │
│  └── Google Search                                      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Phase 2: Blind Review (Parallel, Anonymous)            │
│  ├── Reviewer A (Kimi K2.5)                             │
│  ├── Reviewer B (Gemini 3 Pro)                          │
│  ├── Reviewer C (DeepSeek Reasoner)                     │
│  └── Reviewer D (GPT-5.2)                               │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Phase 3: Independent Arbitration                       │
│  └── Claude Sonnet 4.6 (Neutral Judge)                  │
│      └── Final comprehensive answer                     │
└─────────────────────────────────────────────────────────┘
```

## 🎯 Activation Keywords

- `ensemble <question>`
- `multi-model <question>`
- `综合 <question>`
- `盲审 <question>`
- `jury <question>`
- `committee review <question>`

## ✅ Use Cases

- Complex analysis (market trends, political situations)
- Synthesizing diverse viewpoints
- Topics requiring high accuracy and neutrality
- Multi-perspective research questions

## ❌ Anti-Patterns

- Simple factual queries
- Code generation tasks
- Quick conversational responses

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 🙏 Acknowledgments

- Built for [OpenClaw](https://openclaw.ai)
- Inspired by academic peer review processes
