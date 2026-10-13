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

Input contract:
    stdin / --prompt-file are read with a *bounded* read (prompt <= 64 KiB of
    UTF-8, total JSON <= 64 KiB + 1 MiB overhead budget) and never truncated
    mid-parse, so a document that fits the budget is validated on its real
    content. A fully-read document whose prompt exceeds 64 KiB returns code
    "prompt_too_large". A document larger than the total budget is dropped at
    the cut *before* parsing, so its prompt size cannot be determined: it returns
    "input_too_large" and the caller must shrink the prompt and/or the other
    fields. Prompts must be real UTF-8: an unpaired surrogate escape (e.g.
    \\ud800) is rejected as "invalid_input" rather than raising.
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
MAX_PROMPT_BYTES = 64 * 1024  # 64 KiB — validated against UTF-8 bytes, not characters
# Bounded total input budget. The overhead covers the JSON structure plus the
# non-prompt fields the caller may send (reference path/metadata, notes, …).
INPUT_OVERHEAD_BYTES = 1024 * 1024  # 1 MiB
MAX_INPUT_BYTES = MAX_PROMPT_BYTES + INPUT_OVERHEAD_BYTES

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


def _encode_utf8_strict(value, label):
    """Encode text as real UTF-8. Returns (bytes, None) or (None, error_record).

    ``value`` may carry unpaired surrogates when it came from a JSON ``\\ud800``
    escape or from undecodable argv bytes (surrogateescape). Those are not valid
    UTF-8, so they are rejected here as ``invalid_input`` instead of letting a
    later ``str.encode("utf-8")`` raise ``UnicodeEncodeError`` out of the CLI or
    out of the ``generate_image`` API.
    """
    try:
        return value.encode("utf-8"), None
    except UnicodeEncodeError:
        return None, {
            "code": "invalid_input",
            "error": (
                f"{label} contains an unpaired surrogate escape and is not valid UTF-8 "
                "(for example a lone \\ud800). Remove the unpaired \\uD800-\\uDFFF escape "
                "and retry."
            ),
        }


def _auth_error(code, message):
    """Structured auth failure record. Never carries file contents or tokens."""
    return {"code": code, "error": message}


def _read_auth_file():
    """Read and parse ~/.codex/auth.json.

    Returns (data, None) on success, (None, error_record) on failure. Never
    raises and never echoes file contents — the file holds an access token.
    """
    auth_path = pathlib.Path.home() / ".codex" / "auth.json"
    if not auth_path.exists():
        return None, _auth_error(
            "no_auth",
            "No Codex credentials at ~/.codex/auth.json. Run `codex login --device-auth`.",
        )

    try:
        raw = auth_path.read_text(encoding="utf-8")
    except OSError as e:
        return None, _auth_error(
            "auth_unreadable",
            f"Cannot read ~/.codex/auth.json ({type(e).__name__}). The credentials file "
            "exists but is unusable — this is not a logged-out state. Fix the file or its "
            "permissions, then re-run `codex login --device-auth`.",
        )

    try:
        data = json.loads(raw)
    except ValueError as e:
        where = ""
        if isinstance(e, json.JSONDecodeError):
            where = f" (line {e.lineno} column {e.colno})"
        return None, _auth_error(
            "auth_invalid",
            "~/.codex/auth.json is not valid JSON"
            + where
            + ". The credentials file is corrupt, not merely logged out — re-run "
            "`codex login --device-auth` to rewrite it.",
        )

    if not isinstance(data, dict):
        return None, _auth_error(
            "auth_malformed",
            "~/.codex/auth.json has an unexpected structure (top level is "
            f"{type(data).__name__}, expected an object with tokens.access_token). "
            "The credentials file is corrupt, not merely logged out — re-run "
            "`codex login --device-auth` to rewrite it.",
        )

    return data, None


def _extract_token(data):
    """Pull tokens.access_token out of a parsed auth object. Returns (token, error)."""
    tokens = data.get("tokens")
    if tokens is None:
        return None, _auth_error(
            "no_auth",
            "No Codex token in ~/.codex/auth.json. Run `codex login --device-auth`.",
        )
    if not isinstance(tokens, dict):
        return None, _auth_error(
            "auth_malformed",
            "~/.codex/auth.json has an unexpected structure (tokens is "
            f"{type(tokens).__name__}, expected an object). The credentials file is corrupt, "
            "not merely logged out — re-run `codex login --device-auth` to rewrite it.",
        )

    token = tokens.get("access_token")
    if token is None or token == "":
        return None, _auth_error(
            "no_auth",
            "No Codex token in ~/.codex/auth.json. Run `codex login --device-auth`.",
        )
    if not isinstance(token, str):
        return None, _auth_error(
            "auth_malformed",
            "~/.codex/auth.json has an unexpected structure (tokens.access_token is "
            f"{type(token).__name__}, expected a string). The credentials file is corrupt, "
            "not merely logged out — re-run `codex login --device-auth` to rewrite it.",
        )

    return token, None


def _load_token():
    """Load Codex access token from ~/.codex/auth.json, refreshing if it is stale.

    Returns (token, None) on success or (None, error_record) on failure. All
    failures are structured: a damaged credentials file is reported as such
    instead of being downgraded to a bare "not logged in".
    """
    data, err = _read_auth_file()
    if err:
        return None, err

    token, err = _extract_token(data)
    if err:
        return None, err

    exp = _decode_jwt_exp(token)
    if exp and exp < time.time() + 300:
        _refresh_token()
        data, err = _read_auth_file()
        if err:
            return None, err
        refreshed, err = _extract_token(data)
        if err:
            return None, err
        if not refreshed:
            # Defensive fallback: _extract_token already reports an empty token
            # as no_auth, so this is not reachable today. If that ever changes,
            # a refresh that leaves no token is still a logged-out state, not a
            # stale refresh chain.
            return None, _auth_error(
                "no_auth",
                "Token refresh left no Codex token in ~/.codex/auth.json. "
                "Run `codex login --device-auth`.",
            )
        token = refreshed

    return token, None


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
    prompt_bytes, enc_err = _encode_utf8_strict(prompt, "prompt")
    if enc_err:
        print(json.dumps({"status": "error", "error": enc_err["error"], "code": enc_err["code"]}), flush=True)
        return None
    prompt_sha = hashlib.sha256(prompt_bytes).hexdigest()[:16]

    for attempt in range(1, 4):
        token, auth_err = _load_token()
        if auth_err or not token:
            err = auth_err or _auth_error(
                "no_auth",
                "No Codex token available from ~/.codex/auth.json. "
                "Run `codex login --device-auth`.",
            )
            print(json.dumps({"status": "error", "error": err["error"], "code": err["code"], "prompt_sha256": prompt_sha}), flush=True)
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

def _read_bounded(source, limit):
    """Read at most `limit` bytes from a binary (or text) stream.

    Returns (text, truncated, error_message). The stream is probed one byte past
    the limit so that "there is more data" is distinguishable from "that is all
    the data", without ever buffering an unbounded amount of input.
    """
    stream = getattr(source, "buffer", source)
    try:
        raw = stream.read(limit + 1)
    except (OSError, ValueError) as e:
        return None, False, f"could not read input ({type(e).__name__})"

    if raw is None:
        return "", False, None

    truncated = len(raw) > limit
    if truncated:
        raw = raw[:limit]

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            if truncated:
                # The cut can fall inside a multi-byte character of otherwise
                # valid UTF-8. Truncation is already reported via `truncated`,
                # and the dropped text is never parsed — decode it leniently so
                # a legal document is never misreported as invalid UTF-8.
                text = raw.decode("utf-8", errors="replace")
            else:
                return None, False, "input is not valid UTF-8"
    else:
        text = raw

    return text, truncated, None


def _classify_oversized_input(label):
    """Report input that exceeded MAX_INPUT_BYTES and was never parsed.

    The bounded read drops everything past MAX_INPUT_BYTES, so the prompt's real
    size cannot be measured here. Whatever the prompt holds, the only defensible
    statement is "the document is too large to parse" — never "the prompt itself
    is within budget".
    """
    return {
        "code": "input_too_large",
        "error": (
            f"{label} exceeds the {MAX_INPUT_BYTES}-byte input budget and was not parsed, so "
            f"the prompt size cannot be determined (a prompt over {MAX_PROMPT_BYTES} bytes is "
            "rejected once the document is read in full). Reduce the prompt and/or the other "
            "fields and retry."
        ),
    }


def _parse_prompt_json(text, label):
    """Parse a complete prompt JSON document. Returns ((prompt, reference), error)."""
    try:
        data = json.loads(text)
    except ValueError as e:
        return None, {"code": "invalid_input", "error": f"Invalid {label}: {e}"}

    if not isinstance(data, dict):
        return None, {"code": "invalid_input", "error": f"Invalid {label}: expected a JSON object"}

    prompt = data.get("prompt")
    if prompt is None or not isinstance(prompt, str):
        return None, {"code": "invalid_input", "error": f"Missing or non-string 'prompt' in {label}"}
    if not prompt.strip():
        return None, {"code": "invalid_input", "error": f"Empty 'prompt' in {label}"}

    _, enc_err = _encode_utf8_strict(prompt, "prompt")
    if enc_err:
        return None, enc_err

    reference = data.get("reference")
    if reference is not None and not isinstance(reference, str):
        return None, {"code": "invalid_input", "error": f"'reference' must be a string path in {label}"}
    if reference is not None:
        _, enc_err = _encode_utf8_strict(reference, "'reference' path")
        if enc_err:
            return None, enc_err

    return (prompt, reference), None


def read_prompt_input(args):
    """
    Read prompt in order of preference:
    1. stdin JSON (from pipe/redirect)
    2. --prompt-file <path>
    3. positional argv (deprecated)

    Input is read with a bounded read and parsed in full — never truncated —
    so an oversized document is reported as input_too_large instead of being
    mislabelled as malformed JSON. Returns ((prompt, reference), None) on
    success or (None, {"code": ..., "error": ...}) on failure.
    """
    # Check stdin first (only if not a TTY, i.e. piped)
    if not sys.stdin.isatty():
        text, truncated, read_err = _read_bounded(sys.stdin, MAX_INPUT_BYTES)
        if read_err:
            return None, {"code": "invalid_input", "error": f"Invalid stdin JSON: {read_err}"}
        if truncated:
            return None, _classify_oversized_input("stdin JSON")
        if text.strip():
            return _parse_prompt_json(text, "stdin JSON")

    # --prompt-file
    if args.prompt_file:
        try:
            with open(args.prompt_file, "rb") as fh:
                text, truncated, read_err = _read_bounded(fh, MAX_INPUT_BYTES)
        except OSError as e:
            return None, {"code": "invalid_input", "error": f"Error reading prompt-file: {type(e).__name__}"}
        if read_err:
            return None, {"code": "invalid_input", "error": f"Error reading prompt-file: {read_err}"}
        if truncated:
            return None, _classify_oversized_input("prompt-file JSON")
        if not text.strip():
            return None, {"code": "invalid_input", "error": "Empty prompt-file"}
        return _parse_prompt_json(text, "prompt-file JSON")

    # Positional argv (deprecated). argv uses surrogateescape for undecodable
    # bytes, so validate here as well as in main().
    if args.prompt:
        import warnings
        warnings.warn("Positional prompt arg is deprecated. Use stdin JSON or --prompt-file.")
        _, enc_err = _encode_utf8_strict(args.prompt, "prompt")
        if enc_err:
            return None, enc_err
        ref_path = args.reference
        return (args.prompt, ref_path), None

    return None, {"code": "invalid_input", "error": "No prompt provided. Pipe JSON to stdin or use --prompt-file."}


# --- Main --------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate images via Codex (gpt-5.4) with optional reference images"
    )
    parser.add_argument("prompt", nargs="?", default=None,
                        help="(DEPRECATED) Text prompt. Use stdin JSON instead — see docs.")
    parser.add_argument("--reference", "-r",
                        help="Path to a reference image; used when the stdin/--prompt-file JSON has no 'reference' field")
    parser.add_argument("--prompt-file", "-f",
                        help="Read prompt from JSON file instead of stdin")
    parser.add_argument("--output", "-o", default=None,
                        help="(DEPRECATED) Custom output path ignored; all output goes to ~/.hermes/codex-images/")

    args = parser.parse_args()

    # Read prompt
    result, err = read_prompt_input(args)
    if err:
        print(json.dumps({"status": "error", "error": err["error"], "code": err["code"]}), flush=True)
        sys.exit(1)

    prompt, ref_path_arg = result

    # Validate prompt size (strict UTF-8: a lone surrogate is invalid_input here
    # rather than an uncaught UnicodeEncodeError).
    prompt_bytes, enc_err = _encode_utf8_strict(prompt, "prompt")
    if enc_err:
        print(json.dumps({"status": "error", "error": enc_err["error"], "code": enc_err["code"]}), flush=True)
        sys.exit(1)
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
    prompt_sha = hashlib.sha256(prompt_bytes).hexdigest()[:16]

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
