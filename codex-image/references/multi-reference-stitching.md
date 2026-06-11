# Multi-Reference Stitching

`codex-image` passes a single `reference_b64` to the Codex API. For multiple reference images, stitch them first.

## ffmpeg hstack

```bash
# Resize both to same height, then stack side-by-side
ffmpeg -y -i img1.jpg -i img2.jpg \
  -filter_complex "[0]scale=-1:500[top];[1]scale=-1:500[bot];[top][bot]hstack=inputs=2" \
  -q:v 2 combined.jpg
```

## Pass to generate.py

```bash
echo '{"prompt": "combine both styles", "reference": "/tmp/combined.jpg"}' | python3 generate.py
```
