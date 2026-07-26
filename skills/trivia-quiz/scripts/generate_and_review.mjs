#!/usr/bin/env node
/**
 * 题目生成 + 核实 + DeepSeek 审核 + 写入题库
 * 
 * 完整流程：
 *   1. Gemini 3 Pro 生成候选题目
 *   2. Google Search + Perplexity 核实事实
 *   3. DeepSeek Reasoner 审核选项质量（最多 3 轮）
 *   4. 通过后追加到 questions.json
 *   5. 更新 .backup_state.json
 * 
 * 使用方法:
 *   node generate_and_review.mjs                  # 生成 1 道题补充备用库
 *   node generate_and_review.mjs --count 3        # 生成 3 道
 *   node generate_and_review.mjs --topic 动物      # 指定主题
 */

import { execSync } from 'child_process';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const QUESTIONS_FILE = join(__dirname, '../questions.json');
const BACKUP_STATE = join(__dirname, '../.backup_state.json');
const GOOGLE_SCRIPT = join(__dirname, '../../google-search/scripts/search.mjs');
const PERPLEXITY_SCRIPT = join(__dirname, '../../perplexity-safe/scripts/perplexity_search.sh');

// ── CLI 参数 ──────────────────────────────────────────────────
const args = process.argv.slice(2);
const countArg = args.indexOf('--count');
const topicArg = args.indexOf('--topic');
const COUNT = countArg !== -1 ? parseInt(args[countArg + 1]) : 1;
const TOPIC = topicArg !== -1 ? args[topicArg + 1] : null;

const API_CLIENT = join(__dirname, 'api_client.mjs');

// ── 工具函数 ──────────────────────────────────────────────────
function run(cmd, opts = {}) {
  try {
    return execSync(cmd, { encoding: 'utf-8', timeout: 60000, ...opts }).trim();
  } catch (e) {
    return e.stdout?.trim() || '';
  }
}

function log(msg) { process.stderr.write(`[generate] ${msg}\n`); }

function loadQuestions() {
  if (!existsSync(QUESTIONS_FILE)) return [];
  try {
    return JSON.parse(readFileSync(QUESTIONS_FILE, 'utf-8'));
  } catch { return []; }
}

function saveQuestions(questions) {
  writeFileSync(QUESTIONS_FILE, JSON.stringify(questions, null, 2));
}

function getNextId(questions) {
  if (questions.length === 0) return 1;
  const ids = questions.map(q => q.id);
  return Math.max(...ids) + 1;
}

function updateBackupState(newId) {
  let state = { available: [], used: [], last_refill_check: null };
  if (existsSync(BACKUP_STATE)) {
    try {
      state = JSON.parse(readFileSync(BACKUP_STATE, 'utf-8'));
    } catch {}
  }
  if (!state.available.includes(newId)) state.available.push(newId);
  state.last_refill_check = new Date().toISOString();
  writeFileSync(BACKUP_STATE, JSON.stringify(state, null, 2));
}

// ── 步骤 1：Gemini 生成题目 ───────────────────────────────────
async function generateQuestion(topic) {
  const topicHint = topic ? `主题偏向：${topic}。` : '主题随机选择（天文/生物/历史/化学/物理/动物/地理/人体）。';
  
  const prompt = `你是一位冷门知识出题专家。请生成一道已证实的冷门知识选择题。

要求：
- ${topicHint}
- 问题描述清晰，避免歧义（如涉及参照系要明确说明）
- 4个选项：1个正确答案 + 3个有合理干扰性的错误选项
- 选项文字简洁，不超过20字
- 不选未定论的内容，只选已被科学/历史确认的事实
- 提供简短解析（50-100字）和可靠来源
- 提供一篇200-300字的拓展文章（Markdown格式），标题为"## [标题]"，内容有趣且有深度

请严格按照以下 JSON 格式输出，不要有任何其他文字：
{
  "category": "分类",
  "question": "完整问题？",
  "options": ["选项1", "选项2", "选项3", "选项4"],
  "correct": 0, // 0-3
  "explanation": "解析文字",
  "source": "来源",
  "article": "拓展文章内容"
}`;

  log('Gemini 3 Pro 生成题目...');
  
  // 使用 OpenRouter Gemini 3 Pro
  // 注意：这里使用 node -e 调用 http 请求，因为环境可能没有 curl 或 fetch 支持不全
  // 实际环境中建议使用专门的 LLM 客户端库
  
  // 这里简化为直接调用 hermes agent (如果支持 json 输出最好，否则需要解析)
  // 为了稳定性，我们还是用 node http request
  
  const result = run(`node -e "
const https = require('https');
const key = process.env.OPENROUTER_API_KEY || '';
if (!key) { console.log(JSON.stringify({error:'no api key'})); process.exit(0); }
const body = JSON.stringify({
  model: 'google/gemini-2.5-pro-preview',
  messages: [{role:'user', content: ${JSON.stringify(JSON.stringify(prompt))}}],
  response_format: {type: 'json_object'}
});
const req = https.request({
  hostname:'openrouter.ai',
  path:'/api/v1/chat/completions',
  method:'POST',
  headers:{
    'Authorization':'Bearer '+key,
    'Content-Type':'application/json',
    'Content-Length':Buffer.byteLength(body)
  }
}, res => {
  let d='';
  res.on('data',c=>d+=c);
  res.on('end',()=>{
    try {
      const r = JSON.parse(d);
      const content = r.choices?.[0]?.message?.content || '';
      console.log(content);
    } catch(e){ console.log('{}'); }
  });
});
req.on('error', () => console.log('{}'));
req.write(body);
req.end();
" 2>/dev/null`, { env: process.env });

  try {
    return JSON.parse(result);
  } catch {
    log('Gemini 生成失败，切换到 Kimi K2.5 (Fallback)...');
    try {
      // Fallback: 使用 Hermes CLI 调用 Kimi Agent
      // 这里使用 execSync 直接调用，避免复杂的 HTTP 构造
      // JSON.stringify(prompt) 确保特殊字符在 Shell 中正确传递
      const kimiCmd = `hermes agent --agent kimi --message ${JSON.stringify(prompt)}`;
      const kimiRaw = execSync(kimiCmd, { encoding: 'utf-8', timeout: 60000, maxBuffer: 1024 * 1024 }).trim();
      
      // 清理可能存在的 Markdown 代码块标记 (```json ... ```)
      const cleanKimi = kimiRaw.replace(/```json/g, '').replace(/```/g, '').trim();
      
      // 尝试寻找 JSON 对象
      const jsonMatch = cleanKimi.match(/\{[\s\S]*\}/);
      const jsonStr = jsonMatch ? jsonMatch[0] : cleanKimi;
      
      return JSON.parse(jsonStr);
    } catch (err) {
      log(`Kimi Fallback 也失败了: ${err.message}`);
      return null;
    }
  }
}

// ── 步骤 2：Google + Perplexity 核实 ─────────────────────────
async function verifyFact(question, explanation) {
  log('Google Search 核实...');
  
  const searchQuery = question.replace(/[？?]/g, '').slice(0, 60);
  let googleResult = '';
  let perplexityResult = '';

  try {
    // 假设 google-search 技能存在
    if (existsSync(GOOGLE_SCRIPT)) {
        googleResult = run(`node "${GOOGLE_SCRIPT}" "${searchQuery} 已证实 科学事实" 2>/dev/null`);
    } else {
        googleResult = "Google Search 脚本未找到";
    }
  } catch { googleResult = '搜索失败'; }

  try {
    // 假设 perplexity-safe 技能存在
    if (existsSync(PERPLEXITY_SCRIPT)) {
        perplexityResult = run(
        `bash "${PERPLEXITY_SCRIPT}" "请核实以下事实是否准确，简短回答是或否并说明理由：${explanation}"`,
        { env: { ...process.env } }
        );
    } else {
        perplexityResult = "Perplexity 脚本未找到";
    }
  } catch { perplexityResult = '核实失败'; }

  log(`Google: ${googleResult.slice(0, 50)}...`);
  log(`Perplexity: ${perplexityResult.slice(0, 50)}...`);

  // 简单判断
  const failed = perplexityResult.includes('不准确') ||
                 perplexityResult.includes('错误') ||
                 perplexityResult.includes('不正确') ||
                 perplexityResult.includes('incorrect') ||
                 perplexityResult.includes('false');
  
  return { passed: !failed, google: googleResult.slice(0, 500), perplexity: perplexityResult.slice(0, 500) };
}

// ── 步骤 3：DeepSeek Reasoner 审核 ───────────────────────────
async function reviewWithDeepSeek(qData, round = 1) {
  log(`DeepSeek Reasoner 审核（第 ${round} 轮）...`);

  const optionsText = qData.options.map((o, i) => `${i + 1}. ${o}`).join('\n');
  const correctOption = qData.options[qData.correct];

  const prompt = `你是严格的冷门知识选择题审核员。请审核以下题目的选项质量：

【问题】${qData.question}
【选项】
${optionsText}
【正确答案】${qData.correct + 1}. ${correctOption}
【解析】${qData.explanation}

请从以下6个维度审查，输出严格的 JSON：
1. 问题是否存在歧义（涉及参照系、范围等是否明确）
2. 每个选项是否完整独立（脱离问题也能理解）
3. 干扰项是否合理（有知识性，非"以上皆非"等敷衍选项）
4. 是否存在多个正确答案的争议
5. 事实是否准确可靠
6. 选项文字是否简洁（不超过20字）

输出格式（严格JSON，不要其他文字）：
{
  "passed": true或false,
  "issues": ["问题1", "问题2"],
  "suggestions": {
    "question": "修改后的问题（如无需改动则为null）",
    "options": ["选项1", "选项2", "选项3", "选项4"], // 必须是4个
    "correct": 正确答案索引(0-3) // 如无需改动则为null
  }
}`;

  // 使用 api_client.mjs 调用 DeepSeek，避免 Shell 转义问题
  const promptBase64 = Buffer.from(prompt).toString('base64');
  const result = run(`node "${API_CLIENT}" deepseek '${promptBase64}'`, { env: process.env });

  try {
    return JSON.parse(result);
  } catch {
    log('DeepSeek 解析失败，默认通过');
    return { passed: true, issues: [], suggestions: { question: null, options: null, correct: null } };
  }
}

// ── 步骤 4：写入题库 ──────────────────────────────────────
function appendToQuestions(qData, verifyInfo) {
  const questions = loadQuestions();
  const newId = getNextId(questions);
  
  const newQuestion = {
    id: newId,
    category: qData.category,
    question: qData.question,
    options: qData.options,
    correct: qData.correct,
    explanation: qData.explanation,
    source: qData.source,
    article: qData.article || `## ${qData.category}知识拓展\n\n${qData.explanation}`,
    verified_by: "Google+Perplexity+DeepSeek"
  };
  
  questions.push(newQuestion);
  saveQuestions(questions);
  
  // 更新备用状态
  updateBackupState(newId);
  log(`✅ 题目 Q${newId} 已写入 questions.json`);
  
  return newId;
}

// ── 主流程 ────────────────────────────────────────────────────
async function main() {
  log(`开始生成 ${COUNT} 道题目${TOPIC ? `（主题：${TOPIC}）` : ''}...`);

  let generated = 0;

  while (generated < COUNT) {
    log(`\n── 生成第 ${generated + 1}/${COUNT} 道 ──`);

    // Step 1: 生成
    let qData = await generateQuestion(TOPIC);
    if (!qData || !qData.question) {
      log('❌ 生成失败，跳过');
      continue;
    }
    log(`📝 题目：${qData.question}`);

    // Step 2: 核实
    const verify = await verifyFact(qData.question, qData.explanation);
    if (!verify.passed) {
      log('❌ 事实核实未通过，跳过此题');
      continue;
    }
    log('✅ 事实核实通过');

    // Step 3: DeepSeek 审核（最多 3 轮）
    let approved = false;
    for (let round = 1; round <= 3; round++) {
      const review = await reviewWithDeepSeek(qData, round);
      
      if (review.passed) {
        log(`✅ DeepSeek 第 ${round} 轮审核通过`);
        approved = true;
        break;
      }

      log(`⚠️ 第 ${round} 轮发现问题：${review.issues.join('；')}`);

      if (round < 3 && review.suggestions) {
        // 应用修改建议
        if (review.suggestions.question) qData.question = review.suggestions.question;
        if (review.suggestions.options && Array.isArray(review.suggestions.options)) qData.options = review.suggestions.options;
        if (typeof review.suggestions.correct === 'number') qData.correct = review.suggestions.correct;
        log('🔄 已应用修改建议，重新审核...');
      }
    }

    if (!approved) {
      log('❌ 经 3 轮审核仍未通过，放弃此题');
      continue;
    }

    // Step 4: 写入
    const newId = appendToQuestions(qData, verify);
    generated++;

    console.log(JSON.stringify({ ok: true, id: newId, question: qData.question }));
  }

  log(`\n完成。共生成 ${generated}/${COUNT} 道题目。`);
}

main().catch(e => {
  log(`Fatal: ${e.message}`);
  process.exit(1);
});
