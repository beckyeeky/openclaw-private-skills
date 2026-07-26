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
3.  **ALWAYS** call the provided tool script to get content.
4.  **DO NOT** just output the raw JSON text. Parse it and send a properly formatted reply with inline buttons.

## Workflow

### 1. Start Game
**Trigger**: User says "冷门知识", "trivia", "quiz"

**Action**: Run the skill script and parse its JSON output:
```bash
node {baseDir}/scripts/entry_final.mjs start
```

**AI Response**: Parse the returned JSON. Extract `message` and `buttons`. Send the `message` text together with the `buttons` as Telegram inline buttons. Do NOT add any greeting, commentary, or surrounding text.

### 2. Handle Answer (Callback)
**Trigger**: User clicks a callback button matching `trivia_q{id}_{0-3}`

**Action**: Extract `id` and `index` from the callback data. Example: `trivia_q21_0` → id=`21`, index=`0`:
```bash
node {baseDir}/scripts/entry_final.mjs answer 21 0
```

**AI Response**: Parse the JSON output. Extract `message` and `buttons`. Send the message text together with the buttons as Telegram inline buttons. No extra text.

### 3. Continue Game (Callback)
**Trigger**: User clicks `trivia_continue_{id}`

**Action**:
```bash
node {baseDir}/scripts/entry_final.mjs continue {id}
```

**AI Response**: Parse JSON, send message + inline buttons. No extra text.

### 4. View Article (Callback)
**Trigger**: User clicks `trivia_article_{id}`

**Action**:
```bash
node {baseDir}/scripts/entry_final.mjs article {id}
```

**AI Response**: Parse JSON, send message + inline buttons. No extra text.

### 5. End Game (Callback)
**Trigger**: User clicks `trivia_end`

**Action**:
```bash
node {baseDir}/scripts/entry_final.mjs end
```

**AI Response**: Parse JSON, send message + inline buttons. No extra text.

### 6. Restart (Callback)
**Trigger**: User clicks `trivia_restart`

**Action**: Treat as a new game → run `start` command above.

## Inline Button Formatting Rules

When the script returns `buttons` array like:
```json
{
  "buttons": [
    [{"text": "1️⃣", "callback_data": "trivia:q21:0"}, {"text": "2️⃣", "callback_data": "trivia:q21:1"}],
    [{"text": "3️⃣", "callback_data": "trivia:q21:2"}, {"text": "4️⃣", "callback_data": "trivia:q21:3"}]
  ]
}
```

Send each inner array as a **row** of Telegram inline buttons. Preserve the button labels and callback_data exactly as provided.

## Troubleshooting

- **If tool/script fails**: Report error to user, do NOT invent a question.
- **If user inputs text instead of clicking**: Politely ask them to click the buttons.
- **If callback is 'trivia_continue_undefined' or similar**: State lost. Ask user to start a new game with "冷门知识".

## Output Contract

Send ONLY the content from the script JSON. No greetings. No closing remarks. No conversational filler. The message from the script IS the reply.

If the channel does not support inline buttons, tell the user the environment lacks inline button support — do not silently drop the buttons.
