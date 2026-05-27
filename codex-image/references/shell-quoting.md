# Shell Quoting Issues with Chinese Punctuation

## The Problem

Chinese curly double quotes `"` (U+201C) and `"` (U+201D) inside double-quoted shell strings `"..."` break argument parsing.

**Symptoms:**
```
generate.py: error: unrecognized arguments: + 都市幻想系 boss 女角色 aesthetic。
站姿优雅，一手轻扶墙面...
```

The error shows the prompt argument was split at the curly quote boundary. The script's `argparse` receives multiple positional arguments instead of one.

## Root Cause

Bash implicitly treats `"` (U+201C, LEFT DOUBLE QUOTATION MARK) as an additional string delimiter in some contexts when used inside `"..."` (ASCII double-quote delimiters). The curly close-quote `"` (U+201D) terminates the outer string prematurely.

This only happens with **Chinese/Unicode curly quotes** inside **double-quote delimiters** on the shell command line — not inside the script itself.

## Fix

Use **single quotes** `'...'` as the outer shell delimiter whenever the prompt contains curly quotes:

```bash
# BROKEN — curly quotes inside double quotes
python3 generate.py "角色融合"性感女特工 + boss" aesthetic"

# FIXED — single quotes protect everything inside
python3 generate.py '角色融合"性感女特工 + boss" aesthetic'
```

Single quotes in bash prevent ALL interpretation of special characters. They handle curly quotes, exclamation marks, backticks, dollar signs, and any other punctuation without escaping.

## Quick Check

Before running, check the prompt for:
- `"` (left curly double quote, U+201C)
- `"` (right curly double quote, U+201D)

If either is present, use single-quote outer delimiter.

## When NOT to Use Single Quotes

If the prompt itself contains ASCII single quotes `'` (e.g. French contractions, quoted speech), you cannot use single-quote delimiters. In that case:
- Escape the ASCII single quote: `'\''` (close single quote, escaped quote, reopen)
- Or use a heredoc: `python3 generate.py <<'EOF'` ... `EOF`
- Or write prompt to file and pipe
