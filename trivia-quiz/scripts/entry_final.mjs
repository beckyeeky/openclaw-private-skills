#!/usr/bin/env node
/**
 * trivia-quiz 技能入口脚本（最终版）
 * 
 * 完整流程：
 * 1. start → 显示第一题（inline button）
 * 2. 用户点击答案 → answer → 显示结果 + 导航按钮
 * 3. 用户点击"继续" → continue → 显示下一题
 * 4. 循环直到所有题答完
 * 
 * 状态管理：state.mjs 记录已答题，避免重复
 */

import { execSync } from 'child_process';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

const args = process.argv.slice(2);
const command = args[0] || 'start';
const qid = args[1];
const userAnswer = args[2];

function run(cmd) {
  try {
    return execSync(cmd, { encoding: 'utf-8', cwd: __dirname }).trim();
  } catch (e) {
    return e.stdout?.trim() || '';
  }
}

function formatButtons(options) {
  const rows = [];
  for (let i = 0; i < options.length; i += 2) {
    rows.push(options.slice(i, i + 2));
  }
  return rows;
}

async function main() {
  switch (command) {
    case 'start': {
      // 清理旧状态，开始新游戏
      run('rm -f .game_state.json');
      
      const startResult = run('node trivia.mjs start');
      const startData = JSON.parse(startResult);
      
      // 初始化状态（state.mjs 会自己生成题目池）
      run(`node state.mjs init`);
      
      const firstId = startData.question_ids[0];
      const questionResult = run(`node trivia.mjs get_question ${firstId}`);
      const questionData = JSON.parse(questionResult);
      
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
      if (!qid || userAnswer === undefined) {
        console.log(JSON.stringify({ error: '缺少参数' }));
        break;
      }
      
      // 检查答案
      const checkResult = run(`node trivia.mjs check ${qid} ${userAnswer}`);
      const checkData = JSON.parse(checkResult);
      
      // 记录结果
      run(`node state.mjs record ${qid} ${checkData.correct ? 'correct' : 'wrong'}`);
      
      // 获取游戏状态
      const stateResult = run('node state.mjs summary');
      const stateData = JSON.parse(stateResult);
      
      // 获取下一题（state.mjs 会自己处理题目池）
      const nextResult = run(`node state.mjs next`);
      const nextData = JSON.parse(nextResult);
      
      const hasNext = !nextData.done && nextData.next_id;
      
      let message, buttons;
      
      if (hasNext) {
        message = `${checkData.message}\n\n---\n\n🎮 已答 ${stateData.total} 题（对 ${stateData.score.correct}/错 ${stateData.score.wrong}）\n\n接下来？`;
        buttons = [
          [{ text: '➡️ 继续答题', callback_data: `trivia_continue_${nextData.next_id}` }],
          [{ text: '📖 查看本题文章', callback_data: `trivia_article_${qid}` }],
          [{ text: '🏁 结束游戏', callback_data: 'trivia_end' }]
        ];
      } else {
        message = `${checkData.message}\n\n${stateData.message}`;
        buttons = [
          [{ text: '📖 查看本题文章', callback_data: `trivia_article_${qid}` }],
          [{ text: '🔄 重新开始', callback_data: 'trivia_restart' }]
        ];
      }
      
      console.log(JSON.stringify({
        message,
        buttons,
        metadata: {
          action: 'show_result',
          question_id: qid,
          correct: checkData.correct,
          has_next: hasNext,
          next_question_id: nextData.next_id,
          score: stateData.score
        }
      }));
      break;
    }
    
    case 'continue': {
      if (!qid) {
        console.log(JSON.stringify({ error: '缺少参数' }));
        break;
      }
      
      const questionResult = run(`node trivia.mjs get_question ${qid}`);
      const questionData = JSON.parse(questionResult);
      
      console.log(JSON.stringify({
        message: questionData.text,
        buttons: formatButtons(questionData.options),
        metadata: {
          action: 'show_question',
          question_id: qid
        }
      }));
      break;
    }
    
    case 'article': {
      if (!qid) {
        console.log(JSON.stringify({ error: '缺少参数' }));
        break;
      }
      
      const articleResult = run(`node trivia.mjs get_article ${qid}`);
      const articleData = JSON.parse(articleResult);
      
      console.log(JSON.stringify({
        message: `📚 ${articleData.title}\n\n${articleData.article}`,
        buttons: [[{ text: '🔄 重新开始', callback_data: 'trivia_restart' }]]
      }));
      break;
    }
    
    case 'end': {
      const stateResult = run('node state.mjs summary');
      const stateData = JSON.parse(stateResult);
      
      console.log(JSON.stringify({
        message: `🏁 游戏结束！\n\n${stateData.message}`,
        buttons: [[{ text: '🔄 重新开始', callback_data: 'trivia_restart' }]]
      }));
      break;
    }
    
    default:
      console.log(JSON.stringify({ error: '未知命令' }));
  }
}

main().catch(e => {
  console.log(JSON.stringify({ error: e.message }));
});
