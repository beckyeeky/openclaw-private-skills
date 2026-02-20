---
name: model-hub-manager
description: Manage OpenClaw model and provider configurations. Use when the user needs to add, remove, or list AI models and providers in the OpenClaw config. Supports adding providers with baseUrl/apiKey, adding models with aliases, removing entries, and viewing all configurations. Activate on 'add model', 'remove model', 'list models', 'add provider', 'model config', or when managing OpenClaw AI configurations.
metadata:
  clawdbot:
    emoji: 🤖
    requires:
      bins: ["node"]
---

# Model Hub Manager

> 中转站模型管理器 - 一键管理 OpenClaw Provider 和模型配置

## Overview

A utility skill for managing AI **providers** and **models** in OpenClaw. It simplifies the process of:
- Adding new **providers** (with baseUrl, apiKey)
- Adding **models** to providers (with optional aliases)
- Removing obsolete entries
- Viewing all configurations

## Quick Start

### 1. Add a Provider (First Step)

Before adding models, you need to configure the provider:

```bash
node scripts/add-model.mjs provider add <name> <base-url> [api-key]
```

**Example - Add AI Max:**
```bash
node scripts/add-model.mjs provider add aimax https://api.aimax.com/v1 sk-your-api-key
```

**Example - Add without API key (configure later):**
```bash
node scripts/add-model.mjs provider add aimax https://api.aimax.com/v1
# Then manually edit ~/.openclaw/openclaw.json to add apiKey
```

### 2. Add Models to the Provider

```bash
node scripts/add-model.mjs model add <provider> <model-id> [alias]
```

**Examples:**
```bash
# Add with alias
node scripts/add-model.mjs model add aimax claude-3-opus-20240229 opus
node scripts/add-model.mjs model add aimax gpt-4o g4o

# Add without alias
node scripts/add-model.mjs model add openrouter google/gemini-3.1-pro
```

### 3. View Configurations

```bash
# List all providers
node scripts/add-model.mjs provider list

# List all models
node scripts/add-model.mjs model list
```

## Command Reference

### Provider Management

| Command | Description | Example |
|---------|-------------|---------|
| `provider add <name> <base-url> [api-key]` | Add a new provider | `provider add aimax https://api.aimax.com/v1 sk-xxx` |
| `provider remove <name>` | Remove a provider (must have no models) | `provider remove aimax` |
| `provider list` | List all providers | `provider list` |

### Model Management

| Command | Description | Example |
|---------|-------------|---------|
| `model add <provider> <model-id> [alias]` | Add a model to provider | `model add aimax claude-3-opus opus` |
| `model remove <provider> <model-id>` | Remove a model | `model remove aimax claude-3-opus` |
| `model list` | List all models | `model list` |

## Complete Workflow Example

### Scenario: Add AI Max and configure Claude 3 Opus

```bash
# Step 1: Add AI Max provider
node scripts/add-model.mjs provider add aimax https://api.aimax.com/v1 sk-your-key

# Step 2: Add Claude 3 Opus model with alias
node scripts/add-model.mjs model add aimax claude-3-opus-20240229 opus

# Step 3: Verify configuration
node scripts/add-model.mjs provider list
node scripts/add-model.mjs model list

# Step 4: Restart OpenClaw
openclaw gateway restart

# Step 5: Use the model
openclaw models | grep opus
# Output should show: aimax/claude-3-opus-20240229 → "opus"
```

## Provider Configuration Structure

When you add a provider, it creates this structure in `~/.openclaw/openclaw.json`:

```json
{
  "models": {
    "providers": {
      "aimax": {
        "baseUrl": "https://api.aimax.com/v1",
        "apiKey": "sk-your-api-key",
        "api": "openai-completions",
        "models": []
      }
    }
  }
}
```

## Model Configuration Structure

When you add a model, it creates:

```json
{
  "models": {
    "providers": {
      "aimax": {
        "models": [
          {
            "id": "claude-3-opus-20240229",
            "name": "claude-3-opus-20240229",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "contextWindow": 200000,
            "maxTokens": 64000
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "models": {
        "aimax/claude-3-opus-20240229": {
          "alias": "opus"
        }
      }
    }
  }
}
```

## Common Providers

| Provider | Base URL | Notes |
|----------|----------|-------|
| OpenRouter | `https://openrouter.ai/api/v1` | Unified API for 100+ models |
| AI Max | `https://api.aimax.com/v1` | AIHubMix's AI Max service |
| AIHubMix | `https://aihubmix.com/v1` | AIHubMix API |
| DeepSeek | `https://api.deepseek.com/v1` | DeepSeek official API |
| SiliconFlow | `https://api.siliconflow.cn/v1` | SiliconFlow API |

## Backward Compatibility

The script supports the old format for model commands:

```bash
# Old format (still works)
node add-model.mjs add aimax claude-3-opus opus

# New format (recommended)
node add-model.mjs model add aimax claude-3-opus opus
```

## Configuration Path

All changes are saved to:
```
~/.openclaw/openclaw.json
```

**Important:** After modifying the config, restart OpenClaw:
```bash
openclaw gateway restart
```

## Alias System

Aliases make model switching easier:

```bash
# Without alias
/model aimax/claude-3-opus-20240229

# With alias "opus"
/model opus
```

## Error Handling

Common errors and solutions:

| Error | Solution |
|-------|----------|
| Provider not found | First run `provider add` to create the provider |
| Model already exists | Use `model remove` first, or update alias |
| Provider has models | Remove all models before removing provider |
| Config not found | Check OpenClaw installation |

## Requirements

- **Node.js**: Runtime environment
- **OpenClaw**: Must be installed at `~/.openclaw/`
- **Write Access**: To `~/.openclaw/openclaw.json`

## Anti-Patterns

❌ **Do NOT use for**:
- Modifying model capabilities (reasoning, vision, etc.)
- Bulk operations (script is designed for one-at-a-time)
- Changing complex provider settings (use manual config edit)

✅ **Use for**:
- Quick provider setup
- Adding individual models
- Setting up convenient aliases
- Viewing current configuration

## Troubleshooting

### Provider exists but can't add model
```bash
# Check if provider exists
node scripts/add-model.mjs provider list

# If not, create it first
node scripts/add-model.mjs provider add <name> <base-url>
```

### Changes not reflecting
```bash
# Always restart after config changes
openclaw gateway restart

# Verify with
openclaw models
```
