#!/usr/bin/env node
/**
 * Model Hub Manager - 中转站模型管理器
 * 一键添加模型和 Provider，自动同步配置
 * 
 * 模型管理:
 *   node add-model.mjs model add <provider> <model-id> [alias]
 *   node add-model.mjs model remove <provider> <model-id>
 *   node add-model.mjs model list
 * 
 * Provider 管理:
 *   node add-model.mjs provider add <name> <base-url> [api-key]
 *   node add-model.mjs provider remove <name>
 *   node add-model.mjs provider list
 */

import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

const CONFIG_PATH = join(homedir(), '.hermes', 'config.yaml');

// 默认模型模板
const MODEL_TEMPLATE = {
  reasoning: false,
  input: ["text"],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow: 200000,
  maxTokens: 64000
};

// 默认 provider 模板
const PROVIDER_TEMPLATE = (baseUrl, apiKey) => ({
  baseUrl,
  apiKey: apiKey || "YOUR_API_KEY_HERE",
  api: "openai-completions",
  models: []
});

function loadConfig() {
  try {
    return JSON.parse(readFileSync(CONFIG_PATH, 'utf8'));
  } catch (e) {
    console.error('❌ 无法读取配置:', e.message);
    process.exit(1);
  }
}

function saveConfig(config) {
  writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
  console.log('✅ 配置已保存');
}

// ========== Provider 管理 ==========

function addProvider(config, name, baseUrl, apiKey) {
  if (!config.models) config.models = { providers: {} };
  if (!config.models.providers) config.models.providers = {};
  
  const exists = config.models.providers[name];
  if (exists) {
    console.log(`⚠️ Provider "${name}" 已存在，更新配置...`);
  }

  config.models.providers[name] = PROVIDER_TEMPLATE(baseUrl, apiKey);
  console.log(`✅ 已添加 Provider: ${name}`);
  console.log(`   Base URL: ${baseUrl}`);
  console.log(`   API Key: ${apiKey ? '已配置' : '请手动修改配置添加 API Key'}`);
  
  return config;
}

function removeProvider(config, name) {
  if (!config.models?.providers?.[name]) {
    console.error(`❌ Provider "${name}" 不存在`);
    return;
  }

  // 检查是否还有模型
  const models = config.models.providers[name].models || [];
  if (models.length > 0) {
    console.error(`❌ Provider "${name}" 下还有 ${models.length} 个模型，请先移除模型`);
    console.log(`   使用: node add-model.mjs model remove ${name} <model-id>`);
    return;
  }

  delete config.models.providers[name];
  console.log(`✅ 已移除 Provider: ${name}`);
  return config;
}

function listProviders(config) {
  console.log('\n🔌 当前配置的 Providers:\n');
  
  const providers = config.models?.providers || {};
  const entries = Object.entries(providers);
  
  if (entries.length === 0) {
    console.log('   (暂无 Providers)');
    return;
  }

  for (const [name, provider] of entries) {
    const modelCount = provider.models?.length || 0;
    const apiKeyStatus = provider.apiKey && provider.apiKey !== 'YOUR_API_KEY_HERE' 
      ? '✓ 已配置' 
      : '✗ 未配置';
    console.log(`\n🔹 ${name} (${modelCount} 个模型)`);
    console.log(`   Base URL: ${provider.baseUrl || 'N/A'}`);
    console.log(`   API Key: ${apiKeyStatus}`);
    console.log(`   API Type: ${provider.api || 'openai-completions'}`);
  }
  
  console.log('\n💡 使用方式:');
  console.log('   查看模型: node add-model.mjs model list');
  console.log('   添加模型: node add-model.mjs model add <provider> <model-id> [alias]');
}

// ========== 模型管理 ==========

function addModel(config, providerName, modelId, alias) {
  // 确保 provider 存在
  if (!config.models?.providers?.[providerName]) {
    console.error(`❌ Provider "${providerName}" 不存在`);
    console.log(`\n💡 请先添加 Provider:`);
    console.log(`   node add-model.mjs provider add ${providerName} <base-url> [api-key]`);
    process.exit(1);
  }

  const provider = config.models.providers[providerName];
  if (!provider.models) provider.models = [];
  
  const fullModelId = `${providerName}/${modelId}`;
  
  // 检查是否已存在
  const exists = provider.models.some(m => m.id === modelId);
  if (exists) {
    console.log(`⚠️ 模型 "${modelId}" 已存在，更新别名...`);
  } else {
    // 添加到 models.providers
    provider.models.push({
      id: modelId,
      name: modelId,
      ...MODEL_TEMPLATE
    });
    console.log(`✅ 已添加模型: ${fullModelId}`);
  }

  // 添加到 agents.defaults.models（设置别名）
  if (!config.agents) config.agents = { defaults: { models: {} } };
  if (!config.agents.defaults) config.agents.defaults = { models: {} };
  if (!config.agents.defaults.models) config.agents.defaults.models = {};
  
  const existingEntry = config.agents.defaults.models[fullModelId];
  if (existingEntry) {
    if (alias && existingEntry.alias !== alias) {
      existingEntry.alias = alias;
      console.log(`📝 更新别名: ${fullModelId} → "${alias}"`);
    }
  } else {
    config.agents.defaults.models[fullModelId] = alias ? { alias } : {};
    console.log(`✅ 已添加别名映射: ${fullModelId}${alias ? ` → "${alias}"` : ''}`);
  }

  return config;
}

function removeModel(config, providerName, modelId) {
  const provider = config.models?.providers?.[providerName];
  if (!provider) {
    console.error(`❌ Provider "${providerName}" 不存在`);
    return;
  }

  const fullModelId = `${providerName}/${modelId}`;
  
  // 从 models.providers 移除
  const modelIndex = provider.models?.findIndex(m => m.id === modelId);
  if (modelIndex > -1) {
    provider.models.splice(modelIndex, 1);
    console.log(`✅ 已移除模型: ${fullModelId}`);
  } else {
    console.error(`❌ 模型 "${modelId}" 不存在于 Provider "${providerName}"`);
    return;
  }

  // 从 agents.defaults.models 移除
  if (config.agents?.defaults?.models?.[fullModelId]) {
    delete config.agents.defaults.models[fullModelId];
    console.log(`✅ 已移除别名映射: ${fullModelId}`);
  }

  return config;
}

function listModels(config) {
  console.log('\n📋 当前配置的模型:\n');
  
  const providers = config.models?.providers || {};
  const entries = Object.entries(providers);
  
  if (entries.length === 0) {
    console.log('   (暂无 Providers)');
    return;
  }

  for (const [providerName, provider] of entries) {
    const models = provider.models || [];
    console.log(`\n🔹 ${providerName} (${models.length} 个模型)`);
    
    if (models.length === 0) {
      console.log('   (暂无模型)');
    } else {
      for (const model of models) {
        const fullId = `${providerName}/${model.id}`;
        const agentEntry = config.agents?.defaults?.models?.[fullId];
        const alias = agentEntry?.alias ? ` (别名: ${agentEntry.alias})` : '';
        console.log(`   • ${model.id}${alias}`);
      }
    }
  }
  
  console.log('\n💡 使用方式:');
  console.log('   /model provider/model-id  或  /model 别名');
}

// ========== CLI ==========

const [,, resource, command, ...args] = process.argv;

// 解析参数（支持直接输入或不输入 resource 的向后兼容）
function showHelp() {
  console.log(`
🤖 Model Hub Manager - 中转站模型管理器

📦 Provider 管理:
  provider add <name> <base-url> [api-key]  添加 Provider
  provider remove <name>                    移除 Provider（需先移除所有模型）
  provider list                             列出所有 Providers

🎯 模型管理:
  model add <provider> <model-id> [alias]   添加模型（可选别名）
  model remove <provider> <model-id>        移除模型
  model list                                列出所有模型

📝 示例:
  # 添加 AI Max Provider
  node add-model.mjs provider add aimax https://api.aimax.com/v1 sk-xxx

  # 添加模型
  node add-model.mjs model add aimax claude-3-opus opus
  node add-model.mjs model add openrouter google/gemini-3.1-pro gemini31

  # 查看配置
  node add-model.mjs provider list
  node add-model.mjs model list
`);
}

// 主路由
if (!resource || resource === 'help' || resource === '--help' || resource === '-h') {
  showHelp();
  process.exit(0);
}

// 处理向后兼容：如果没有指定 resource，直接输入了 command
let effectiveResource = resource;
let effectiveCommand = command;
let effectiveArgs = args;

if (['add', 'remove', 'rm', 'list', 'ls'].includes(resource) && !command) {
  // 旧格式: node add-model.mjs add provider model alias
  console.log('⚠️ 警告: 使用新格式更清晰');
  console.log('   旧: node add-model.mjs add <provider> <model> [alias]');
  console.log('   新: node add-model.mjs model add <provider> <model> [alias]\n');
  
  // 重定向到 model add
  effectiveResource = 'model';
  effectiveCommand = resource;  // 原来的 command 其实是 resource
  effectiveArgs = [command, ...args];  // 剩下的参数
}

switch (effectiveResource) {
  case 'provider': {
    switch (effectiveCommand) {
      case 'add': {
        const [name, baseUrl, apiKey] = effectiveArgs;
        if (!name || !baseUrl) {
          console.log('Usage: node add-model.mjs provider add <name> <base-url> [api-key]');
          console.log('Example: node add-model.mjs provider add aimax https://api.aimax.com/v1 sk-xxx');
          process.exit(1);
        }
        const config = loadConfig();
        const newConfig = addProvider(config, name, baseUrl, apiKey);
        saveConfig(newConfig);
        console.log(`\n🚀 重启 Hermes 后生效: hermes gateway restart`);
        break;
      }

      case 'remove':
      case 'rm': {
        const [name] = effectiveArgs;
        if (!name) {
          console.log('Usage: node add-model.mjs provider remove <name>');
          process.exit(1);
        }
        const config = loadConfig();
        const newConfig = removeProvider(config, name);
        if (newConfig) {
          saveConfig(newConfig);
          console.log(`\n🚀 重启 Hermes 后生效: hermes gateway restart`);
        }
        break;
      }

      case 'list':
      case 'ls': {
        const config = loadConfig();
        listProviders(config);
        break;
      }

      default:
        console.log('Unknown provider command. Use: add, remove, list');
        showHelp();
    }
    break;
  }

  case 'model': {
    switch (effectiveCommand) {
      case 'add': {
        const [provider, modelId, alias] = effectiveArgs;
        if (!provider || !modelId) {
          console.log('Usage: node add-model.mjs model add <provider> <model-id> [alias]');
          console.log('Example: node add-model.mjs model add aimax claude-3-opus opus');
          process.exit(1);
        }
        const config = loadConfig();
        const newConfig = addModel(config, provider, modelId, alias);
        saveConfig(newConfig);
        console.log(`\n🚀 重启 Hermes 后生效: hermes gateway restart`);
        break;
      }

      case 'remove':
      case 'rm': {
        const [provider, modelId] = effectiveArgs;
        if (!provider || !modelId) {
          console.log('Usage: node add-model.mjs model remove <provider> <model-id>');
          process.exit(1);
        }
        const config = loadConfig();
        const newConfig = removeModel(config, provider, modelId);
        if (newConfig) {
          saveConfig(newConfig);
          console.log(`\n🚀 重启 Hermes 后生效: hermes gateway restart`);
        }
        break;
      }

      case 'list':
      case 'ls': {
        const config = loadConfig();
        listModels(config);
        break;
      }

      default:
        console.log('Unknown model command. Use: add, remove, list');
        showHelp();
    }
    break;
  }

  default:
    console.log(`Unknown resource: ${effectiveResource}`);
    showHelp();
}
