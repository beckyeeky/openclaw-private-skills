#!/usr/bin/env node
/**
 * 技能调用包装器
 * 当 AI 检测到技能触发词时，调用此脚本
 * 
 * 使用方法:
 *   node skill_wrapper.mjs trivia-quiz start
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
  
  const data = JSON.parse(output);
  
  // 输出给 AI 的格式
  console.log(JSON.stringify({
    skill: 'trivia-quiz',
    action: 'send_message',
    data: data
  }));
  
} catch (error) {
  console.log(JSON.stringify({
    error: error.message,
    skill: 'trivia-quiz',
    action: 'failed'
  }));
}
