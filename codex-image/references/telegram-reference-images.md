# Using Telegram User-Submitted Photos as Reference Images

When a user sends a photo in Telegram as a reference for image generation, the gateway downloads and caches it. Here's how to find and use it.

## Finding the cached photo

Telegram caches user-submitted photos in:

```
/root/.hermes/image_cache/img_*.jpg
```

Find the most recent one:

```python
import pathlib
cached = sorted(pathlib.Path("/root/.hermes/image_cache").iterdir(), key=lambda p: p.stat().st_mtime)
latest = cached[-1]  # most recent
```

## Reading & passing as reference

**generate.py now supports `--reference` CLI arg (v1.9+).** No need for custom scripts:

```bash
ref=$(ls -t /root/.hermes/image_cache/img_*.jpg 2>/dev/null | head -1)
python3 /root/.hermes/skills/image-generation/codex-image/scripts/generate.py "use this reference style" --reference "$ref"
```

Then include `MEDIA:/path` in the agent response (from the `OUTPUT_PATH=` line).

MIME type is auto-detected from file extension. Override with `--mime` if needed.

### If you still need to call the Python function directly

```python
import base64, pathlib

# 1. Find cached photo
cache_dir = pathlib.Path("/root/.hermes/image_cache")
cached = sorted(cache_dir.iterdir(), key=lambda p: p.stat().st_mtime)
ref_path = cached[-1]

# 2. Determine MIME type
ext = ref_path.suffix.lower()
mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")

# 3. Read as base64
ref_b64 = base64.b64encode(ref_path.read_bytes()).decode()

# 4. Pass to call_codex_image
# Note: call_codex_image is now importable (if __name__ guard added)
from generate import call_codex_image
result = call_codex_image("your prompt", reference_b64=ref_b64, ref_mime=mime)
```

### Content construction

When passing a reference, the `content` field must be a list (not a string):

```python
content = [
    {"type": "input_text", "text": prompt},
    {"type": "input_image", "image_url": f"data:{mime};base64,{ref_b64}"}
]
```

If the reference is used alone (no text), still wrap it in `input_text` + `input_image` format.

## Pitfalls

- **Only the most recent photo**: The cache only keeps a few images. If the user sent multiple photos across different messages, you might get the wrong one. Check timestamps.
- **DeepSeek can't see images**: DeepSeek models (deepseek-v4-flash/pro) don't support vision. You can't visually verify which image you're using. Just pass it through to Codex.
- **Content filtering**: Requests with reference images are more likely to trigger Codex's content filter. If it hangs (no partial_image event), fall back to text-only prompt describing the reference.
- **MIME type matters**: Telegram caches everything as .jpg by default. Check actual extension from the file — `.jpg` → `image/jpeg`, `.png` → `image/png`.

## Full working example

See the session transcript for a complete example at `/tmp/couple_gen.py` that:
1. Finds the latest cached photo
2. Reads it as base64
3. Sends to Codex with a couple-photo prompt
4. Delivers via openclaw

```python
# Minimal self-contained version
import base64, json, urllib.request, pathlib, time, subprocess

token = json.loads((pathlib.Path.home() / ".codex" / "auth.json").read_text())["tokens"]["access_token"]
ref = sorted(pathlib.Path("/root/.hermes/image_cache").iterdir(), key=lambda p: p.stat().st_mtime)[-1]
b64 = base64.b64encode(ref.read_bytes()).decode()
mime = "image/jpeg" if ref.suffix in (".jpg", ".jpeg") else "image/png"

payload = {
    "model": "gpt-5.4",
    "input": [{"role": "user", "content": [
        {"type": "input_text", "text": "Generate image based on this reference"},
        {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}
    ]}],
    "tools": [{"type": "image_generation"}],
    "stream": True,
}
req = urllib.request.Request(
    "https://chatgpt.com/backend-api/codex/responses",
    data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST"
)
response = urllib.request.urlopen(req, timeout=120)
# ... parse SSE stream for partial_image_b64, save, send via openclaw
```
