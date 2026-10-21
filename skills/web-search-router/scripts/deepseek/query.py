#!/usr/bin/env python3
"""Command-line client for the DeepSeek Search API.

The client uses only the official endpoints, reads the API key from
``DEEPSEEK_API_KEY``, never prints the key, never follows redirects, and keeps
TLS certificate and hostname verification enabled.

Standard library only; no third-party dependencies.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# The base URL is intentionally fixed. There is no flag or environment
# variable that can redirect the bearer token to another origin.
SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
FETCH_URL = "https://api.deepseek.com/v1/tools/fetch"
ENV_VAR = "DEEPSEEK_API_KEY"
USER_AGENT = "deepseek-search-skill/0.1"

DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2
MAX_RETRIES = 5
BASE_RETRY_DELAY = 0.5
MAX_RETRY_DELAY = 8.0
MAX_TOTAL_RETRY_WAIT = 20.0
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

DEFAULT_COUNT = 10
MIN_COUNT = 1
MAX_COUNT = 50
MAX_QUERY_CHARS = 128
MAX_ORIGINAL_QUESTION_CHARS = 128
MAX_FETCH_URL_CHARS = 8192

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_HTTP = 4
EXIT_NETWORK = 5
EXIT_RESPONSE = 6
EXIT_OUTPUT = 7

RETRYABLE_STATUS = frozenset({408, 429})


class CLIError(Exception):
    """A reported failure with a stable, secret-free error record."""

    def __init__(self, code, message, *, exit_code, status=None, retryable=False):
        super().__init__(code)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.status = status
        self.retryable = retryable


class _SafeArgumentParser(argparse.ArgumentParser):
    """Argparse variant that emits one structured, value-free error.

    The default argparse error text can echo user-supplied arguments. That is
    unsafe here because a user might paste a key into the wrong flag, so only a
    fixed message is reported.
    """

    def error(self, message):
        raise CLIError(
            "invalid_arguments",
            "Invalid command line arguments. Run with --help for usage.",
            exit_code=EXIT_USAGE,
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect instead of re-sending a request elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _make_ssl_context():
    """Return a verifying TLS context; verification cannot be disabled."""

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _build_opener():
    return urllib.request.build_opener(
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=_make_ssl_context()),
    )


def _urlopen(request, timeout):
    """Thin seam around urllib so offline tests can replace the transport."""

    return _build_opener().open(request, timeout=timeout)


def _sleep(seconds):
    """Thin seam around time.sleep so retry tests stay offline and fast."""

    time.sleep(seconds)


def _is_retryable_status(status):
    return status in RETRYABLE_STATUS or 500 <= status <= 599


def _read_api_key():
    key = os.environ.get(ENV_VAR)
    if key is None or not key.strip():
        raise CLIError(
            "missing_api_key",
            f"{ENV_VAR} is not set. Create a DeepSeek API key and export it "
            "in the environment; never paste it into chat or commit it.",
            exit_code=EXIT_AUTH,
        )
    # Reject values that cannot be sent safely as an HTTP header without
    # echoing the value anywhere.
    if (
        not key.isascii()
        or any(ch.isspace() or ord(ch) < 0x21 or ord(ch) == 0x7F for ch in key)
    ):
        raise CLIError(
            "invalid_api_key",
            f"{ENV_VAR} contains whitespace, control characters, or "
            "non-ASCII characters and was not sent.",
            exit_code=EXIT_AUTH,
        )
    return key


def _validate_timeout(value):
    if not math.isfinite(value) or value <= 0:
        raise CLIError(
            "invalid_timeout",
            "--timeout must be a positive, finite number of seconds.",
            exit_code=EXIT_USAGE,
        )


def _validate_retries(value):
    if value < 0 or value > MAX_RETRIES:
        raise CLIError(
            "invalid_retries",
            f"--retries must be between 0 and {MAX_RETRIES}.",
            exit_code=EXIT_USAGE,
        )


def _validate_text(value, label, max_chars, *, non_empty=True):
    if not isinstance(value, str):
        raise CLIError(
            "invalid_argument", f"{label} must be a string.", exit_code=EXIT_USAGE
        )
    if non_empty and not value.strip():
        raise CLIError(
            "invalid_argument", f"{label} must not be empty.", exit_code=EXIT_USAGE
        )
    if len(value) > max_chars:
        raise CLIError(
            "invalid_argument",
            f"{label} must be at most {max_chars} Unicode characters.",
            exit_code=EXIT_USAGE,
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise CLIError(
            "invalid_argument",
            f"{label} is not valid UTF-8 text.",
            exit_code=EXIT_USAGE,
        ) from None
    return value


def _validate_count(value):
    if value < MIN_COUNT or value > MAX_COUNT:
        raise CLIError(
            "invalid_count",
            f"--count must be between {MIN_COUNT} and {MAX_COUNT}.",
            exit_code=EXIT_USAGE,
        )
    return value


def _validate_localization(value):
    if value is None:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise CLIError(
            "invalid_localization",
            "--localization must be a valid IPv4 or IPv6 address.",
            exit_code=EXIT_USAGE,
        ) from None


def _validate_fetch_url(value):
    if not isinstance(value, str):
        raise CLIError(
            "invalid_fetch_url", "URL must be a string.", exit_code=EXIT_USAGE
        )
    if len(value) > MAX_FETCH_URL_CHARS:
        raise CLIError(
            "invalid_fetch_url",
            f"URL must be at most {MAX_FETCH_URL_CHARS} characters.",
            exit_code=EXIT_USAGE,
        )
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise CLIError(
            "invalid_fetch_url",
            "URL must not contain whitespace or control characters.",
            exit_code=EXIT_USAGE,
        )
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        raise CLIError(
            "invalid_fetch_url", "URL could not be parsed.", exit_code=EXIT_USAGE
        ) from None
    if parts.scheme not in ("http", "https"):
        raise CLIError(
            "invalid_fetch_url",
            "URL scheme must be http or https.",
            exit_code=EXIT_USAGE,
        )
    if not parts.netloc or parts.hostname is None:
        raise CLIError(
            "invalid_fetch_url", "URL must include a host.", exit_code=EXIT_USAGE
        )
    if parts.username is not None or parts.password is not None:
        raise CLIError(
            "invalid_fetch_url",
            "URL must not contain embedded credentials.",
            exit_code=EXIT_USAGE,
        )
    try:
        parts.port
    except ValueError:
        raise CLIError(
            "invalid_fetch_url", "URL contains an invalid port.", exit_code=EXIT_USAGE
        ) from None
    return value


def _response_status(response):
    status = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        if getcode is not None:
            status = getcode()
    if not isinstance(status, int) or isinstance(status, bool):
        raise CLIError(
            "invalid_response",
            "DeepSeek API response did not include a valid HTTP status.",
            exit_code=EXIT_RESPONSE,
        )
    return status


def _read_response(response):
    chunks = []
    total = 0
    # read(amt) on http.client may return short reads, so loop until EOF or
    # until the local size cap is exceeded.
    while True:
        chunk = response.read(min(65536, MAX_RESPONSE_BYTES + 1 - total))
        if not isinstance(chunk, (bytes, bytearray, str)):
            raise CLIError(
                "invalid_response",
                "DeepSeek API response body had an unsupported type.",
                exit_code=EXIT_RESPONSE,
            )
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise CLIError(
                "response_too_large",
                "DeepSeek API response exceeded the local size limit.",
                exit_code=EXIT_RESPONSE,
            )
    if not chunks:
        return b""
    if isinstance(chunks[0], str):
        return "".join(chunks)
    return b"".join(chunks)


def _decode_json(raw):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise CLIError(
            "invalid_response",
            "DeepSeek API returned a response that was not valid JSON.",
            exit_code=EXIT_RESPONSE,
        ) from None


def _schema_error():
    raise CLIError(
        "invalid_response",
        "DeepSeek API response did not match the expected schema.",
        exit_code=EXIT_RESPONSE,
    )


def _validate_search_payload(payload):
    if not isinstance(payload, dict):
        _schema_error()
    results = payload.get("results")
    if not isinstance(results, list):
        _schema_error()
    for item in results:
        if not isinstance(item, dict):
            _schema_error()
        url = item.get("url")
        title = item.get("title")
        if not isinstance(url, str) or not url.strip():
            _schema_error()
        if not isinstance(title, str):
            _schema_error()
        try:
            parts = urllib.parse.urlsplit(url)
        except ValueError:
            _schema_error()
        if parts.scheme not in ("http", "https") or not parts.netloc:
            _schema_error()


def _validate_fetch_payload(payload):
    if not isinstance(payload, dict):
        _schema_error()
    if not isinstance(payload.get("title"), str):
        _schema_error()
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        _schema_error()


def _parse_retry_after(headers):
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return max(0, seconds)


def _retry_delay(attempt, headers, waited):
    delay = min(BASE_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
    retry_after = _parse_retry_after(headers)
    if retry_after is not None:
        delay = min(max(float(retry_after), BASE_RETRY_DELAY), MAX_RETRY_DELAY)
    if waited + delay > MAX_TOTAL_RETRY_WAIT:
        return None
    return delay


def _http_error(status):
    if 300 <= status < 400:
        return CLIError(
            "redirect_blocked",
            "DeepSeek API returned an unexpected redirect. Redirects are not "
            "followed, so credentials cannot be forwarded to another origin.",
            status=status,
            exit_code=EXIT_HTTP,
        )
    if status == 400:
        message = (
            "DeepSeek API rejected the request (HTTP 400). Check the query, "
            "count, and optional fields."
        )
    elif status == 401:
        message = (
            "DeepSeek API authentication failed (HTTP 401). Check "
            f"{ENV_VAR} and whether the key is active."
        )
    elif status == 402:
        message = (
            "DeepSeek API reported payment required or insufficient balance "
            "(HTTP 402)."
        )
    elif status == 403:
        message = (
            "DeepSeek API denied the request (HTTP 403). For fetch, this is "
            "usually a security-policy rejection; do not retry it unchanged."
        )
    elif status == 404:
        message = (
            "DeepSeek API returned HTTP 404. For fetch, the URL may be "
            "unavailable or have no extractable Markdown content; for search, "
            "the endpoint may be unavailable."
        )
    elif status == 413:
        message = (
            "DeepSeek API rejected the request as too large (HTTP 413)."
        )
    elif _is_retryable_status(status):
        return CLIError(
            "retry_exhausted",
            f"DeepSeek API still returned HTTP {status} after the configured "
            "retries.",
            status=status,
            retryable=True,
            exit_code=EXIT_NETWORK,
        )
    else:
        message = f"DeepSeek API returned HTTP {status}."
    return CLIError("http_error", message, status=status, exit_code=EXIT_HTTP)


def _is_cert_error(exc):
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    return isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError)


def _tls_error():
    return CLIError(
        "tls_verification_failed",
        "TLS certificate verification failed. The request was not retried and "
        "verification was not disabled; fix local trust or the network path.",
        exit_code=EXIT_NETWORK,
    )


def _network_error(exc, attempts):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, TimeoutError):
        code = "request_timeout"
        message = (
            f"DeepSeek API request timed out after {attempts} attempt(s)."
        )
    elif isinstance(reason, ssl.SSLError):
        code = "tls_error"
        message = (
            f"TLS handshake with DeepSeek failed after {attempts} attempt(s); "
            "certificate verification remains enabled."
        )
    else:
        code = "network_error"
        message = f"Network request to DeepSeek failed after {attempts} attempt(s)."
    return CLIError(
        code, message, retryable=True, exit_code=EXIT_NETWORK
    )


def _request_json(url, body, timeout, retries):
    key = _read_api_key()
    try:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        raise CLIError(
            "invalid_argument",
            "Request text is not valid UTF-8.",
            exit_code=EXIT_USAGE,
        ) from None

    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    # Unredirected: even if a future handler allowed a redirect, the bearer
    # token would not be copied to the new request.
    request.add_unredirected_header("Authorization", f"Bearer {key}")

    attempts = retries + 1
    waited = 0.0
    for attempt in range(attempts):
        try:
            with _urlopen(request, timeout=timeout) as response:
                status = _response_status(response)
                raw = _read_response(response)

            if not 200 <= status < 300:
                if _is_retryable_status(status) and attempt + 1 < attempts:
                    delay = _retry_delay(attempt, None, waited)
                    if delay is not None:
                        _sleep(delay)
                        waited += delay
                        continue
                raise _http_error(status)
            return _decode_json(raw)

        except urllib.error.HTTPError as exc:
            status = exc.code
            headers = exc.headers
            try:
                exc.close()
            except Exception:
                pass
            if _is_retryable_status(status) and attempt + 1 < attempts:
                delay = _retry_delay(attempt, headers, waited)
                if delay is not None:
                    _sleep(delay)
                    waited += delay
                    continue
            raise _http_error(status) from None

        except ssl.SSLCertVerificationError:
            raise _tls_error() from None

        except (
            urllib.error.URLError,
            http.client.HTTPException,
            TimeoutError,
            ConnectionError,
            ssl.SSLError,
            OSError,
        ) as exc:
            if _is_cert_error(exc):
                raise _tls_error() from None
            if attempt + 1 < attempts:
                delay = _retry_delay(attempt, None, waited)
                if delay is not None:
                    _sleep(delay)
                    waited += delay
                    continue
            raise _network_error(exc, attempt + 1) from None

    # The loop either returns or raises; this is a defensive fallback.
    raise CLIError(
        "network_error",
        "Network request to DeepSeek failed.",
        retryable=True,
        exit_code=EXIT_NETWORK,
    )


def _run_search(args):
    _validate_timeout(args.timeout)
    _validate_retries(args.retries)
    _validate_text(args.query, "query", MAX_QUERY_CHARS)
    _validate_count(args.count)
    if args.ori_question is not None:
        _validate_text(
            args.ori_question,
            "--original-question",
            MAX_ORIGINAL_QUESTION_CHARS,
        )
    localization = _validate_localization(args.localization)

    body = {"query": args.query, "count": args.count}
    if args.ori_question is not None:
        body["ori_question"] = args.ori_question
    if localization is not None:
        body["localization"] = localization
    if args.content:
        body["need_content"] = True

    _preflight_output(args.output)
    payload = _request_json(SEARCH_URL, body, args.timeout, args.retries)
    _validate_search_payload(payload)
    return payload


def _run_fetch(args):
    _validate_timeout(args.timeout)
    _validate_retries(args.retries)
    url = _validate_fetch_url(args.url)
    _preflight_output(args.output)
    payload = _request_json(FETCH_URL, {"url": url}, args.timeout, args.retries)
    _validate_fetch_payload(payload)
    return payload


def _preflight_output(output):
    """Fail before a billable request when the output path is unusable."""

    if output is None:
        return
    if os.path.lexists(output):
        raise CLIError(
            "output_exists",
            "Refusing to overwrite an existing output file.",
            exit_code=EXIT_OUTPUT,
        )
    parent = os.path.dirname(os.path.abspath(output))
    if not os.path.isdir(parent):
        raise CLIError(
            "output_error",
            "The output directory does not exist.",
            exit_code=EXIT_OUTPUT,
        )


def _write_output(payload, output):
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    try:
        with open(output, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        raise CLIError(
            "output_exists",
            "Refusing to overwrite an existing output file.",
            exit_code=EXIT_OUTPUT,
        ) from None
    except OSError:
        raise CLIError(
            "output_error",
            "Could not write the requested output file.",
            exit_code=EXIT_OUTPUT,
        ) from None


def _emit_error(exc):
    record = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "retryable": bool(exc.retryable),
        }
    }
    if exc.status is not None:
        record["error"]["status"] = exc.status
    sys.stderr.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stderr.flush()


def _add_common_arguments(parser):
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"per-request timeout in seconds (default: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        metavar="N",
        help=(
            "bounded retries for 408/429/5xx and transient network failures "
            f"(0-{MAX_RETRIES}, default: {DEFAULT_RETRIES})"
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="write JSON to PATH instead of stdout; refuses to overwrite",
    )


def _build_parser():
    parser = _SafeArgumentParser(
        prog="query.py",
        description=(
            "Search the web or fetch a page through the DeepSeek Search API. "
            "Requires DEEPSEEK_API_KEY. Output is JSON on stdout by default."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser(
        "search", help="run one web search", description="Run one DeepSeek web search."
    )
    search.add_argument("query", help="search query (1-128 Unicode characters)")
    search.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        metavar="N",
        help=f"number of results, {MIN_COUNT}-{MAX_COUNT} (default: {DEFAULT_COUNT})",
    )
    search.add_argument(
        "--content",
        action="store_true",
        help="request page content for each result (need_content=true)",
    )
    search.add_argument(
        "--original-question",
        dest="ori_question",
        metavar="TEXT",
        help="optional original user question (1-128 Unicode characters)",
    )
    search.add_argument(
        "--localization",
        metavar="IP",
        help="optional IPv4/IPv6 address used as a location hint",
    )
    _add_common_arguments(search)

    fetch = subparsers.add_parser(
        "fetch",
        help="fetch one page as Markdown",
        description="Fetch one http(s) page through the DeepSeek Search API.",
    )
    fetch.add_argument("url", help="http(s) URL, at most 8192 characters")
    _add_common_arguments(fetch)

    return parser


def main(argv=None):
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "search":
            payload = _run_search(args)
        else:
            payload = _run_fetch(args)
        _write_output(payload, args.output)
    except CLIError as exc:
        _emit_error(exc)
        return exc.exit_code
    except KeyboardInterrupt:
        _emit_error(
            CLIError("interrupted", "Interrupted before completion.", exit_code=130)
        )
        return 130
    except Exception as exc:  # pragma: no cover - defensive
        _emit_error(
            CLIError(
                "internal_error",
                f"Unexpected client failure ({type(exc).__name__}).",
                exit_code=EXIT_INTERNAL,
            )
        )
        return EXIT_INTERNAL
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
