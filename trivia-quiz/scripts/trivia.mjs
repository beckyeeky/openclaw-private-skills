#!/usr/bin/env node
/**
 * Trivia Quiz Manager
 * 管理冷门知识选择题游戏的状态和交互
 * 
 * 使用方法:
 *   node trivia.mjs start                    # 开始新游戏（含状态初始化+备用库检查）
 *   node trivia.mjs get_question <id>        # 获取题目
 *   node trivia.mjs check <id> <answer>      # 检查答案 (0-3)
 *   node trivia.mjs get_article <id>         # 获取拓展文章
 *   node trivia.mjs list                     # 列出所有题目
 *   node trivia.mjs list_ids                 # 列出所有题目 ID（供 state.mjs 调用）
 *   node trivia.mjs summary                  # 本局成绩总结
 */

import { readFileSync, existsSync } from 'fs';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// 加载题库
function loadQuestions() {
  const jsonPath = join(__dirname, '../questions.json');
  if (!existsSync(jsonPath)) {
    throw new Error('题库文件 questions.json 不存在');
  }
  
  try {
    const content = readFileSync(jsonPath, 'utf-8');
    return JSON.parse(content);
  } catch (err) {
    throw new Error(`题库解析失败: ${err.message}`);
  }
}

// 获取格式化的问题
function normalizeOptionText(option, index) {
  const emojiPrefix = ['1️⃣', '2️⃣', '3️⃣', '4️⃣'][index];
  const cleanText = String(option)
    .replace(/^[1-4]️⃣\s*/, '')
    .replace(/^\d[.)、]\s*/, '')
    .trim();
  return `${emojiPrefix} ${cleanText}`;
}

function formatQuestion(question) {
  const normalizedOptions = question.options.map(normalizeOptionText);
  const optionsText = normalizedOptions.join('\n');

  return {
    text: `🎯 ${question.category}类\n\n${question.question}\n\n${optionsText}`,
    options: normalizedOptions.map((label, i) => ({
      text: ['1️⃣', '2️⃣', '3️⃣', '4️⃣'][i],
      callback_data: `trivia_q${question.id}_${i}`
    })),
    correct: question.correct
  };
}

// 主函数
function main() {
  const args = process.argv.slice(2);
  const command = args[0];
  
  try {
    const questions = loadQuestions();
    
    switch (command) {
      case 'start': {
        // 初始化游戏状态并返回本局题目池
        const initRaw = execSync(`node "${join(__dirname, 'state.mjs')}" init`, { encoding: 'utf-8' }).trim();
        const initData = JSON.parse(initRaw);

        // 后台检查备用题库（不阻塞游戏启动）
        try {
          execSync(`node "${join(__dirname, 'refill.mjs')}" --check-only`, { encoding: 'utf-8', timeout: 5000 });
        } catch { /* 检查失败不阻断 */ }

        const selectedIds = initData.question_pool || [];
        console.log(JSON.stringify({
          total: selectedIds.length,
          question_ids: selectedIds,
          message: `🎮 冷门知识挑战开始！\n\n共 ${selectedIds.length} 道题，准备好挑战你的知识边界了吗？`
        }));
        break;
      }

      case 'summary': {
        const summaryRaw = execSync(
          `node "${join(__dirname, 'state.mjs')}" summary`,
          { encoding: 'utf-8' }
        ).trim();
        console.log(summaryRaw);
        break;
      }
      
      case 'list_ids': {
        const ids = questions.map(q => q.id);
        console.log(JSON.stringify(ids));
        break;
      }
        
      case 'get_question': {
        const id = parseInt(args[1]);
        const q = questions.find(q => q.id === id);
        if (!q) {
          console.error(JSON.stringify({ error: '题目不存在' }));
          process.exit(1);
        }
        console.log(JSON.stringify(formatQuestion(q)));
        break;
      }
        
      case 'check': {
        const id = parseInt(args[1]);
        const answer = parseInt(args[2], 10); // 用户选择的索引
        const q = questions.find(q => q.id === id);
        if (!q) {
          console.error(JSON.stringify({ error: '题目不存在' }));
          process.exit(1);
        }
        const isCorrect = answer === q.correct;

        // 记录答题结果到状态文件
        try {
          execSync(
            `node "${join(__dirname, 'state.mjs')}" record ${id} ${isCorrect ? 'correct' : 'wrong'}`,
            { encoding: 'utf-8' }
          );
        } catch { /* 状态记录失败不影响游戏 */ }

        console.log(JSON.stringify({
          correct: isCorrect,
          correct_answer: q.correct,
          selected_answer: answer,
          explanation: q.explanation,
          source: q.source,
          message: isCorrect 
            ? `✅ 回答正确！\n\n${q.explanation}\n\n📚 来源：${q.source}`
            : `❌ 回答错误！\n\n正确答案是：${['1️⃣', '2️⃣', '3️⃣', '4️⃣'][q.correct]}\n\n${q.explanation}\n\n📚 来源：${q.source}`
        }));
        break;
      }
        
      case 'get_article': {
        const id = parseInt(args[1]);
        const q = questions.find(q => q.id === id);
        if (!q) {
          console.error(JSON.stringify({ error: '题目不存在' }));
          process.exit(1);
        }
        console.log(JSON.stringify({
          title: `${q.category}知识拓展`,
          article: q.article || '暂无拓展文章'
        }));
        break;
      }
        
      case 'list': {
        console.log(JSON.stringify({
          total: questions.length,
          categories: [...new Set(questions.map(q => q.category))],
          questions: questions.map(q => ({
            id: q.id,
            category: q.category,
            question: q.question
          }))
        }));
        break;
      }
        
      default:
        console.log(`
使用方法:
  node trivia.mjs start                    # 开始新游戏
  node trivia.mjs list_ids                 # 列出所有ID
  node trivia.mjs get_question <id>        # 获取题目
  node trivia.mjs check <id> <answer>      # 检查答案 (0-3)
  node trivia.mjs get_article <id>         # 获取拓展文章
  node trivia.mjs list                     # 列出所有题目
        `.trim());
    }
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  }
}

main();
