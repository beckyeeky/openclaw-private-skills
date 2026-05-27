#!/usr/bin/env node
/**
 * 技能调用包装器
 * 当 AI 检测到技能触发词时，调用此脚本
 */

import { execSync } from 'child_process';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const skill = args[0];
const command = args[1] || 'start';

if (skill !== 'trivia-quiz') {
  console.log('只支持 trivia-quiz 技能');
  process.exit(1);
}

try {
  const output = execSync(
    `node "${join(__dirname, 'scripts/entry_final.mjs')}" ${command}`,
    { encoding: 'utf-8', cwd: __dirname }
  ).trim();
  
  // 直接输出原始 JSON，不做任何包装
  // Hermes skill 执行器会直接解析并提取 text/buttons 字段发送 Telegram
  console.log(output);
  
} catch (error) {
  console.log(JSON.stringify({
    error: error.message,
    skill: 'trivia-quiz',
    action: 'failed'
  }));
}
