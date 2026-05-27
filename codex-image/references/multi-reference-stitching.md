# Multi-Reference Image Stitching for Codex

When the user wants Codex to reference **two or more images**, stitch them into one combined image before passing to `call_codex_image(reference_b64=...)`.

## Why

`call_codex_image` only accepts ONE `reference_b64` parameter. The Codex API supports multiple `input_image` entries at the HTTP level, but the existing generate.py wrapper doesn't expose multi-image.

## Recipe: ffmpeg hstack

```bash
# 1. Check dimensions (hstack requires same height)
ffprobe -v error -show_entries stream=width,height -of csv=p=0 img1.jpg
ffprobe -v error -show_entries stream=width,height -of csv=p=0 img2.jpg

# 2. Resize both to same height, then hstack
ffmpeg -y -i img1.jpg -i img2.jpg \
  -filter_complex "[0]scale=-1:500[top];[1]scale=-1:500[bot];[top][bot]hstack=inputs=2" \
  -q:v 2 combined.jpg
```

## Python Wrapper Pattern

```python
import base64, pathlib, subprocess

# Import generate.py functions (monkey-patch import to avoid main-block side-effects)
builtins.print = lambda *a, **kw: None
import generate
builtins.print = __import__('builtins').print  # restore

# Stitch refs
combined = pathlib.Path("/tmp/ref_combined.jpg")
# ... run ffmpeg ...

ref_b64 = base64.b64encode(combined.read_bytes()).decode()
result = generate.call_codex_image(prompt, reference_b64=ref_b64, ref_mime="image/jpeg")
```

## Pitfalls

- ~~**generate.py imports run main code**: The generate.py script runs its entire main block at module level (not inside `if __name__ == "__main__"`).~~ **[FIXED in v1.9]** `if __name__` guard added - import generate.py safely now.
- **Content filtering on second call**: Codex may filter identical/similar reference submissions on repeated calls. If the second generation times out (no image returned), fall back to a text-only prompt that describes the reference content.
- **deepseek-v4-pro no vision**: The `vision_analyze` tool doesn't work with deepseek models. If the user sends reference images and you can't see them, explain the limitation and ask for text descriptions.

## Token Path

The Codex auth token lives at `~/.codex/auth.json` under:
```python
auth_data["tokens"]["access_token"]
```
NOT `auth_data["token"]` (doesn't exist). The file also contains `id_token`, `refresh_token`, `account_id`.
