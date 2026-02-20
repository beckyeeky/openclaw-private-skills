# Model Hub Manager

> 中转站模型管理器 - One-click management for OpenClaw providers and models

[![OpenClaw](https://img.shields.io/badge/OpenClaw-Skill-blue)](https://openclaw.ai)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 🤖 Overview

Model Hub Manager is an OpenClaw skill for managing AI **providers** and **models**. It simplifies the process of adding new providers, adding models with aliases, removing entries, and viewing all configurations.

### Key Features

- **Provider Management**: Add/remove/list AI service providers
- **Model Management**: Add/remove/list models with convenient aliases
- **Configuration Sync**: Auto-sync with OpenClaw config
- **User-Friendly**: Chinese CLI interface with helpful examples

## 🚀 Quick Start

### Add a Provider

```bash
node scripts/add-model.mjs provider add aimax https://api.aimax.com/v1 sk-your-api-key
```

### Add a Model

```bash
# With alias
node scripts/add-model.mjs model add aimax claude-3-opus-20240229 opus

# Without alias
node scripts/add-model.mjs model add openrouter google/gemini-3.1-pro
```

### List Configurations

```bash
# List providers
node scripts/add-model.mjs provider list

# List models
node scripts/add-model.mjs model list
```

## 📋 Requirements

- **Node.js**: Runtime environment
- **OpenClaw**: Must be installed at `~/.openclaw/`
- **Write Access**: To `~/.openclaw/openclaw.json`

## 📚 Command Reference

### Provider Management

| Command | Description |
|---------|-------------|
| `provider add <name> <base-url> [api-key]` | Add a new provider |
| `provider remove <name>` | Remove a provider |
| `provider list` | List all providers |

### Model Management

| Command | Description |
|---------|-------------|
| `model add <provider> <model-id> [alias]` | Add a model to provider |
| `model remove <provider> <model-id>` | Remove a model |
| `model list` | List all models |

## 🔄 Complete Workflow

```bash
# Step 1: Add provider
node scripts/add-model.mjs provider add aimax https://api.aimax.com/v1 sk-your-key

# Step 2: Add model with alias
node scripts/add-model.mjs model add aimax claude-3-opus-20240229 opus

# Step 3: Verify
node scripts/add-model.mjs provider list
node scripts/add-model.mjs model list

# Step 4: Restart OpenClaw
openclaw gateway restart

# Step 5: Use the model
openclaw models | grep opus
```

## 🌍 Common Providers

| Provider | Base URL |
|----------|----------|
| OpenRouter | `https://openrouter.ai/api/v1` |
| AIHubMix | `https://aihubmix.com/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| SiliconFlow | `https://api.siliconflow.cn/v1` |

## ⚙️ Configuration

All changes are saved to `~/.openclaw/openclaw.json`:

```json
{
  "models": {
    "providers": {
      "aimax": {
        "baseUrl": "https://api.aimax.com/v1",
        "apiKey": "sk-your-key",
        "api": "openai-completions",
        "models": [...]
      }
    }
  }
}
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.
