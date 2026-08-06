#!/usr/bin/env python3
"""Build a non-secret ArticleContent template.json from a captured request.

Accepts either:
  - a directory containing request_header_raw.txt (HTTP Toolkit / similar dump)
  - a raw request-header text file

Writes only endpoint, operation, persisted-query extensions, and non-secret
headers. Never copies Authorization, Cookie, or response bodies.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FORBIDDEN = ("authorization", "cookie", "token", "secret", "password", "x-api-key")
SKIP_HEADERS = {
    "accept-encoding",
    "content-length",
    "priority",
    "connection",
    "host",
    "content-encoding",
}


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def load_header_text(path: Path) -> str:
    if path.is_dir():
        candidate = path / "request_header_raw.txt"
        if not candidate.exists():
            die(f"No request_header_raw.txt in {path}")
        return candidate.read_text("utf-8", errors="replace")
    return path.read_text("utf-8", errors="replace")


def parse_headers(text: str) -> tuple[str, str, dict[str, str]]:
    """Return method, path_or_url, headers (may be HTTP/1.1 or HTTP/2 pseudo)."""
    lines = [ln.strip("\r") for ln in text.splitlines() if ln.strip()]
    if not lines:
        die("Empty request header")
    method, path, headers = "", "", {}
    first = lines[0]
    m = re.match(r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(\S+)", first, re.I)
    if m:
        method, path = m.group(1).upper(), m.group(2)
        body_lines = lines[1:]
    else:
        body_lines = lines
    for ln in body_lines:
        if ln.startswith(":"):
            # HTTP/2 pseudo-header
            if ln.startswith(":method:"):
                method = ln.split(":", 2)[-1].strip().upper()
            elif ln.startswith(":path:"):
                path = ln.split(":", 2)[-1].strip()
            elif ln.startswith(":authority:"):
                headers["host"] = ln.split(":", 2)[-1].strip()
            continue
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        headers[k.strip()] = v.strip()
    if not path:
        die("Could not find request path")
    return method or "GET", path, headers


def build_template(method: str, path: str, headers: dict[str, str]) -> dict:
    if method != "GET":
        die(f"Expected GET ArticleContent, got {method}")
    if path.startswith("http"):
        parsed = urlparse(path)
        path_q = parsed.path + ("?" + parsed.query if parsed.query else "")
        endpoint = f"{parsed.scheme}://{parsed.netloc}{parsed.path.split('?')[0]}"
        if parsed.path.endswith("/graphql") or "/graphql" in parsed.path:
            endpoint = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        qs = parse_qs(parsed.query)
    else:
        # path like /gateway/graphql?…
        endpoint_host = headers.get("host") or "shared-data.dowjones.io"
        qpos = path.find("?")
        pure = path if qpos < 0 else path[:qpos]
        query = "" if qpos < 0 else path[qpos + 1 :]
        endpoint = f"https://{endpoint_host}{pure}"
        qs = parse_qs(query)

    if "shared-data.dowjones.io" not in endpoint or not endpoint.endswith("/graphql"):
        die(f"Refusing non-WSJ GraphQL endpoint: {endpoint}")

    op = qs.get("operationName", [headers.get("x-apollo-operation-name", "")])[0]
    if op != "ArticleContent":
        die(f"Not an ArticleContent capture (operationName={op!r})")

    try:
        extensions = json.loads(qs.get("extensions", ["{}"])[0])
        variables = json.loads(qs.get("variables", ["{}"])[0])
    except json.JSONDecodeError:
        die("Could not parse extensions/variables from query string")

    if "persistedQuery" not in extensions:
        die("Capture missing extensions.persistedQuery")

    clean_headers = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk == "host":
            continue
        if any(f in lk for f in FORBIDDEN):
            continue
        if lk in SKIP_HEADERS:
            continue
        clean_headers[k] = v

    # Ensure Apollo operation headers stay aligned with the hash.
    sha = extensions.get("persistedQuery", {}).get("sha256Hash")
    if sha:
        clean_headers.setdefault("x-apollo-operation-id", sha)
        clean_headers.setdefault("x-apollo-operation-name", "ArticleContent")
        clean_headers.setdefault("x-apollo-operation-type", "query")

    # Force English preference in the example; fetch script also overrides at runtime.
    clean_headers["accept-language"] = "en-US,en;q=0.9"
    clean_headers.setdefault(
        "accept",
        "multipart/mixed;deferSpec=20220824,application/graphql-response+json,application/json",
    )
    clean_headers.setdefault("content-type", "application/json")

    variables_template = {
        "filterByScope": variables.get("filterByScope") or "MOBILE",
        "id": "",
        "idType": variables.get("idType") or "originid",
    }

    return {
        "endpoint": endpoint if endpoint.endswith("/graphql") else "https://shared-data.dowjones.io/gateway/graphql",
        "operation_name": "ArticleContent",
        "query": {
            "extensions": extensions,
            "operationName": "ArticleContent",
            "variables": variables_template,
        },
        "headers": clean_headers,
        "captured_app_version": clean_headers.get("x-app-version")
        or clean_headers.get("apollographql-client-version"),
        "notes": "Non-secret template generated by build_template.py. Authorization is not stored here.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "capture",
        type=Path,
        help="Capture dir (with request_header_raw.txt) or a request-header file",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: ~/.openclaw/wsj-article-reader/template.json)",
    )
    ap.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout instead of writing a file",
    )
    args = ap.parse_args()
    text = load_header_text(args.capture)
    method, path, headers = parse_headers(text)
    template = build_template(method, path, headers)

    if args.stdout:
        json.dump(template, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    out = args.output or Path(
        "~/.openclaw/wsj-article-reader/template.json"
    ).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"Wrote non-secret template: {out}")
    print(f"persistedQuery.sha256Hash={template['query']['extensions']['persistedQuery'].get('sha256Hash')}")
    print(f"app={template.get('captured_app_version')}")


if __name__ == "__main__":
    main()
