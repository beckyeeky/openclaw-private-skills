#!/usr/bin/env python3
"""Fetch one user-authorized WSJ ArticleContent request conservatively.

Secrets: reads WSJ_DJ_AUTHORIZATION only from the process environment. It never
writes or prints the value. The GraphQL template is non-secret JSON stored in a
user runtime directory, never under the installed skill or Git repository.

Supports:
  --origin-id SB… / WP-WSJ-…
  --url https://www.wsj.com/...   (resolves public articleId / SB… then fetches)
  --from-json path                (offline parse of an already-authorized response)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(os.environ.get("WSJ_READER_HOME", "~/.openclaw/wsj-article-reader")).expanduser()
TEMPLATE = ROOT / "template.json"
STATE = ROOT / "state.json"
ARTICLES = ROOT / "articles"
HOUR_LIMIT, DAY_LIMIT, MIN_GAP = 6, 20, 15 * 60
ENDPOINT_ALLOWED = "https://shared-data.dowjones.io/gateway/graphql"
ORIGIN_RE = re.compile(r"^(?:SB\d{10,}|WP-WSJ[O0-9A-Z-]*-\d+)$", re.I)
SB_IN_TEXT_RE = re.compile(r"\bSB\d{20,}\b")
ARTICLE_ID_JSON_RE = re.compile(r'"articleId"\s*:\s*"(SB\d{10,}|WP-WSJ[^"]+)"')
WSJ_HOST_RE = re.compile(r"(?:^|\.)wsj\.com$", re.I)


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


def record(state: dict, article_id: str, status) -> None:
    # No title, URL, headers, token, query values, or response text.
    state.setdefault("attempts", []).append(
        {"at": iso(), "id": str(article_id)[-12:], "status": status}
    )
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


def resolve_origin_from_url(url: str) -> str:
    """Resolve origin id from a user-supplied WSJ article URL via public HTML markers."""
    url = url.strip()
    if not url.startswith("http"):
        die("URL must start with http(s)://")
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    if not WSJ_HOST_RE.search(host):
        die("URL host is not wsj.com")

    # Try a short list of ordinary browser UAs. Some edges return 401 to
    # non-browser clients; this still only reads public articleId markers.
    user_agents = [
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        ),
    ]
    html = ""
    last_err = None
    for ua in user_agents:
        req = Request(
            url,
            headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=30) as r:
                html = r.read(600_000).decode("utf-8", errors="replace")
            if html:
                break
        except HTTPError as e:
            last_err = e.code
            continue
        except URLError:
            last_err = 0
            continue
    if not html:
        if last_err:
            die(
                f"Could not open article URL (HTTP {last_err}) to resolve origin id. "
                "Pass --origin-id from the WSJ app capture instead."
            )
        die("Network failure while resolving origin id from URL.")

    m = ARTICLE_ID_JSON_RE.search(html)
    if m:
        return normalize_origin_id(m.group(1))
    ms = SB_IN_TEXT_RE.findall(html)
    if ms:
        # Prefer the most frequent SB id
        from collections import Counter

        oid, _ = Counter(ms).most_common(1)[0]
        return normalize_origin_id(oid)
    die(
        "Could not find an origin id in the article page. "
        "Pass --origin-id from the app capture, or refresh the URL."
    )


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


def fetch_remote(template: dict, origin_id: str, allow_once: bool) -> dict:
    if not os.environ.get("WSJ_DJ_AUTHORIZATION"):
        die("WSJ_DJ_AUTHORIZATION is not set.")
    state = load_json(STATE, {"attempts": []})
    allowed(state, allow_once)
    # Intentional small non-deterministic pacing; no retry/polling/burst.
    time.sleep(random.uniform(2, 6))
    url, headers = build_request(template, origin_id)
    try:
        with urlopen(Request(url, headers=headers, method="GET"), timeout=45) as r:
            status, raw = r.status, r.read()
    except HTTPError as e:
        record(state, origin_id, e.code)
        die(f"WSJ returned HTTP {e.code}; stopped without retry.")
    except URLError:
        record(state, origin_id, 0)
        die("Network failure; stopped without retry.")
    record(state, origin_id, status)
    if status != 200:
        die(f"Unexpected HTTP {status}; stopped.")
    # Response may be plain JSON (capture) or compressed by urllib already.
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        die("Response was not JSON; stopped.")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--origin-id",
        help="WSJ origin id (SB… / WP-WSJ-…), from app or public articleId",
    )
    src.add_argument("--url", help="WSJ article URL; resolves origin id then fetches")
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
        "--print-md",
        action="store_true",
        help="Also print Markdown to stdout after saving",
    )
    args = ap.parse_args()

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

    if args.url:
        origin_id = resolve_origin_from_url(args.url)
        print(f"Resolved origin id: {origin_id}")
    else:
        origin_id = normalize_origin_id(args.origin_id)

    payload = fetch_remote(template, origin_id, args.allow_once)
    article = extract_article_from_response(payload)
    # Prefer server-reported origin id for filename when present
    out, title = write_article(article, article.get("originId") or origin_id)
    print(f"Fetched one authorized article: {title}")
    print(f"Saved: {out}")
    if args.print_md:
        print(out.read_text("utf-8"))


if __name__ == "__main__":
    main()
