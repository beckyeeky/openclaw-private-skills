# Trivia Quiz

> 冷门知识选择题游戏 - Fun trivia game with inline buttons and detailed explanations

[![OpenClaw](https://img.shields.io/badge/OpenClaw-Skill-blue)](https://openclaw.ai)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 🎯 Overview

Trivia Quiz is an OpenClaw skill that provides a fun trivia game experience with multiple-choice questions. It features inline buttons for answering, detailed explanations after each question, and articles for further learning.

### Key Features

- **🎮 Interactive Gameplay**: Inline buttons for selecting answers
- **📚 Educational**: Detailed explanations and articles for each question
- **📊 Progress Tracking**: Tracks correct/wrong answers during session
- **🔄 Continuous Play**: Option to continue with next question or view article

## 🚀 Quick Start

### Activation Keywords

Simply say one of these to start the game:
- "冷门知识"
- "trivia"
- "知识问答"
- "quiz"

### Commands

```bash
# Start new game
node scripts/entry_final.mjs start

# Answer a question
node scripts/entry_final.mjs answer <qid> <answer_index>

# Continue to next question
node scripts/entry_final.mjs continue <qid>

# View article for a question
node scripts/entry_final.mjs article <qid>

# End game and show summary
node scripts/entry_final.mjs end
```

## 📋 Requirements

- **Node.js**: Runtime environment
- **OpenClaw**: Must be installed and configured
- **Dependencies**: `trivia.mjs`, `state.mjs` (included)

## 🎮 Game Flow

```
User: "冷门知识"
  ↓
AI: Shows Question 1 with 4 options (inline buttons)
  ↓
User: Clicks an answer
  ↓
AI: Shows result (correct/wrong) + explanation + navigation buttons
  ↓
User: Chooses to continue or view article
  ↓
[Continue] → Next question
[Article]  → Detailed article about the topic
[End]      → Game summary
```

## 📚 Question Format

Each question includes:
- **Question text**: The trivia question
- **4 options**: Multiple choice answers
- **Correct answer**: Stored separately
- **Explanation**: Brief explanation of the correct answer
- **Article**: Detailed article for further reading

## 🔄 Callback Data Format

- `trivia_q{id}_{idx}` - Answer selection
- `trivia_continue_{id}` - Continue to next question
- `trivia_article_{id}` - View article
- `trivia_restart` - Restart game
- `trivia_end` - End game

## 📁 File Structure

```
trivia-quiz/
├── SKILL.md              # Skill definition
├── scripts/
│   ├── entry_final.mjs   # Main entry point
│   ├── trivia.mjs        # Question database
│   └── state.mjs         # Game state management
└── .game_state.json      # Session state (auto-generated)
```

## 🎯 Activation

The skill activates when user says:
- "冷门知识"
- " trivia"
- "知识问答"
- "quiz"

## ⚠️ Important Note for AI

**AI should NEVER generate quiz questions itself.**

Always call the provided tool script to get content:
```bash
node skill_wrapper.mjs trivia-quiz start
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built for [OpenClaw](https://openclaw.ai)
- Questions curated for educational and entertainment purposes
