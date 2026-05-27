#!/usr/bin/env node
/**
 * trivia-quiz 技能入口脚本（安全修复版）
 * 
 * 修复内容：
 * 1. 使用 spawn 替代 execSync，避免命令注入
 * 2. 添加输入验证和清理
 * 3. 添加 JSON 解析错误处理
 * 4. 检查依赖文件存在性
 * 
 * 完整流程：
 * 1. start → 显示第一题（inline button）
 * 2. 用户点击答案 → answer → 显示结果 + 导航按钮
 * 3. 用户点击"继续" → continue → 显示下一题
 * 4. 循环直到所有题答完
 */

import { spawn } from 'child_process';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { existsSync } from 'fs';

const __dirname = dirname(fileURLToPath(import.meta.url));

const args = process.argv.slice(2);
const command = args[0] || 'start';
const qid = args[1];
const userAnswer = args[2];

// 依赖文件检查
const DEPS = {
  trivia: join(__dirname, 'trivia.mjs'),
  state: join(__dirname, 'state.mjs')
};

function checkDeps() {
  for (const [name, path] of Object.entries(DEPS)) {
    if (!existsSync(path)) {
      throw new Error(`依赖文件缺失: ${name} (${path})`);
    }
  }
}

// 输入验证和清理
function sanitizeId(input) {
  if (!input) return null;
  // 只允许数字、字母、下划线、连字符
  const cleaned = String(input).replace(/[^a-zA-Z0-9_-]/g, '');
  if (cleaned.length > 50) return null;
  return cleaned;
}

function sanitizeAnswer(input) {
  if (input === undefined || input === null) return null;
  const normalized = String(input).trim();
  if (!/^\d+$/.test(normalized)) return null;
  const num = parseInt(normalized, 10);
  if (isNaN(num) || num < 0 || num > 3) return null;
  return num;
}

// 使用 spawn 替代 execSync，避免命令注入
function run(script, args = []) {
  return new Promise((resolve, reject) => {
    const cmd = process.execPath; // node
    const child = spawn(cmd, [script, ...args], {
      cwd: __dirname,
      encoding: 'utf-8',
      timeout: 30000
    });
    
    let stdout = '';
    let stderr = '';
    
    child.stdout.on('data', (data) => {
      stdout += data;
    });
    
    child.stderr.on('data', (data) => {
      stderr += data;
    });
    
    child.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`Process exited with code ${code}: ${stderr}`));
      } else {
        resolve(stdout.trim());
      }
    });
    
    child.on('error', (err) => {
      reject(err);
    });
  });
}

// 安全的 JSON 解析
function safeJsonParse(str, context = 'unknown') {
  try {
    return JSON.parse(str);
  } catch (e) {
    throw new Error(`JSON 解析失败 (${context}): ${e.message}`);
  }
}

function formatButtons(options) {
  return [options];
}

async function getCurrentState() {
  const currentResult = await run(DEPS.state, ['current']).catch(() => '{}');
  return safeJsonParse(currentResult, 'current');
}

function isQuestionPending(stateData, questionId) {
  if (!stateData || stateData.error) return false;
  const qid = Number(questionId);
  return Array.isArray(stateData.remaining_ids) && stateData.remaining_ids.includes(qid);
}

async function main() {
  // 检查依赖
  checkDeps();
  
  switch (command) {
    case 'start': {
      const startResult = await run(DEPS.trivia, ['start']);
      const startData = safeJsonParse(startResult, 'start');
      
      const firstId = startData.question_ids?.[0];
      if (!firstId) {
        throw new Error('无法获取第一题');
      }
      
      const questionResult = await run(DEPS.trivia, ['get_question', firstId]);
      const questionData = safeJsonParse(questionResult, 'get_question');
      
      console.log(JSON.stringify({
        message: questionData.text,
        buttons: formatButtons(questionData.options),
        metadata: {
          action: 'show_question',
          question_id: firstId,
          question_ids: startData.question_ids
        }
      }));
      break;
    }
    
    case 'answer': {
      const cleanQid = sanitizeId(qid);
      const cleanAnswer = sanitizeAnswer(userAnswer);
      
      if (!cleanQid || cleanAnswer === null) {
        console.log(JSON.stringify({ 
          error: '参数无效',
          details: { qid: cleanQid, answer: cleanAnswer }
        }));
        break;
      }

      const currentState = await getCurrentState();
      if (!isQuestionPending(currentState, cleanQid)) {
        console.log(JSON.stringify({
          error: '题目不在当前游戏中，或已作答',
          buttons: [[{ text: '🔄 重新开始', callback_data: 'trivia:restart' }]],
          metadata: { action: 'invalid_question', question_id: cleanQid }
        }));
        break;
      }
      
      // 检查答案
      const checkResult = await run(DEPS.trivia, ['check', cleanQid, String(cleanAnswer)]);
      const checkData = safeJsonParse(checkResult, 'check');
      
      // 记录结果
      await run(DEPS.state, ['record', cleanQid, checkData.correct ? 'correct' : 'wrong']).catch(() => {});
      
      // 获取游戏状态
      const stateResult = await run(DEPS.state, ['summary']).catch(() => '{}');
      const stateData = safeJsonParse(stateResult, 'summary');
      
      // 获取下一题
      const nextResult = await run(DEPS.state, ['next']).catch(() => '{}');
      const nextData = safeJsonParse(nextResult, 'next');
      
      const hasNext = !nextData.done && nextData.next_id;
      
      let message, buttons;
      
      if (hasNext) {
        message = `${checkData.message}\n\n---\n\n🎮 已答 ${stateData.total || 0} 题（对 ${stateData.score?.correct || 0}/错 ${stateData.score?.wrong || 0}）\n\n接下来？`;
        buttons = [
          [{ text: '➡️ 继续答题', callback_data: `trivia:continue:${nextData.next_id}` }],
          [{ text: '📖 查看本题文章', callback_data: `trivia:article:${cleanQid}` }],
          [{ text: '🏁 结束游戏', callback_data: 'trivia:end' }]
        ];
      } else {
        message = `${checkData.message}\n\n${stateData.message || '🎉 游戏结束！'}`;
        buttons = [
          [{ text: '📖 查看本题文章', callback_data: `trivia:article:${cleanQid}` }],
          [{ text: '🔄 重新开始', callback_data: 'trivia:restart' }]
        ];
      }
      
      console.log(JSON.stringify({
        message,
        buttons,
        metadata: {
          action: 'show_result',
          question_id: cleanQid,
          correct: checkData.correct,
          has_next: Boolean(hasNext),
          next_question_id: nextData.next_id,
          score: stateData.score
        }
      }));
      break;
    }
    
    case 'continue': {
      const cleanQid = sanitizeId(qid);
      
      if (!cleanQid) {
        console.log(JSON.stringify({ error: '无效的题目ID' }));
        break;
      }

      const currentState = await getCurrentState();
      if (!isQuestionPending(currentState, cleanQid)) {
        console.log(JSON.stringify({
          error: '下一题状态已失效，请重新开始',
          buttons: [[{ text: '🔄 重新开始', callback_data: 'trivia:restart' }]],
          metadata: { action: 'stale_continue', question_id: cleanQid }
        }));
        break;
      }
      
      const questionResult = await run(DEPS.trivia, ['get_question', cleanQid]);
      const questionData = safeJsonParse(questionResult, 'get_question');
      
      console.log(JSON.stringify({
        message: questionData.text,
        buttons: formatButtons(questionData.options),
        metadata: {
          action: 'show_question',
          question_id: cleanQid
        }
      }));
      break;
    }
    
    case 'article': {
      const cleanQid = sanitizeId(qid);
      
      if (!cleanQid) {
        console.log(JSON.stringify({ error: '无效的题目ID' }));
        break;
      }
      
      const articleResult = await run(DEPS.trivia, ['get_article', cleanQid]);
      const articleData = safeJsonParse(articleResult, 'get_article');
      
      console.log(JSON.stringify({
        message: `📚 ${articleData.title || '文章'}\n\n${articleData.article || '暂无内容'}`,
        buttons: [[{ text: '🔄 重新开始', callback_data: 'trivia:restart' }]]
      }));
      break;
    }
    
    case 'end': {
      const stateResult = await run(DEPS.state, ['summary']).catch(() => '{}');
      const stateData = safeJsonParse(stateResult, 'summary');
      
      console.log(JSON.stringify({
        message: `🏁 游戏结束！\n\n${stateData.message || `共答 ${stateData.total || 0} 题`}`,
        buttons: [[{ text: '🔄 重新开始', callback_data: 'trivia:restart' }]]
      }));
      break;
    }
    
    default:
      console.log(JSON.stringify({ error: '未知命令', available: ['start', 'answer', 'continue', 'article', 'end'] }));
  }
}

main().catch(e => {
  console.error(JSON.stringify({ error: e.message, stack: e.stack }));
  process.exit(1);
});
