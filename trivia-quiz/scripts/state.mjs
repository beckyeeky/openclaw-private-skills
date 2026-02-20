#!/usr/bin/env node
/**
 * 游戏状态管理器
 * 持久化追踪：已答题目、答对/错记录、备用题库状态
 * 
 * 使用方法:
 *   node state.mjs init                        # 初始化新游戏
 *   node state.mjs record <qid> <correct|wrong> # 记录答题结果
 *   node state.mjs next <pool_ids...>           # 获取下一题（排除已答）
 *   node state.mjs summary                      # 本局统计
 *   node state.mjs backup_status               # 查看备用题库状态
 *   node state.mjs backup_used <qid>           # 标记备用题已使用
 */

import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const STATE_FILE = join(__dirname, '../.game_state.json');
const BACKUP_STATE_FILE = join(__dirname, '../.backup_state.json');

function loadState() {
  if (!existsSync(STATE_FILE)) return null;
  return JSON.parse(readFileSync(STATE_FILE, 'utf-8'));
}

function saveState(state) {
  writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

function loadBackupState() {
  if (!existsSync(BACKUP_STATE_FILE)) {
    return { available: [11, 12, 13], used: [], last_refill_check: null };
  }
  return JSON.parse(readFileSync(BACKUP_STATE_FILE, 'utf-8'));
}

function saveBackupState(state) {
  writeFileSync(BACKUP_STATE_FILE, JSON.stringify(state, null, 2));
}

const args = process.argv.slice(2);
const cmd = args[0];

switch (cmd) {
  case 'init': {
    const explicitIds = args.slice(1).map(Number).filter(id => id > 0);
    
    let finalQuestionPool = explicitIds;
    if (finalQuestionPool.length === 0) {
      try {
        // 动态获取全量题目 ID
        const listOutput = execSync(`node "${join(__dirname, 'trivia.mjs')}" list_ids`, { encoding: 'utf-8' }).trim();
        const allIds = JSON.parse(listOutput);
        
        // 随机选5道
        finalQuestionPool = [...allIds]
          .sort(() => 0.5 - Math.random())
          .slice(0, 5);
          
      } catch (err) {
        console.error(`无法获取题目列表: ${err.message}`);
        // 降级策略：假设至少有 1-5
        finalQuestionPool = [1, 2, 3, 4, 5];
      }
    }
    
    const state = {
      session_id: Date.now(),
      started_at: new Date().toISOString(),
      answered: [],      // [{qid, correct, timestamp}]
      score: { correct: 0, wrong: 0 },
      question_pool: finalQuestionPool
    };
    saveState(state);
    console.log(JSON.stringify({ 
      ok: true, 
      session_id: state.session_id, 
      question_pool: state.question_pool 
    }));
    break;
  }

  case 'record': {
    const state = loadState();
    if (!state) { console.error(JSON.stringify({ error: 'no active game' })); process.exit(1); }
    const qid = parseInt(args[1]);
    const result = args[2]; // 'correct' or 'wrong'
    
    // 检查是否已经记录过这道题
    const alreadyRecorded = state.answered.some(a => a.qid === qid);
    if (!alreadyRecorded) {
      state.answered.push({ qid, correct: result === 'correct', timestamp: new Date().toISOString() });
      if (result === 'correct') state.score.correct++;
      else state.score.wrong++;
      saveState(state);
    }
    
    console.log(JSON.stringify({ ok: true, score: state.score, already_recorded: alreadyRecorded }));
    break;
  }

  case 'next': {
    const state = loadState();
    if (!state) { console.log(JSON.stringify({ done: true, message: '没有活跃游戏' })); break; }
    
    const answered_ids = state.answered.map(a => a.qid);
    
    // 使用保存的题目池，而不是传入的参数
    const pool = (state.question_pool || []).filter(id => !answered_ids.includes(id));
    
    if (pool.length === 0) {
      // 池子空了，检查是否需要从备用题库补充
      const backupState = loadBackupState();
      if (backupState.available.length > 0) {
        // 从备用题库取一道题加入池子
        const newId = backupState.available[0];
        state.question_pool.push(newId);
        saveState(state);
        
        // 标记备用题已使用
        backupState.available.shift();
        backupState.used.push(newId);
        saveBackupState(backupState);
        
        console.log(JSON.stringify({ 
          done: false, 
          next_id: newId, 
          remaining: 1,
          from_backup: true 
        }));
      } else {
        console.log(JSON.stringify({ 
          done: true, 
          message: '所有题目已完成，备用题库也空了' 
        }));
      }
    } else {
      const next_id = pool[Math.floor(Math.random() * pool.length)];
      console.log(JSON.stringify({ 
        done: false, 
        next_id, 
        remaining: pool.length,
        from_backup: false 
      }));
    }
    break;
  }

  case 'summary': {
    const state = loadState();
    if (!state) { console.log(JSON.stringify({ error: 'no active game' })); break; }
    const total = state.score.correct + state.score.wrong;
    const pct = total > 0 ? Math.round(state.score.correct / total * 100) : 0;
    console.log(JSON.stringify({
      score: state.score,
      total,
      accuracy: `${pct}%`,
      answered_ids: state.answered.map(a => a.qid),
      question_pool: state.question_pool || [],
      message: `🏁 本局结束！答对 ${state.score.correct}/${total} 题（正确率 ${pct}%）`
    }));
    break;
  }

  case 'backup_status': {
    const bs = loadBackupState();
    const needs_refill = bs.available.length < 10;
    console.log(JSON.stringify({
      available: bs.available,
      used: bs.used,
      count: bs.available.length,
      needs_refill,
      message: needs_refill
        ? `⚠️ 备用题库仅剩 ${bs.available.length} 道，需要补充`
        : `✅ 备用题库充足（${bs.available.length} 道待用）`
    }));
    break;
  }

  case 'backup_used': {
    const qid = parseInt(args[1]);
    const bs = loadBackupState();
    bs.available = bs.available.filter(id => id !== qid);
    bs.used.push(qid);
    saveBackupState(bs);
    const needs_refill = bs.available.length < 10;
    console.log(JSON.stringify({ ok: true, remaining: bs.available.length, needs_refill }));
    break;
  }

  case 'backup_add': {
    const qid = parseInt(args[1]);
    const bs = loadBackupState();
    if (!bs.available.includes(qid)) bs.available.push(qid);
    bs.last_refill_check = new Date().toISOString();
    saveBackupState(bs);
    console.log(JSON.stringify({ ok: true, available: bs.available }));
    break;
  }

  default:
    console.log('使用方法: node state.mjs <init|record|next|summary|backup_status|backup_used|backup_add>');
}
