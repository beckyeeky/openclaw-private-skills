#!/usr/bin/env python3
"""
Codex Image Generator v2.0.0 — Secure rewrite.

Reads prompt from stdin (JSON) or --prompt-file. No argv leakage.
No filter bypass. Secure file handling with UUID output paths.

Usage (preferred — stdin JSON):
    echo '{"prompt": "a cat in space"}' | python3 generate.py
    echo '{"prompt": "make it cyberpunk", "reference": "/path/img.jpg"}' | python3 generate.py

Usage (--prompt-file):
    python3 generate.py --prompt-file /tmp/prompt.json

Usage (deprecated — positional argv, logs warning):
    python3 generate.py "a cat in space"

Output (stdout — JSON only):
    {"status": "ok", "path": "/root/.hermes/codex-images/uuid.png", "prompt_sha256": "abc...", "model": "gpt-5.4"}
    {"status": "error", "error": "description", "code": "error_code"}

Stderr: Log messages only — request ID, status, timing, safe file metadata.
"""

import json
import base64
import urllib.request
import urllib.error
import time
import pathlib
import sys
import os
import uuid
import argparse

# === Config ===
CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_MODEL = "gpt-5.4"
MAX_WAIT_MS = 5 * 60 * 1000  # 5 minutes max per attempt
SSE_CHUNK_SIZE = 8192
MAX_PROMPT_BYTES = 64 * 1024  # 64 KiB

# Secure output directory
OUTPUT_DIR = pathlib.Path.home() / ".hermes" / "codex-images"
OUTPUT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


# --- Helpers -----------------------------------------------------------

def _decode_jwt_exp(token):
    """Decode JWT exp claim without verification. Returns 0 on failure."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return 0
        seg = parts[1]
        padding = 4 - len(seg) % 4
        if padding != 4:
            seg += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(seg))
        return payload.get("exp", 0)
    except Exception:
        return 0


def _refresh_token():
    """Trigger Codex CLI token refresh by running `codex login status`."""
    import subprocess as sp
    try:
        sp.run(
            ["codex", "login", "status"],
            capture_output=True, timeout=15,
            env={**os.environ, "CODEX_DAEMONIZE": "false"}
        )
    except Exception:
        pass


def _load_token():
    """Load Codex access token from ~/.codex/auth.json, refresh if needed."""
    auth_path = pathlib.Path.home() / ".codex" / "auth.json"
    if not auth_path.exists():
        return None
    data = json.loads(auth_path.read_text())
    token = data.get("tokens", {}).get("access_token")
    if not token:
        return None

    exp = _decode_jwt_exp(token)
    now = time.time()
    if exp and exp < now + 300:
        _refresh_token()
        data = json.loads(auth_path.read_text())
        token = data.get("tokens", {}).get("access_token")

    return token


def _make_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _build_payload(prompt, reference_b64=None, ref_mime="image/png"):
    """Build Codex API request payload. No prompt transformation."""
    if reference_b64:
        content = [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": f"data:{ref_mime};base64,{reference_b64}"},
        ]
    else:
        content = prompt

    return {
        "model": CODEX_MODEL,
        "instructions": "You are a helpful assistant. Use tools when available.",
        "input": [{"role": "user", "content": content}],
        "store": False,
        "tools": [{"type": "image_generation"}],
        "reasoning": {"effort": "low"},
        "include": [],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": True,
    }


# --- Image Generation --------------------------------------------------

def _call_codex_api(payload, token):
    """POST to Codex API, parse SSE stream. Returns image or error dict."""
    headers = _make_headers(token)
    remaining_ms = MAX_WAIT_MS
    timeout_s = max(10, remaining_ms / 1000)

    req = urllib.request.Request(
        CODEX_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        response = urllib.request.urlopen(req, timeout=timeout_s)
    except urllib.error.HTTPError as e:
        code = e.code
        if code == 401:
            return {"image_b64": None, "status": "http_401", "error": str(e)}
        elif code == 429:
            return {"image_b64": None, "status": "http_429", "error": str(e)}
        elif 500 <= code < 600:
            return {"image_b64": None, "status": f"http_{code}", "error": str(e)}
        else:
            return {"image_b64": None, "status": f"http_{code}", "error": str(e), "fatal": True}
    except urllib.error.URLError as e:
        return {"image_b64": None, "status": "connection_error", "error": str(e)}

    image_b64 = None
    status = None
    response_id = None
    read_deadline = time.time() + (remaining_ms / 1000)

    try:
        while time.time() < read_deadline:
            try:
                line_bytes = response.readline()
            except Exception:
                break

            if not line_bytes:
                break

            line = line_bytes.decode("utf-8", errors="replace").strip()

            if not line.startswith("data: "):
                continue

            raw = line[6:]
            if not raw:
                continue

            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue

            t = obj.get("type", "")

            if t == "response.created":
                resp = obj.get("response", {})
                response_id = resp.get("id") or response_id
                status = resp.get("status") or status

            elif t == "response.image_generation_call.partial_image":
                if obj.get("partial_image_b64"):
                    image_b64 = obj["partial_image_b64"]

            elif t == "response.completed":
                resp = obj.get("response", {})
                status = resp.get("status", "completed")
                # If we have the image, we're done
                if image_b64:
                    break
                # Check completed.output for final image
                if not image_b64:
                    for output_item in resp.get("output", []):
                        if output_item.get("type") == "image":
                            content = output_item.get("content", [])
                            for c in content:
                                if c.get("type") == "image_file" and c.get("image_url"):
                                    url = c["image_url"]
                                    if url.startswith("data:image"):
                                        _, b64data = url.split(",", 1)
                                        image_b64 = b64data
                                        break
                break

            elif t == "response.failed":
                status = "failed"
                break

            if image_b64 and (t == "response.completed" or t == "response.failed"):
                break

    finally:
        response.close()

    if not image_b64:
        return {
            "image_b64": None,
            "status": status or "no_image",
            "response_id": response_id,
        }

    return {
        "image_b64": image_b64,
        "status": status or "completed",
        "response_id": response_id,
    }


def generate_image(prompt, reference_b64=None, ref_mime="image/png"):
    """
    Generate image via Codex. No filter bypass strategies.
    Simple retry: max 3 attempts. Retry on 401 (token refresh),
    429 (rate limit), and 5xx (server error).
    """
    import hashlib
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

    for attempt in range(1, 4):
        token = _load_token()
        if not token:
            print(json.dumps({"status": "error", "error": "No Codex auth token found. Run `codex login --device-auth` first.", "code": "no_auth", "prompt_sha256": prompt_sha}), flush=True)
            return None

        print(f"[codex-image] attempt={attempt}/3 rid={uuid.uuid4().hex[:8]} prompt_sha={prompt_sha}", flush=True, file=sys.stderr)

        payload = _build_payload(prompt, reference_b64=reference_b64, ref_mime=ref_mime)
        result = _call_codex_api(payload, token)

        if result.get("image_b64"):
            print(f"[codex-image] success rid={result.get('response_id','?')}", flush=True, file=sys.stderr)
            return result

        status = result.get("status", "unknown")
        fatal = result.get("fatal", False)
        error = result.get("error", "")

        print(f"[codex-image] attempt={attempt} status={status}", flush=True, file=sys.stderr)

        # Fatal errors — don't retry
        if fatal:
            print(json.dumps({"status": "error", "error": f"Codex API error: {status}", "code": status, "prompt_sha256": prompt_sha}), flush=True)
            return None

        # 401 — try refreshing token and retry
        if status == "http_401":
            print("[codex-image] token expired, refreshing...", flush=True, file=sys.stderr)
            _refresh_token()
            if attempt < 3:
                time.sleep(1)
                continue
            print(json.dumps({"status": "error", "error": "All 3 attempts returned 401 — token refresh chain stale. Run `codex login --device-auth`.", "code": "auth_stale", "prompt_sha256": prompt_sha}), flush=True)
            return None

        # 429 — retry with backoff
        if status == "http_429":
            wait = 2 ** attempt
            print(f"[codex-image] rate limited, retrying in {wait}s...", flush=True, file=sys.stderr)
            time.sleep(wait)
            continue

        # 5xx — retry with backoff
        if status.startswith("http_5"):
            wait = 2 ** attempt
            print(f"[codex-image] server error, retrying in {wait}s...", flush=True, file=sys.stderr)
            time.sleep(wait)
            continue

        # "completed" without image means content filtered
        if status == "completed":
            print(json.dumps({"status": "error", "error": "Content filtered by Codex safety system (no image generated)", "code": "filtered", "prompt_sha256": prompt_sha}), flush=True)
            return None

        # Other errors — no retry
        print(json.dumps({"status": "error", "error": f"Codex API error: {status}", "code": status, "prompt_sha256": prompt_sha}), flush=True)
        return None

    print(json.dumps({"status": "error", "error": f"All {3} attempts failed", "code": "max_retries", "prompt_sha256": prompt_sha}), flush=True)
    return None


# --- Output ------------------------------------------------------------

def save_image_secure(image_b64):
    """Decode base64 and save to secure private directory. Returns absolute path."""
    img_bytes = base64.b64decode(image_b64)
    # UUID filename, exclusive create to prevent symlink attacks
    while True:
        filename = f"{uuid.uuid4().hex}.png"
        out_path = OUTPUT_DIR / filename
        try:
            fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(img_bytes)
            return str(out_path.resolve())
        except FileExistsError:
            continue


# --- Prompt Input ------------------------------------------------------

def read_prompt_input(args):
    """
    Read prompt in order of preference:
    1. stdin JSON (from pipe/redirect)
    2. --prompt-file <path>
    3. positional argv (deprecated)
    """
    # Check stdin first (only if not a TTY, i.e. piped)
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read(MAX_PROMPT_BYTES)
            if raw.strip():
                data = json.loads(raw)
                prompt = data.get("prompt", "")
                ref_path = data.get("reference")
                if not prompt.strip():
                    return None, "Empty 'prompt' in stdin JSON"
                return (prompt, ref_path), None
        except json.JSONDecodeError as e:
            return None, f"Invalid stdin JSON: {e}"

    # --prompt-file
    if args.prompt_file:
        try:
            raw = pathlib.Path(args.prompt_file).read_text(encoding="utf-8")[:MAX_PROMPT_BYTES]
            data = json.loads(raw)
            prompt = data.get("prompt", "")
            ref_path = data.get("reference")
            if not prompt.strip():
                return None, "Empty 'prompt' in prompt-file JSON"
            return (prompt, ref_path), None
        except (json.JSONDecodeError, OSError) as e:
            return None, f"Error reading prompt-file: {e}"

    # Positional argv (deprecated)
    if args.prompt:
        import warnings
        warnings.warn("Positional prompt arg is deprecated. Use stdin JSON or --prompt-file.")
        ref_path = args.reference
        return (args.prompt, ref_path), None

    return None, "No prompt provided. Pipe JSON to stdin or use --prompt-file."


# --- Main --------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate images via Codex (gpt-5.4) with optional reference images"
    )
    parser.add_argument("prompt", nargs="?", default=None,
                        help="(DEPRECATED) Text prompt. Use stdin JSON instead — see docs.")
    parser.add_argument("--reference", "-r",
                        help="Path to reference image (used with positional prompt only)")
    parser.add_argument("--prompt-file", "-f",
                        help="Read prompt from JSON file instead of stdin")
    parser.add_argument("--output", "-o", default=None,
                        help="(DEPRECATED) Custom output path ignored; all output goes to ~/.hermes/codex-images/")

    args = parser.parse_args()

    # Read prompt
    result, err = read_prompt_input(args)
    if err:
        print(json.dumps({"status": "error", "error": err, "code": "invalid_input"}), flush=True)
        sys.exit(1)

    prompt, ref_path_arg = result

    # Validate prompt size
    prompt_bytes = prompt.encode("utf-8")
    if len(prompt_bytes) > MAX_PROMPT_BYTES:
        print(json.dumps({"status": "error", "error": f"Prompt too large ({len(prompt_bytes)} bytes, max {MAX_PROMPT_BYTES})", "code": "prompt_too_large"}), flush=True)
        sys.exit(1)

    # Resolve reference image
    reference_b64 = None
    ref_mime = "image/png"
    ref_to_use = ref_path_arg or args.reference

    if ref_to_use:
        ref_path = pathlib.Path(ref_to_use).resolve()
        if not ref_path.exists():
            print(json.dumps({"status": "error", "error": f"Reference not found: {ref_to_use}", "code": "ref_not_found"}), flush=True)
            sys.exit(1)
        if ref_path.is_symlink():
            print(json.dumps({"status": "error", "error": "Reference is a symlink — rejected", "code": "ref_symlink"}), flush=True)
            sys.exit(1)

        # Validate MIME from magic bytes
        img_bytes = ref_path.read_bytes()
        magic = img_bytes[:8]
        mime_map = {
            b"\x89PNG\r\n\x1a\n": "image/png",
            b"\xff\xd8": "image/jpeg",
            b"RIFF": "image/webp",  # WEBP starts with RIFF
            b"GIF87a": "image/gif",
            b"GIF89a": "image/gif",
        }
        detected_mime = None
        for sig, m in mime_map.items():
            if magic.startswith(sig if sig != b"RIFF" else b"RIFF") or (sig == b"RIFF" and magic[:4] == b"RIFF"):
                detected_mime = m
                break
        # WEBP: check after RIFF header
        if detected_mime is None and magic[:4] == b"RIFF":
            detected_mime = "image/webp"

        if not detected_mime:
            print(json.dumps({"status": "error", "error": f"Unrecognized image format for: {ref_path.name}", "code": "bad_mime"}), flush=True)
            sys.exit(1)

        ref_mime = detected_mime

        # Validate size (max 20MB)
        if len(img_bytes) > 20 * 1024 * 1024:
            print(json.dumps({"status": "error", "error": f"Reference too large ({len(img_bytes)} bytes, max 20MB)", "code": "ref_too_large"}), flush=True)
            sys.exit(1)

        reference_b64 = base64.b64encode(img_bytes).decode()

    # Generate
    result = generate_image(prompt, reference_b64, ref_mime)
    if result is None:
        sys.exit(1)

    # Save
    try:
        out_path = save_image_secure(result["image_b64"])
        file_size = os.path.getsize(out_path)
    except Exception as e:
        print(json.dumps({"status": "error", "error": f"Failed to save image: {e}", "code": "save_failed"}), flush=True)
        sys.exit(1)

    import hashlib
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

    print(f"[codex-image] saved {out_path} ({file_size} bytes)", flush=True, file=sys.stderr)

    output = {
        "status": "ok",
        "path": out_path,
        "prompt_sha256": prompt_sha,
        "size_bytes": file_size,
        "model": CODEX_MODEL,
    }
    print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
