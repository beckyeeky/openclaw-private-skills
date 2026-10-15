#!/usr/bin/env python3
"""Fetch one user-authorized WSJ ArticleContent request conservatively.

Secrets: reads WSJ_DJ_AUTHORIZATION only from the process environment. It never
writes or prints the value. The GraphQL template is non-secret JSON stored in a
user runtime directory, never under the installed skill or Git repository.

Supports:
  --origin-id SB… / WP-WSJ-…
  --url https://www.wsj.com/...   (browser metadata resolver first, then one fetch)
  --from-json path                (offline parse of an already-authorized response)

TLS: by default the request uses the system trust store with certificate and
hostname verification always on. An explicit local extra CA may optionally be
appended through WSJ_CA_BUNDLE (never substituted); an unreadable, empty, or
malformed bundle fails before any request is sent. ``--insecure`` disables
verification for one explicitly requested run only — never automatically,
never persistently, and never as a reaction to a certificate error. TLS/network
failures are reported only as fixed safe categories without tokens, request
URLs, or headers. ``--network-retries`` (0-2, default 0) retries only connect
timeouts, temporary DNS failures, and connection resets; every real attempt
consumes the hourly/daily budget and is recorded.
"""
from __future__ import annotations

import argparse
import errno
import datetime as dt
from http.client import IncompleteRead
import json
import os
import random
import re
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


class RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urlopen(req, timeout=45, context=None):
    """One authorized request; never forward credentials through redirects."""
    return build_opener(RefuseRedirects(), HTTPSHandler(context=context)).open(req, timeout=timeout)


ROOT = Path(os.environ.get("WSJ_READER_HOME", "~/.openclaw/wsj-article-reader")).expanduser()
TEMPLATE = ROOT / "template.json"
STATE = ROOT / "state.json"
ARTICLES = ROOT / "articles"
HOUR_LIMIT, DAY_LIMIT, MIN_GAP = 6, 20, 15 * 60
ENDPOINT_ALLOWED = "https://shared-data.dowjones.io/gateway/graphql"
ORIGIN_RE = re.compile(r"^(?:SB\d{10,}|WP-WSJ[O0-9A-Z-]*-\d+)$", re.I)
WSJ_HOST_RE = re.compile(r"(?:^|\.)wsj\.com$", re.I)
CA_BUNDLE_ENV = "WSJ_CA_BUNDLE"
RESOLVER = Path(__file__).resolve().parent / "resolve_origin_id.py"
MAX_NETWORK_RETRIES = 2
RETRY_METHODS = frozenset({'GET'})

# Explicit opt-in only (--insecure). Never enabled by an environment variable,
# a config file, or automatically after a certificate failure.
INSECURE_WARNING = (
    "WARNING: --insecure was requested explicitly for this single run. TLS "
    "certificate and hostname verification are DISABLED for this request only; "
    "the connection can be intercepted or modified. This is never automatic, "
    "never persistent, and it is not used to recover from a certificate error. "
    "Fixing local TLS trust is the correct remedy."
)

# Fixed, non-sensitive TLS/network reporting. Messages must never be built from
# exception text (which can carry a URL/host), tokens, or request headers.
TLS_CERT_UNTRUSTED = "tls_certificate_untrusted"
TLS_HANDSHAKE_FAILED = "tls_handshake_failed"
NETWORK_ERROR = "network_error"
NETWORK_TIMEOUT = "network_timeout"

NETWORK_MESSAGES = {
    TLS_CERT_UNTRUSTED: (
        "TLS category: tls_certificate_untrusted — the server certificate chain "
        "could not be verified against the local trust store (for example an "
        "unknown issuer or a missing intermediate). Fix local TLS trust first, "
        "then start one new request manually. Verification is never relaxed "
        "automatically and this category is never retried."
    ),
    TLS_HANDSHAKE_FAILED: (
        "TLS category: tls_handshake_failed — the TLS handshake failed for a "
        "reason other than certificate trust (protocol, cipher, or connection "
        "reset). Fix the local TLS setup first, then start one new request "
        "manually. This category is never retried."
    ),
    NETWORK_TIMEOUT: (
        "Network category: network_timeout — the request timed out before a "
        "response arrived."
    ),
    NETWORK_ERROR: (
        "Network category: network_error — the request could not reach the "
        "content endpoint (name resolution, routing, or a dropped connection)."
    ),
}


def die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime | None = None) -> str:
    return (t or now()).replace(microsecond=0).isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return default
    except Exception:
        die(f"Invalid local runtime file: {path.name}")


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def parse_time(v: str) -> dt.datetime:
    return dt.datetime.fromisoformat(v.replace("Z", "+00:00"))


def precheck_ca_bundle(path: Path) -> ssl.SSLContext:
    """Validate a user-supplied extra CA bundle *before* any request is sent.

    Rejects missing, unreadable, empty, non-PEM, and unparsable files. Returns a
    throwaway context only to prove the bundle loads; the caller builds the real
    context. Certificate verification is never weakened here.
    """
    if not path.exists():
        die(f"{CA_BUNDLE_ENV} points to a missing file: {path}")
    if not path.is_file():
        die(f"{CA_BUNDLE_ENV} is not a regular file: {path}")
    try:
        size = path.stat().st_size
    except OSError:
        die(f"{CA_BUNDLE_ENV} could not be inspected: {path}")
    if size == 0:
        die(
            f"{CA_BUNDLE_ENV} is empty (0 bytes): {path}. Export the CA "
            "certificate chain as PEM text before retrying."
        )
    try:
        raw = path.read_bytes()
    except OSError:
        die(f"{CA_BUNDLE_ENV} is not readable: {path}")
    if b"-----BEGIN CERTIFICATE-----" not in raw or b"-----END CERTIFICATE-----" not in raw:
        die(
            f"{CA_BUNDLE_ENV} is not a PEM certificate bundle: {path}. "
            "A DER/binary or truncated file cannot be used."
        )
    probe = ssl.create_default_context()
    try:
        probe.load_verify_locations(cafile=str(path))
        added = probe.cert_store_stats().get("x509", 0)
    except (ssl.SSLError, OSError, ValueError):
        die(
            f"{CA_BUNDLE_ENV} could not be parsed as a certificate bundle: {path}. "
            "Re-export it and retry."
        )
    if added <= 0:
        die(f"{CA_BUNDLE_ENV} contains no usable certificate: {path}")
    return probe


def explicit_insecure_context() -> ssl.SSLContext:
    """Unverified context, reachable only through the explicit ``--insecure`` flag.

    This function is the single place in the file that touches
    ``verify_mode``/``check_hostname``. It is never called from error handling,
    so a certificate failure can never downgrade verification on its own.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def safe_tls_context(insecure: bool = False) -> ssl.SSLContext:
    """Build the HTTPS context: system CAs + optional WSJ_CA_BUNDLE, verification on.

    Uses ``create_default_context`` (so the platform trust store stays in
    effect) and only *appends* an explicit local bundle via
    ``load_verify_locations``. Verification is disabled only when the caller
    passes ``insecure=True``, which happens solely for the explicit
    ``--insecure`` flag; there is no environment variable or automatic path to
    an unverified context.
    """
    if insecure:
        print(INSECURE_WARNING, file=sys.stderr)
        return explicit_insecure_context()
    ctx = ssl.create_default_context()
    extra = (os.environ.get(CA_BUNDLE_ENV) or "").strip()
    if extra:
        path = Path(extra).expanduser()
        precheck_ca_bundle(path)  # fails before any network activity
        try:
            ctx.load_verify_locations(cafile=str(path))
        except (ssl.SSLError, OSError, ValueError):
            die(
                f"{CA_BUNDLE_ENV} could not be loaded into the TLS context: {path}. "
                "No request was sent."
            )
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
        die("Refusing to continue without full TLS certificate verification.")
    return ctx


def classify_network_error(exc: BaseException) -> tuple[str, str]:
    """Map a transport failure to a fixed (category, message) pair.

    The returned text is assembled from constants only, so no token, request
    URL, query string, header, or raw exception text can leak into output.
    """
    reason = getattr(exc, "reason", exc)
    seen = set()
    while isinstance(reason, BaseException) and id(reason) not in seen:
        seen.add(id(reason))
        if isinstance(reason, ssl.SSLCertVerificationError):
            return TLS_CERT_UNTRUSTED, NETWORK_MESSAGES[TLS_CERT_UNTRUSTED]
        if isinstance(reason, ssl.SSLError):
            return TLS_HANDSHAKE_FAILED, NETWORK_MESSAGES[TLS_HANDSHAKE_FAILED]
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return NETWORK_TIMEOUT, NETWORK_MESSAGES[NETWORK_TIMEOUT]
        nxt = getattr(reason, "reason", None)
        if nxt is None or nxt is reason:
            break
        reason = nxt
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return NETWORK_TIMEOUT, NETWORK_MESSAGES[NETWORK_TIMEOUT]
    return NETWORK_ERROR, NETWORK_MESSAGES[NETWORK_ERROR]


RETRYABLE_DNS_CODES = frozenset(
    {getattr(socket, "EAI_AGAIN", -3), getattr(socket, "EAI_FAIL", -4)}
)
RETRYABLE_OS_ERRORS = frozenset(
    {errno.ECONNRESET, errno.EPIPE, errno.ECONNABORTED, errno.ETIMEDOUT}
)


def is_retryable_transport_error(exc: BaseException) -> bool:
    """True only for connect timeouts, temporary DNS failures, connection resets.

    Everything else is final: TLS verification errors and other TLS failures,
    HTTP errors of any status (401/403/429/5xx included), entitlement results,
    and schema/template rejections are never retried.
    """
    reason = getattr(exc, "reason", exc)
    seen = set()
    while isinstance(reason, BaseException) and id(reason) not in seen:
        seen.add(id(reason))
        if isinstance(reason, ssl.SSLError):
            # Covers SSLCertVerificationError and every other handshake failure.
            return False
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return True
        if isinstance(reason, socket.gaierror):
            return reason.errno in RETRYABLE_DNS_CODES
        if isinstance(reason, ConnectionResetError):
            return True
        if isinstance(reason, OSError):
            return reason.errno in RETRYABLE_OS_ERRORS
        nxt = getattr(reason, "reason", None)
        if nxt is None or nxt is reason:
            break
        reason = nxt
    return False


def validate_network_retries(value: int) -> int:
    if not isinstance(value, int) or value < 0:
        die("--network-retries must be 0 or greater; no request was sent.")
    if value > MAX_NETWORK_RETRIES:
        die(
            f"--network-retries is capped at {MAX_NETWORK_RETRIES}; "
            "no request was sent."
        )
    return value


def attempt_note(attempts: int, retries: int) -> str:
    if attempts <= 1:
        return " No automatic retry was performed."
    return (
        f" {attempts} attempts were made in this run under "
        f"--network-retries={retries}."
    )


def validate_template(t: dict) -> None:
    required = {"endpoint", "operation_name", "query", "headers"}
    if not isinstance(t, dict) or not required <= t.keys():
        die("Template is incomplete; refresh your own non-secret ArticleContent template.")
    if t["endpoint"] != ENDPOINT_ALLOWED:
        die("Template endpoint is not the permitted WSJ GraphQL endpoint.")
    if t["operation_name"] != "ArticleContent":
        die("Template is not an ArticleContent template.")
    if not isinstance(t["query"], dict) or not isinstance(t["headers"], dict):
        die("Template query/headers must be objects.")
    forbidden = ("authorization", "cookie", "token", "secret", "password")
    found = [k for k in t["headers"] if any(x in k.lower() for x in forbidden)]
    if found:
        die("Template contains a credential-like header; remove it before use.")
    ext = t["query"].get("extensions") or {}
    if not isinstance(ext, dict) or "persistedQuery" not in ext:
        die("Template query.extensions.persistedQuery is missing.")


def allowed(state: dict, override_wait: bool) -> None:
    attempts = state.get("attempts", [])
    cutoff_h, cutoff_d = now() - dt.timedelta(hours=1), now() - dt.timedelta(days=1)
    recent_h = [x for x in attempts if parse_time(x["at"]) >= cutoff_h]
    recent_d = [x for x in attempts if parse_time(x["at"]) >= cutoff_d]
    if len(recent_h) >= HOUR_LIMIT:
        die("Local hourly limit reached (6 requests/hour).")
    if len(recent_d) >= DAY_LIMIT:
        die("Local daily limit reached (20 requests/day).")
    if attempts and not override_wait:
        elapsed = (now() - parse_time(attempts[-1]["at"])).total_seconds()
        if elapsed < MIN_GAP:
            die(
                f"Local cooldown active; wait {int(MIN_GAP - elapsed)} seconds "
                "or use --allow-once."
            )


def record(state: dict, article_id: str, status, phase=None) -> None:
    entry = {"at": iso(), "id": str(article_id)[-12:], "status": status}
    if phase:
        entry["phase"] = phase
    state.setdefault("attempts", []).append(entry)
    state["attempts"] = state["attempts"][-100:]
    save_json(STATE, state)


def text_node(node) -> str:
    """Extract plain text from TextAndDecorations / ParagraphArticleBody / str."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    flat = node.get("flattened")
    if isinstance(flat, dict) and isinstance(flat.get("text"), str):
        return flat["text"]
    tad = node.get("textAndDecorations")
    if isinstance(tad, dict):
        return text_node(tad)
    if isinstance(node.get("text"), str):
        return node["text"]
    return ""


def apply_inline(text: str, decorations) -> str:
    """Apply LINK/BOLD/ITALIC decorations onto plain text (outermost-first)."""
    if not text or not decorations:
        return text
    spans = []
    for d in decorations:
        if not isinstance(d, dict):
            continue
        try:
            start = int(d.get("startIndex", 0))
            length = int(d.get("decorationLength", 0))
        except (TypeError, ValueError):
            continue
        if length <= 0 or start < 0 or start >= len(text):
            continue
        end = min(len(text), start + length)
        dtype = (d.get("decorationType") or "").upper()
        meta = d.get("decorationMetadata") or {}
        if dtype == "LINK":
            uri = ""
            if isinstance(meta, dict):
                uri = meta.get("uri") or ""
            spans.append((start, end, "link", uri))
        elif dtype == "BOLD":
            spans.append((start, end, "bold", None))
        elif dtype == "ITALIC":
            spans.append((start, end, "italic", None))
        # PERSON/COMPANY/DEFAULT/BREAK: keep plain text
    if not spans:
        return text

    # Merge by processing from the end so earlier indices stay valid.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    # Build uniquely covered segments via simple stack on sorted starts — fallback:
    # apply non-overlapping preference to longer spans first, then shorter if free.
    used = [False] * len(text)
    applied = []  # (start, end, type, uri)
    for start, end, dtype, uri in sorted(spans, key=lambda s: (-(s[1] - s[0]), s[0])):
        if any(used[i] for i in range(start, end)):
            continue
        for i in range(start, end):
            used[i] = True
        applied.append((start, end, dtype, uri))
    applied.sort(key=lambda s: s[0])

    out = []
    cursor = 0
    for start, end, dtype, uri in applied:
        if cursor < start:
            out.append(text[cursor:start])
        segment = text[start:end]
        if dtype == "link" and uri:
            out.append(f"[{segment}]({uri})")
        elif dtype == "bold":
            out.append(f"**{segment}**")
        elif dtype == "italic":
            out.append(f"*{segment}*")
        else:
            out.append(segment)
        cursor = end
    if cursor < len(text):
        out.append(text[cursor:])
    return "".join(out)


def decorated_text(node) -> str:
    if not isinstance(node, dict):
        return text_node(node)
    # Prefer node that holds flattened directly or via textAndDecorations
    holder = node
    if "flattened" not in holder and isinstance(node.get("textAndDecorations"), dict):
        holder = node["textAndDecorations"]
    flat = holder.get("flattened") if isinstance(holder, dict) else None
    if not isinstance(flat, dict):
        return text_node(node)
    raw = flat.get("text") or ""
    return apply_inline(raw, flat.get("decorations") or [])


def image_url(block: dict) -> str:
    dv = block.get("displayVariants") or {}
    for key in ("defaultVariant", "wideDisplayVariant", "narrowDisplayVariant"):
        var = dv.get(key) if isinstance(dv, dict) else None
        if isinstance(var, dict) and var.get("combinedUrl"):
            return var["combinedUrl"]
    src = block.get("src")
    if isinstance(src, dict):
        base = (src.get("baseUrl") or "").rstrip("/")
        path = src.get("path") or ""
        if base and path:
            return f"{base}{path}"
    return ""


def body_block_markdown(block: dict) -> str | None:
    if not isinstance(block, dict):
        return None
    t = block.get("__typename") or ""

    if t == "ParagraphArticleBody":
        text = decorated_text(block).strip()
        return text or None

    if t == "BlockquoteArticleBody":
        text = decorated_text(block).strip()
        if not text:
            return None
        return "\n".join(f"> {ln}" if ln else ">" for ln in text.splitlines())

    if t == "TaglineArticleBody":
        text = decorated_text(block).strip()
        return f"*{text}*" if text else None

    if t == "ImageArticleBody":
        url = image_url(block)
        alt = (block.get("altText") or block.get("hed") or "image").strip() or "image"
        caption = decorated_text(block.get("richTextCaption") or {}) or (
            block.get("caption") or ""
        )
        credit = block.get("formattedCredit") or block.get("credit") or ""
        lines = []
        if url:
            lines.append(f"![{alt}]({url})")
        elif caption:
            lines.append(f"*[Image: {caption}]*")
        else:
            lines.append("*[Image]*")
        note = " ".join(x for x in (caption.strip(), f"({credit})" if credit else "") if x)
        if note:
            lines.append(f"*{note}*")
        return "\n".join(lines)

    if t == "AudioArticleBody":
        content = block.get("content") or {}
        if not isinstance(content, dict):
            return "*[Audio]*"
        title = ""
        hl = content.get("headline")
        if isinstance(hl, dict):
            title = hl.get("text") or ""
        title = title or content.get("name") or "Audio"
        link = content.get("linkUrl") or content.get("linkShortUrl") or content.get("audioUrl") or ""
        pod = content.get("podcastName") or content.get("columnName") or ""
        label = f"{pod}: {title}" if pod else title
        return f"🎧 [{label}]({link})" if link else f"🎧 {label}"

    if t == "VideoArticleBody":
        caption = decorated_text(block.get("richTextCaption") or {}) or (
            block.get("caption") or ""
        )
        vc = block.get("videoContent") or {}
        duration = ""
        link = ""
        if isinstance(vc, dict):
            duration = vc.get("formattedDuration") or ""
            # No stable public watch URL always present; prefer description URL if unescaped
            ad = (vc.get("adTagParams") or {}).get("descriptionUrl") if isinstance(vc.get("adTagParams"), dict) else None
            if isinstance(ad, str) and ad:
                try:
                    from urllib.parse import unquote

                    link = unquote(ad)
                except Exception:
                    link = ad
        label = caption or "Video"
        if duration:
            label = f"{label} ({duration})"
        if link:
            return f"🎬 [{label}]({link})"
        return f"🎬 {label}"

    if t == "NewsletterInsetArticleBody":
        return None

    # Unknown block: try text extraction; otherwise skip silently.
    fallback = decorated_text(block).strip()
    return fallback or None


def _paragraph_style(block: dict) -> tuple[str, str]:
    """Return (text, dominant_style) for a short sign-off paragraph."""
    text = text_node(block).strip()
    flat = ((block.get("textAndDecorations") or {}).get("flattened") or {})
    decs = flat.get("decorations") or []
    style = ""
    if isinstance(decs, list) and len(decs) == 1 and isinstance(decs[0], dict):
        d0 = decs[0]
        try:
            start = int(d0.get("startIndex", 0))
            length = int(d0.get("decorationLength", 0))
        except (TypeError, ValueError):
            start, length = 0, 0
        if start == 0 and length >= max(0, len(text) - 2):
            style = (d0.get("decorationType") or "").upper()
    return text, style


def authors_line(article: dict) -> str:
    authors = article.get("authors") or []
    names = []
    for a in authors:
        if isinstance(a, dict) and a.get("text"):
            names.append(a["text"].strip())
    if names:
        return ", ".join(names)
    by = text_node(article.get("articleByline") or {})
    by = by.strip()
    if by.lower().startswith("by "):
        by = by[3:].strip()
    if by:
        return by
    # TaglineArticleBody (columnist sign-off).
    for block in article.get("articleBody") or []:
        if isinstance(block, dict) and block.get("__typename") == "TaglineArticleBody":
            tag = decorated_text(block).strip().rstrip(" ,")
            if tag:
                return tag
    # Letters: trailing short BOLD name paragraph, often followed by ITALIC location.
    paras = [
        b
        for b in (article.get("articleBody") or [])
        if isinstance(b, dict) and b.get("__typename") == "ParagraphArticleBody"
    ]
    if len(paras) >= 1:
        text, style = _paragraph_style(paras[-1])
        if style == "BOLD" and 0 < len(text) <= 80:
            return text
        if len(paras) >= 2:
            prev_text, prev_style = _paragraph_style(paras[-2])
            if prev_style == "BOLD" and style == "ITALIC" and 0 < len(prev_text) <= 80:
                return prev_text
    return ""


def markdown(article: dict) -> tuple[str, str]:
    title = text_node(article.get("articleHeadline") or {}) or "WSJ article"
    standfirst = ""
    sf = article.get("standFirst")
    if isinstance(sf, dict):
        standfirst = decorated_text(sf).strip()
    elif isinstance(sf, str):
        standfirst = sf.strip()

    body_parts = []
    for block in article.get("articleBody") or []:
        md = body_block_markdown(block)
        if md:
            body_parts.append(md)

    section = article.get("sectionName") or ""
    column = article.get("columnName") or ""
    section_line = section
    if column and column != section:
        section_line = f"{section} / {column}" if section else column

    lines = [
        f"# {title}",
        "",
        "- Source: Wall Street Journal",
        f"- URL: {article.get('sourceUrl') or ''}",
        f"- Author: {authors_line(article)}",
        f"- Section: {section_line}",
        f"- Published: {article.get('publishedDateTimeUtc') or ''}",
        f"- Updated: {article.get('updatedDateTimeUtc') or ''}",
        f"- Origin ID: {article.get('originId') or ''}",
        f"- Retrieved: {iso()}",
        "",
    ]
    if standfirst:
        lines += [f"> {standfirst}", ""]
    lines += ["---", ""]
    if body_parts:
        # Separate blocks with blank lines
        body_md = "\n\n".join(body_parts)
        lines.append(body_md)
        lines.append("")
    return "\n".join(lines), title


def normalize_origin_id(value: str) -> str:
    v = (value or "").strip()
    if not v:
        die("Empty origin id")
    if ORIGIN_RE.match(v):
        return v
    # Allow bare paste of longer internal ids that still start with SB
    if re.match(r"^SB\d{10,}$", v):
        return v
    die(f"Unrecognized origin id format: {v[:40]}")


def resolve_origin_via_browser(url: str) -> str:
    """Resolve the *current* article's origin id from public rendered metadata.

    Delegates to the bundled resolver, which reads only the page's canonical URL
    and its own ``articleId`` metadata. Related/recommended stories carry their
    own ids, so this helper never falls back to "first id anywhere in the HTML".
    If the browser CLI is unavailable or metadata is ambiguous, it fails loudly
    and no authorized request is made.
    """
    url = (url or "").strip()
    if not url.startswith("http"):
        die("URL must start with http(s)://")
    host = urlparse(url).hostname or ""
    if not WSJ_HOST_RE.search(host):
        die("URL host is not wsj.com")
    if not RESOLVER.exists():
        die(
            "Browser metadata resolver is missing from this skill: "
            f"{RESOLVER.name}. Reinstall the skill or pass --origin-id."
        )
    # The resolver reads public metadata only: never hand it the access token.
    child_env = dict(os.environ)
    child_env.pop("WSJ_DJ_AUTHORIZATION", None)
    try:
        proc = subprocess.run(
            [sys.executable, str(RESOLVER), url],
            capture_output=True,
            text=True,
            timeout=120,
            env=child_env,
        )
    except FileNotFoundError:
        die("Could not start the browser metadata resolver (no local python3).")
    except subprocess.TimeoutExpired:
        die(
            "Browser metadata resolution timed out; the browser was unavailable "
            "or did not finish loading. Re-run later and pass --origin-id if you "
            "already have one. No authorized request was sent."
        )
    if proc.returncode != 0:
        lines = [ln.strip() for ln in (proc.stderr or "").splitlines() if ln.strip()]
        reason = lines[-1] if lines else "no diagnostic output"
        die(
            "Could not resolve an origin id from public metadata: "
            f"{reason}\n"
            "The built-in browser may be unavailable, or the page exposed no "
            "unambiguous current-article id. Related/recommended-story ids are "
            "deliberately not used. No authorized request was sent."
        )
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        die("Browser metadata resolver returned no origin id; no request was sent.")
    return normalize_origin_id(lines[-1])


def extract_article_from_response(payload: dict) -> dict:
    try:
        article = payload["data"]["articleContent"]
    except Exception:
        die("Unexpected response schema; no export written.")
    if not article:
        die("No entitled article content returned; stopped.")
    if not isinstance(article, dict):
        die("Unexpected articleContent type; stopped.")
    return article


def slugify(value: str) -> str:
    s = "".join(c if c.isalnum() else "-" for c in value).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[-64:] or "article"


def write_article(article: dict, origin_id: str) -> tuple[Path, str]:
    md, title = markdown(article)
    ARTICLES.mkdir(parents=True, exist_ok=True)
    out = ARTICLES / f"{slugify(origin_id or article.get('originId') or 'article')}.md"
    out.write_text(md, "utf-8")
    return out, title


def build_request(template: dict, origin_id: str) -> tuple[str, dict]:
    query = {}
    for key, value in template["query"].items():
        # Persisted-query fields were JSON strings in the original URL.
        query[key] = (
            json.dumps(value, separators=(",", ":"))
            if isinstance(value, (dict, list))
            else str(value)
        )
    try:
        variables = json.loads(query.get("variables") or "{}")
    except json.JSONDecodeError:
        variables = {}
    if not isinstance(variables, dict):
        variables = {}
    variables.update(
        {"id": origin_id, "idType": "originid", "filterByScope": "MOBILE"}
    )
    query["variables"] = json.dumps(variables, separators=(",", ":"))
    query["operationName"] = template["operation_name"]
    url = template["endpoint"] + "?" + urlencode(query)
    headers = dict(template["headers"])
    headers["Authorization"] = os.environ["WSJ_DJ_AUTHORIZATION"]
    headers["Accept-Language"] = "en-US,en;q=0.9"
    return url, headers


def fetch_remote(
    template: dict,
    origin_id: str,
    allow_once: bool,
    context: ssl.SSLContext | None = None,
    network_retries: int = 0,
) -> dict:
    if not os.environ.get("WSJ_DJ_AUTHORIZATION"):
        die("WSJ_DJ_AUTHORIZATION is not set.")
    retries = validate_network_retries(network_retries)
    ctx = context or safe_tls_context()
    url, headers = build_request(template, origin_id)
    attempts = 0
    while True:
        attempts += 1
        # Reload per attempt: every real attempt consumes the hourly/daily budget.
        state = load_json(STATE, {"attempts": []})
        # The interactive cooldown gates the first attempt only; explicit retries
        # in the same run are not blocked by it, but still respect the limits.
        allowed(state, override_wait=allow_once or attempts > 1)
        # Pacing on the first attempt, then a short bounded backoff. No burst.
        time.sleep(random.uniform(2, 6) if attempts == 1 else random.uniform(3, 6))
        phase = 'connect'
        try:
            with urlopen(
                Request(url, headers=headers, method="GET"), timeout=45, context=ctx
            ) as r:
                status = r.status
                phase = 'body'
                raw = r.read()
        except HTTPError as e:
            # Publisher access decisions and every other HTTP status are final.
            record(state, origin_id, e.code)
            if 300 <= e.code < 400:
                die(f"WSJ returned HTTP {e.code} (redirect); credentials are never re-sent and no second request was made.")
            if e.code in (401, 403):
                die(
                    f"WSJ returned HTTP {e.code} (authorization or entitlement "
                    "denied); stopped without retry."
                )
            if e.code == 429:
                die("WSJ returned HTTP 429 (rate limited); stopped without retry.")
            die(f"WSJ returned HTTP {e.code}; stopped without retry.")
        except IncompleteRead:
            record(state, origin_id, 'network_body_interrupted', phase)
            if attempts <= retries:
                continue
            die('Network category: network_body_interrupted — response transfer was truncated.' + attempt_note(attempts, retries))
        except (URLError, ssl.SSLError, OSError) as e:
            category, message = classify_network_error(e)
            record(state, origin_id, category, None if category in (TLS_CERT_UNTRUSTED, TLS_HANDSHAKE_FAILED) else phase)
            retryable = is_retryable_transport_error(e)
            if retryable and attempts <= retries:
                continue
            die(message + attempt_note(attempts, retries))
        record(state, origin_id, status)
        if status != 200:
            die(f"Unexpected HTTP {status}; stopped.")
        # Response may be plain JSON (capture) or compressed by urllib already.
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            die("Response was not JSON; stopped.")
        return payload


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--origin-id",
        help="WSJ origin id (SB… / WP-WSJ-…), from app or public articleId",
    )
    src.add_argument(
        "--url",
        help="WSJ article URL; resolved through the browser metadata resolver",
    )
    src.add_argument(
        "--from-json",
        type=Path,
        help="Offline: parse a saved ArticleContent JSON response (no network)",
    )
    ap.add_argument(
        "--allow-once",
        action="store_true",
        help="Explicitly bypass only the 15-minute local cooldown once",
    )
    ap.add_argument(
        "--network-retries",
        type=int,
        default=0,
        help=(
            f"Bounded retries for transient transport faults only "
            f"(0-{MAX_NETWORK_RETRIES}, default 0)"
        ),
    )
    ap.add_argument(
        "--insecure",
        action="store_true",
        help=(
            "Disable TLS certificate/hostname verification for THIS run only; "
            "never automatic, never persistent, never used to recover from a "
            "certificate error"
        ),
    )
    ap.add_argument(
        "--print-md",
        action="store_true",
        help="Also print Markdown to stdout after saving",
    )
    args = ap.parse_args(argv)

    if args.from_json:
        try:
            payload = json.loads(args.from_json.read_text("utf-8"))
        except Exception:
            die(f"Could not read JSON: {args.from_json}")
        article = extract_article_from_response(payload)
        origin = article.get("originId") or args.from_json.stem
        out, title = write_article(article, origin)
        print(f"Parsed authorized article: {title}")
        print(f"Saved: {out}")
        if args.print_md:
            print(out.read_text("utf-8"))
        return

    template = load_json(TEMPLATE, None)
    if template is None:
        die(
            f"Missing non-secret template: {TEMPLATE}\n"
            "Copy references/template.example.json or run scripts/build_template.py "
            "on your own ArticleContent capture."
        )
    validate_template(template)
    validate_network_retries(args.network_retries)

    # Validate TLS trust (including any explicit WSJ_CA_BUNDLE) before any
    # network activity, so a broken local trust store costs nothing.
    context = safe_tls_context(insecure=args.insecure)

    if args.url:
        origin_id = resolve_origin_via_browser(args.url)
        print(f"Resolved origin id: {origin_id}")
    else:
        origin_id = normalize_origin_id(args.origin_id)

    payload = fetch_remote(
        template, origin_id, args.allow_once, context, args.network_retries
    )
    article = extract_article_from_response(payload)
    # Prefer server-reported origin id for filename when present
    out, title = write_article(article, article.get("originId") or origin_id)
    print(f"Fetched one authorized article: {title}")
    print(f"Saved: {out}")
    if args.print_md:
        print(out.read_text("utf-8"))


if __name__ == "__main__":
    main()
