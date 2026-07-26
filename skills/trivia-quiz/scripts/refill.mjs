#!/usr/bin/env node
/**
 * 备用题库守护脚本
 * 检查备用题库数量，不足 3 道时自动触发生成
 * 
 * 在 trivia.mjs start 时调用，或单独执行
 * 
 * 使用方法:
 *   node refill.mjs              # 检查并按需补充到 3 道
 *   node refill.mjs --check-only # 仅检查，不触发生成
 */

import { execSync } from 'child_process';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

function run(cmd) {
  try {
    return execSync(cmd, { encoding: 'utf-8', timeout: 120000 }).trim();
  } catch (e) {
    return e.stdout?.trim() || '';
  }
}

const checkOnly = process.argv.includes('--check-only');

// 检查备用题库状态
const statusRaw = run(`node "${join(__dirname, 'state.mjs')}" backup_status`);
let status;
try { status = JSON.parse(statusRaw); }
catch { status = { available: [], count: 0, needs_refill: true }; }

console.log(JSON.stringify({
  backup_count: status.count,
  needs_refill: status.needs_refill,
  available_ids: status.available
}));

if (!status.needs_refill) {
  process.stderr.write(`[refill] ✅ 备用题库充足（${status.count} 道），无需补充\n`);
  process.exit(0);
}

if (checkOnly) {
  process.stderr.write(`[refill] ⚠️ 备用题库不足（${status.count} 道），需要补充但 --check-only 模式跳过\n`);
  process.exit(0);
}

const needed = 10 - status.count;
process.stderr.write(`[refill] 🔄 备用题库仅剩 ${status.count} 道，开始生成 ${needed} 道...\n`);

const result = run(`node "${join(__dirname, 'generate_and_review.mjs')}" --count ${needed}`);
process.stderr.write(`[refill] 生成结果：${result}\n`);
