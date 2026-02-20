---
name: trivia-quiz
description: 冷门知识选择题游戏。激活词："冷门知识"、" trivia"、"知识问答"、"quiz"。当用户想要玩知识问答游戏、测试冷门知识、或进行趣味学习时使用。使用 inline button 呈现选项，回答后提供详细解释和拓展文章。
metadata: {"clawdbot":{"emoji":"🎯","requires":{"bins":["node"]},"command":"node {baseDir}/scripts/entry_final.mjs start"}}
---

# Trivia Quiz Skill

> 冷门知识选择题游戏系统

## 🚨 CRITICAL INSTRUCTION FOR AI

**YOU ARE THE INTERFACE, NOT THE CONTENT GENERATOR.**

1.  **NEVER** generate quiz questions yourself.
2.  **NEVER** answer in English unless the tool output is in English.
3.  **ALWAYS** call the provided tool script (`skill_wrapper.mjs`) to get content.
4.  **STRICTLY** output the JSON content provided by the tool using the `message` tool. Do not add conversational filler.

## Usage

### 1. Start Game
**Trigger**: User says "冷门知识", "trivia", "quiz"
**Action**:
```bash
node skill_wrapper.mjs trivia-quiz start
```

### 2. Handle Answer (Callback)
**Trigger**: Callback data `trivia_q{id}_{correct|wrong_idx}`
**Action**:
```bash
# Example: User clicked answer index 2 for question 10
node scripts/entry_final.mjs answer 10 2
```

### 3. Continue Game (Callback)
**Trigger**: Callback data matching regex `^trivia_continue_(\d+)$`
**Action**:
1. Extract the ID from the callback (e.g., `trivia_continue_10` -> `10`).
2. Run the command:
```bash
node scripts/entry_final.mjs continue 10
```
(Replace `10` with the actual ID extracted)

## Workflow

1.  **User**: "冷门知识"
2.  **AI**: Calls `node skill_wrapper.mjs trivia-quiz start`
3.  **Tool**: Returns JSON `{ "skill": "trivia-quiz", "action": "send_message", "data": { ... } }`
4.  **AI**: Calls `message` tool with `message` and `buttons` from `data`.

## Troubleshooting

- **If tool fails**: Report error to user, do NOT invent a question.
- **If user inputs text (1-4)**: Politely ask them to click the buttons.
- **If callback is 'trivia_continue_undefined'**: The state might be lost. Ask user to start a new game with "冷门知识".
