# Telegram Reference Images

When a user sends a photo as reference, pass it **explicitly** — no auto-discovery from global cache.

## In Agent Response

When the user sends a photo and says "use this as reference for X", the image is available at a known path in the conversation context. Pass it directly:

```bash
echo '{"prompt": "make it look like this reference", "reference": "/path/to/user_image.jpg"}' \
  | python3 /root/.hermes/skills/codex-image/scripts/generate.py
```

## Codex API Content Construction

When passing a reference, the `content` field becomes a list (text + image):

```python
content = [
    {"type": "input_text", "text": prompt},
    {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}
]
```
