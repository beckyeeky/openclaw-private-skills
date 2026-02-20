#!/usr/bin/env node
/**
 * Ensemble Jury - 多模型盲审系统
 * 
 * 流程：
 * 1. 并行搜索 (Perplexity + Google)
 * 2. 并行询问 4个模型 (Kimi, Gemini Pro, DeepSeek Reasoner, GPT-5.2)
 * 3. Claude 综合所有匿名答案
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { writeFileSync, appendFileSync, existsSync, mkdirSync } from 'fs';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = process.env.OPENCLAW_WORKSPACE || '/root/.openclaw/workspace';

// 日志目录
const LOG_DIR = path.join(WORKSPACE, '.logs');
if (!existsSync(LOG_DIR)) {
  mkdirSync(LOG_DIR, { recursive: true });
}
const ERROR_LOG = path.join(LOG_DIR, 'ensemble-jury-error.log');

// 依赖路径配置（集中管理，便于修改）
const DEPS = {
  perplexity: path.join(WORKSPACE, 'skills/perplexity-safe/scripts/perplexity_search.sh'),
  google: path.join(WORKSPACE, 'skills/google-search/scripts/search.mjs')
};

// 颜色输出
const colors = {
  reset: '\x1b[0m',
  cyan: '\x1b[36m',
  yellow: '\x1b[33m',
  green: '\x1b[32m',
  magenta: '\x1b[35m',
  red: '\x1b[31m',
  gray: '\x1b[90m'
};

function log(msg, color = 'reset') {
  console.log(`${colors[color]}${msg}${colors.reset}`);
}

function logError(source, error) {
  const timestamp = new Date().toISOString();
  const entry = `[${timestamp}] ${source}: ${error}\n`;
  try {
    appendFileSync(ERROR_LOG, entry);
  } catch (e) {
    // 如果连日志都写不了，忽略
  }
}

// 输入验证和清理
function sanitizeInput(input) {
  // 移除控制字符和潜在危险字符
  return input
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '')  // 控制字符
    .replace(/[;&|`$]/g, '')  // 命令注入风险字符
    .trim();
}

function validateQuery(query) {
  if (!query || query.length === 0) {
    return { valid: false, error: '查询内容不能为空' };
  }
  if (query.length > 10000) {
    return { valid: false, error: '查询内容过长（最大10000字符）' };
  }
  return { valid: true };
}

// 获取查询
const rawQuery = process.argv.slice(2).join(' ');
const query = sanitizeInput(rawQuery);

if (!query) {
  console.error('Usage: node ensemble.mjs "你的问题"');
  process.exit(1);
}

const validation = validateQuery(query);
if (!validation.valid) {
  console.error(`❌ 输入验证失败: ${validation.error}`);
  process.exit(1);
}

log('⚖️ 启动 Ensemble Jury 盲审委员会...', 'cyan');
log(`📋 议题: ${query.substring(0, 100)}${query.length > 100 ? '...' : ''}\n`, 'cyan');

// Phase 1: 并行搜索
async function gatherIntelligence() {
  log('📡 Phase 1: 情报收集中...', 'yellow');
  
  const results = {
    perplexity: null,
    google: null
  };
  
  // Perplexity 搜索
  const pPromise = new Promise((resolve) => {
    const p = spawn('bash', [
      DEPS.perplexity,
      '-f', 'markdown',
      query
    ], { timeout: 30000 });
    
    let out = '';
    let errOut = '';
    p.stdout.on('data', (d) => out += d);
    p.stderr.on('data', (d) => {
      errOut += d;
    });
    p.on('close', (code) => {
      if (code !== 0 && errOut) {
        logError('Perplexity', errOut.substring(0, 500));
      }
      results.perplexity = code === 0 ? out : null;
      resolve();
    });
    p.on('error', (err) => {
      logError('Perplexity', err.message);
      results.perplexity = null;
      resolve();
    });
  });
  
  // Google 搜索
  const gPromise = new Promise((resolve) => {
    const p = spawn('node', [
      DEPS.google,
      query,
      '--limit', '5'
    ], { timeout: 30000 });
    
    let out = '';
    let errOut = '';
    p.stdout.on('data', (d) => out += d);
    p.stderr.on('data', (d) => {
      errOut += d;
    });
    p.on('close', (code) => {
      if (code !== 0 && errOut) {
        logError('Google', errOut.substring(0, 500));
      }
      results.google = code === 0 ? out : null;
      resolve();
    });
    p.on('error', (err) => {
      logError('Google', err.message);
      results.google = null;
      resolve();
    });
  });
  
  await Promise.all([pPromise, gPromise]);
  
  const hasResults = results.perplexity || results.google;
  if (!hasResults) {
    log('⚠️ 情报收集未返回结果，将仅依赖模型知识', 'yellow');
  } else {
    log('✅ 情报收集完成\n', 'green');
  }
  
  return results;
}

// Phase 2: 并行盲审（4个模型）
async function blindReview(query, intelligence) {
  log('🎭 Phase 2: 盲审评阅中（4位专家并行作答，Claude独立裁决）...', 'yellow');
  
  const reviewers = [
    { agent: 'kimi', name: 'Reviewer A' },
    { agent: 'gemini', name: 'Reviewer B' },
    { agent: 'deepseek', name: 'Reviewer C' },
    { agent: 'gpt-5.2', name: 'Reviewer D' }
  ];
  
  const intelligenceContext = intelligence.perplexity || intelligence.google
    ? `【参考资料】\n${intelligence.perplexity ? `Perplexity搜索结果:\n${intelligence.perplexity}\n` : ''}${intelligence.google ? `Google搜索结果:\n${intelligence.google}` : ''}\n\n【你的任务】\n基于以上参考资料和你的知识，回答以下问题。请给出结构化的详细回答。`
    : `【你的任务】\n基于你的知识，回答以下问题。请给出结构化的详细回答。`;
  
  const fullPrompt = `${intelligenceContext}\n\n【问题】\n${query}`;
  
  const reviews = await Promise.all(reviewers.map(async (reviewer) => {
    return new Promise((resolve) => {
      const startTime = Date.now();
      const p = spawn('openclaw', [
        'agent',
        '--agent', reviewer.agent,
        '-m', fullPrompt
      ], { timeout: 90000 });  // 增加到90秒
      
      let out = '';
      let errOut = '';
      p.stdout.on('data', (d) => out += d);
      p.stderr.on('data', (d) => {
        errOut += d;
      });
      p.on('close', (code) => {
        const duration = ((Date.now() - startTime) / 1000).toFixed(1);
        if (code !== 0) {
          logError(reviewer.agent, `Exit code ${code}, stderr: ${errOut.substring(0, 200)}`);
        }
        resolve({
          name: reviewer.name,
          agent: reviewer.agent,
          answer: code === 0 ? out.trim() : `[${reviewer.name} 未能完成评阅 (耗时${duration}s)]`,
          duration: duration
        });
      });
      p.on('error', (err) => {
        logError(reviewer.agent, err.message);
        resolve({
          name: reviewer.name,
          agent: reviewer.agent,
          answer: `[${reviewer.name} 连接失败: ${err.message}]`,
          duration: 0
        });
      });
    });
  }));
  
  // 统计成功/失败
  const successCount = reviews.filter(r => !r.answer.includes('未能完成') && !r.answer.includes('连接失败')).length;
  log(`✅ 盲审完成 (${successCount}/4 位专家成功返回)\n`, successCount >= 2 ? 'green' : 'yellow');
  
  return reviews;
}

// Phase 3: Claude 综合
async function synthesize(query, intelligence, reviews) {
  log('⚖️ Phase 3: 最终裁决中 (Claude Sonnet 4.6)...', 'magenta');
  
  // 匿名化：去掉模型名称，只保留 Reviewer X
  const anonymizedReviews = reviews.map(r => 
    `【${r.name}的观点】\n${r.answer}`
  ).join('\n\n---\n\n');
  
  // 构建参考资料摘要
  const perplexitySnippet = intelligence.perplexity 
    ? intelligence.perplexity.slice(0, 1500) + (intelligence.perplexity.length > 1500 ? '\n...(已截断)' : '')
    : '';
  const googleSnippet = intelligence.google 
    ? intelligence.google.slice(0, 1500) + (intelligence.google.length > 1500 ? '\n...(已截断)' : '')
    : '';
  
  const synthesisPrompt = `你是一位资深的综合分析专家和最终裁决者。请阅读以下四位匿名专家的评阅意见和参考资料，给出一个全面、客观、结构化的最终答案。

【原始问题】
${query}

【参考资料】
${perplexitySnippet ? 'Perplexity搜索结果:\n' + perplexitySnippet + '\n\n' : ''}${googleSnippet ? 'Google搜索结果:\n' + googleSnippet : ''}

【匿名专家评阅意见】
${anonymizedReviews}

【你的任务】
1. 作为独立裁决者，综合以上所有观点，给出结构化的最终答案
2. 如有观点冲突，请客观列出不同角度的考量
3. 不要提及任何模型名称或"Reviewer"字样
4. 回答要专业、全面、有深度，体现你作为最终裁决者的独立判断

请以清晰的结构输出最终答案。`;

  return new Promise((resolve) => {
    const p = spawn('openclaw', [
      'agent',
      '--agent', 'claude',
      '-m', synthesisPrompt
    ], { timeout: 180000 });  // 增加到180秒
    
    let out = '';
    let errOut = '';
    p.stdout.on('data', (d) => out += d);
    p.stderr.on('data', (d) => {
      errOut += d;
    });
    p.on('close', (code) => {
      if (code !== 0) {
        logError('Claude-Synthesis', `Exit code ${code}, stderr: ${errOut.substring(0, 500)}`);
      }
      resolve(code === 0 ? out.trim() : '⚠️ 综合裁决过程出现错误，请重试');
    });
    p.on('error', (err) => {
      logError('Claude-Synthesis', err.message);
      resolve('⚠️ 综合裁决连接失败: ' + err.message);
    });
  });
}

// 主流程
async function main() {
  const startTime = Date.now();
  
  try {
    // Phase 1
    const intelligence = await gatherIntelligence();
    
    // Phase 2
    const reviews = await blindReview(query, intelligence);
    
    // Phase 3
    const finalAnswer = await synthesize(query, intelligence, reviews);
    
    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    
    // 输出最终结果
    console.log('\n' + '='.repeat(60));
    log('⚖️ ENSEMBLE JURY - 盲审委员会综合裁决', 'cyan');
    console.log('='.repeat(60) + '\n');
    
    console.log(finalAnswer);
    
    console.log('\n' + '='.repeat(60));
    log(`⏱️ 总计用时: ${duration}s`, 'yellow');
    log('📊 参与评审: 4位专家盲审 (Kimi/Gemini/DeepSeek/GPT-5.2) + Claude独立裁决 + 2个情报来源', 'yellow');
    if (existsSync(ERROR_LOG)) {
      log(`📝 错误日志: ${ERROR_LOG}`, 'gray');
    }
    console.log('='.repeat(60));
    
  } catch (err) {
    log(`\n❌ 错误: ${err.message}`, 'red');
    logError('Main', err.stack || err.message);
    process.exit(1);
  }
}

main();
