# Shell Quoting (Deprecated Positional Usage)

This only applies when using the **deprecated positional prompt** approach:

```bash
# BAD — if prompt contains curly quotes inside double quotes
python3 generate.py "prompt with \"curly\" quotes"

# FIXED — single quotes protect everything
python3 generate.py 'prompt with "curly" quotes'
```

**Recommended fix:** Use stdin JSON instead — no shell quoting issues at all:

```bash
echo '{"prompt": "带有\"弯引号\"的提示词"}' | python3 generate.py
```
