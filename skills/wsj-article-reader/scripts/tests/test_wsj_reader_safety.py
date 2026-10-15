#!/usr/bin/env python3
"""Offline regression tests for the WSJ article reader safety patch.

Everything here is local and deterministic: no request is ever sent to WSJ,
Dow Jones, or any authorization endpoint, and no credential value is real.
Transport behaviour is simulated with fakes that keep the real call
constraints (``urlopen`` signature, HTTPError/URLError shapes, return-code
contract of the browser resolver CLI).

Run:
  python3 scripts/tests/test_wsj_reader_safety.py
  python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import ast
import contextlib
import errno
import http.server
import importlib.util
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request

SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL_ROOT / "scripts"
FETCH_PATH = SCRIPTS / "fetch_article.py"
RESOLVER_PATH = SCRIPTS / "resolve_origin_id.py"
PROBE_PATH = SCRIPTS / "probe_metadata.js"
HARNESS_PATH = SCRIPTS / "tests" / "probe_node_harness.js"
FIXTURES = SCRIPTS / "tests" / "fixtures"
EXAMPLE_TEMPLATE = SKILL_ROOT / "references" / "template.example.json"

FAKE_TOKEN = "Bearer FAKE-TOKEN-FOR-TESTS-000"
FAKE_SECRET = "SECRET-LEAK-CANARY"
FAKE_URL_MARKER = "id=WP-WSJ-0001234567"
ARTICLE_ID = "WP-WSJ-0001234567"
OTHER_ARTICLE_ID = "WP-WSJ-0007654321"
ARTICLE_URL = "https://www.wsj.com/articles/a-test-headline-abc123"
REQUESTED_PATH = "/articles/a-test-headline-abc123"


def load_fetch_module(home: Path):
    """Import scripts/fetch_article.py fresh so ROOT points at a temp home."""
    os.environ["WSJ_READER_HOME"] = str(home)
    os.environ.pop("WSJ_CA_BUNDLE", None)
    spec = importlib.util.spec_from_file_location(
        f"fetch_article_under_test_{abs(hash(str(home)))}", FETCH_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_template(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE_TEMPLATE, home / "template.json")


def response_payload(article_id: str = ARTICLE_ID) -> bytes:
    return json.dumps({"data": {"articleContent": sample_article(article_id)}}).encode()


def sample_article(article_id: str = ARTICLE_ID) -> dict:
    def tad(text, decorations=None):
        return {
            "textAndDecorations": {
                "flattened": {"text": text, "decorations": decorations or []}
            }
        }

    return {
        "originId": article_id,
        "sourceUrl": ARTICLE_URL,
        "articleHeadline": tad("A Test Headline"),
        "standFirst": "Short deck",
        "authors": [{"text": "Jane Doe"}],
        "sectionName": "Business",
        "columnName": "Markets",
        "publishedDateTimeUtc": "2026-01-01T00:00:00Z",
        "updatedDateTimeUtc": "2026-01-02T00:00:00Z",
        "articleBody": [
            {
                "__typename": "ParagraphArticleBody",
                "textAndDecorations": {
                    "flattened": {
                        "text": "Hello bold link world",
                        "decorations": [
                            {
                                "decorationType": "BOLD",
                                "startIndex": 6,
                                "decorationLength": 4,
                            },
                            {
                                "decorationType": "LINK",
                                "startIndex": 11,
                                "decorationLength": 4,
                                "decorationMetadata": {"uri": "https://example.com/x"},
                            },
                        ],
                    }
                },
            },
            {
                "__typename": "BlockquoteArticleBody",
                **tad("Quoted line"),
            },
            {
                "__typename": "ImageArticleBody",
                "altText": "Chart",
                "displayVariants": {
                    "defaultVariant": {"combinedUrl": "https://img.example/1.jpg"}
                },
                "richTextCaption": tad("A caption"),
                "formattedCredit": "Photo: Example",
            },
            {"__typename": "NewsletterInsetArticleBody"},
            {
                "__typename": "AudioArticleBody",
                "content": {
                    "headline": {"text": "Pod title"},
                    "linkUrl": "https://pod.example/1",
                    "podcastName": "WSJ Podcasts",
                },
            },
            {"__typename": "TaglineArticleBody", **tad("Write to jane@example.com")},
        ],
    }


class FakeResponse:
    """Minimal urlopen-compatible context manager."""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self, *_args, **_kwargs) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def fake_urlopen_factory(recorded: list, body: bytes | None = None, status: int = 200):
    def _urlopen(req, timeout=None, context=None, **_kwargs):
        recorded.append({"url": req.full_url, "headers": dict(req.headers), "context": context})
        if status != 200:
            raise _http_error(req.full_url, status)
        return FakeResponse(body if body is not None else response_payload())

    return _urlopen


def _http_error(url: str, code: int, reason: str = "denied"):
    from urllib.error import HTTPError

    return HTTPError(url, code, reason, {}, io.BytesIO(b""))


def cert_error() -> ssl.SSLCertVerificationError:
    return ssl.SSLCertVerificationError(
        1, f"certificate verify failed: unable to get local issuer ({FAKE_SECRET})"
    )


def fake_resolver(rc: int = 0, stdout: str = "", stderr: str = ""):
    def _run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["resolver"], returncode=rc, stdout=stdout, stderr=stderr)

    return _run


def fail_run(fn, *args, **kwargs):
    """Run ``fn`` expecting ``die()``; return (exit_code, captured_stderr)."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            return exc.code, buf.getvalue()
    raise AssertionError(f"expected SystemExit from {fn!r}, none raised")


class TlsContextTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)

    def test_default_environment_keeps_full_verification(self):
        ctx = self.mod.safe_tls_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreater(ctx.cert_store_stats().get("x509_ca", 0), 0)

    def test_additional_bundle_is_appended_and_verification_survives(self):
        before = ssl.create_default_context().cert_store_stats()["x509"]
        os.environ["WSJ_CA_BUNDLE"] = "/etc/ssl/certs/ca-certificates.crt"
        try:
            ctx = self.mod.safe_tls_context()
        finally:
            os.environ.pop("WSJ_CA_BUNDLE", None)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        # Substitution is the failure mode we must avoid: system CAs stay loaded.
        self.assertGreaterEqual(ctx.cert_store_stats()["x509"], before)

    @unittest.skipUnless(shutil.which("openssl"), "openssl not available")
    def test_self_signed_local_ca_is_accepted(self):
        pem = self.home / "local-extra-ca.pem"
        res = subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(self.home / "k.pem"), "-out", str(pem),
                "-days", "1", "-subj", "/CN=wsj-reader-test-ca",
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            self.skipTest(f"openssl key generation unavailable: {res.stderr.strip()[:80]}")
        os.environ["WSJ_CA_BUNDLE"] = str(pem)
        try:
            ctx = self.mod.safe_tls_context()
        finally:
            os.environ.pop("WSJ_CA_BUNDLE", None)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def _assert_precheck_fails(self, path: str):
        os.environ["WSJ_CA_BUNDLE"] = path
        try:
            code, err = fail_run(self.mod.safe_tls_context)
        finally:
            os.environ.pop("WSJ_CA_BUNDLE", None)
        self.assertEqual(code, 1)
        self.assertIn("WSJ_CA_BUNDLE", err)
        return err

    def test_missing_bundle_file_fails(self):
        self._assert_precheck_fails(str(self.home / "does-not-exist.pem"))

    def test_directory_bundle_fails(self):
        self._assert_precheck_fails(str(self.home))

    def test_empty_zero_byte_bundle_fails(self):
        empty = self.home / "loon_ca.pem"
        empty.write_bytes(b"")
        msg = self._assert_precheck_fails(str(empty))
        self.assertIn("empty (0 bytes)", msg)

    def test_truncated_pem_bundle_fails(self):
        broken = self.home / "broken.pem"
        broken.write_text("-----BEGIN CERTIFICATE-----\nnot base64\n")
        self._assert_precheck_fails(str(broken))

    def test_binary_der_bundle_fails(self):
        der = self.home / "der.bin"
        der.write_bytes(bytes(range(256)))
        msg = self._assert_precheck_fails(str(der))
        self.assertIn("not a PEM certificate bundle", msg)

    def test_garbage_pem_block_fails(self):
        fake = self.home / "garbage.pem"
        fake.write_text(
            "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
        )
        self._assert_precheck_fails(str(fake))

    def test_precheck_error_never_contains_token_or_url(self):
        os.environ["WSJ_DJ_AUTHORIZATION"] = FAKE_TOKEN
        empty = self.home / "loon_ca.pem"
        empty.write_bytes(b"")
        msg = self._assert_precheck_fails(str(empty))
        self.assertNotIn(FAKE_TOKEN, msg)
        self.assertNotIn("shared-data.dowjones.io", msg)
        self.assertNotIn("Authorization", msg)
        os.environ.pop("WSJ_DJ_AUTHORIZATION", None)

    def test_invalid_bundle_fails_before_any_request(self):
        write_template(self.home)
        os.environ["WSJ_DJ_AUTHORIZATION"] = FAKE_TOKEN
        empty = self.home / "loon_ca.pem"
        empty.write_bytes(b"")
        os.environ["WSJ_CA_BUNDLE"] = str(empty)
        network_calls = []

        def _boom(*_a, **_k):
            network_calls.append(1)
            raise AssertionError("network must not be reached with an invalid CA bundle")

        try:
            with mock.patch.object(self.mod, "urlopen", _boom), mock.patch.object(
                self.mod.subprocess, "run", _boom
            ):
                fail_run(self.mod.main, ["--url", ARTICLE_URL])
        finally:
            os.environ.pop("WSJ_CA_BUNDLE", None)
            os.environ.pop("WSJ_DJ_AUTHORIZATION", None)
        self.assertEqual(network_calls, [])
        self.assertFalse((self.home / "state.json").exists())

    def test_source_never_disables_verification_outside_the_opt_in_path(self):
        tree = ast.parse(FETCH_PATH.read_text("utf-8"))
        insecure_fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "explicit_insecure_context"
        )
        low, high = insecure_fn.lineno, max(n.lineno for n in ast.walk(insecure_fn) if hasattr(n, "lineno"))
        banned_attrs = {"CERT_NONE", "CERT_OPTIONAL", "_create_unverified_context"}
        for node in ast.walk(tree):
            in_opt_in = low <= getattr(node, "lineno", -1) <= high
            if isinstance(node, ast.Attribute) and node.attr in banned_attrs:
                self.assertTrue(
                    in_opt_in, f"{node.attr} must only appear in explicit_insecure_context"
                )
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in {
                        "verify_mode",
                        "check_hostname",
                    }:
                        self.assertTrue(
                            in_opt_in,
                            f"assigning {target.attr} is only allowed in explicit_insecure_context",
                        )
        called = self._called_names(tree)
        self.assertIn("create_default_context", called)
        self.assertIn("load_verify_locations", called)

    @staticmethod
    def _called_names(tree) -> set:
        names = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        names |= {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        return names

    def test_opt_in_context_is_reachable_only_from_the_flag(self):
        tree = ast.parse(FETCH_PATH.read_text("utf-8"))
        insecure_fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "explicit_insecure_context"
        )
        low = insecure_fn.lineno
        high = max(n.lineno for n in ast.walk(insecure_fn) if hasattr(n, "lineno"))
        references = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and node.id == "explicit_insecure_context"
            and not (low <= node.lineno <= high)
        ]
        self.assertEqual(
            len(references), 1, "explicit_insecure_context may be called from exactly one place"
        )
        safe_fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "safe_tls_context"
        )
        self.assertLessEqual(safe_fn.lineno, references[0])
        self.assertLessEqual(
            references[0],
            max(n.lineno for n in ast.walk(safe_fn) if hasattr(n, "lineno")),
        )

    def test_no_environment_variable_can_change_verification(self):
        tree = ast.parse(FETCH_PATH.read_text("utf-8"))
        literals = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"get", "__getitem__"}:
                continue
            owner = node.func.value
            if not (isinstance(owner, ast.Attribute) and owner.attr == "environ"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literals.add(arg.value)
        # Only the runtime-root and the token may come from the environment; the
        # second literal is the documented default runtime root.
        self.assertEqual(
            literals,
            {"WSJ_READER_HOME", "WSJ_DJ_AUTHORIZATION", "~/.openclaw/wsj-article-reader"},
        )


class NetworkDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)

    def test_certificate_verification_error_is_untrusted_category(self):
        err = self.mod.classify_network_error(cert_error())
        self.assertEqual(err[0], "tls_certificate_untrusted")

    def test_generic_ssl_error_is_handshake_category(self):
        tag, message = self.mod.classify_network_error(ssl.SSLError("handshake failure"))
        self.assertEqual(tag, "tls_handshake_failed")
        self.assertIn("tls_handshake_failed", message)

    def test_timeout_is_its_own_category(self):
        from urllib.error import URLError

        tag, _ = self.mod.classify_network_error(URLError(TimeoutError("timed out")))
        self.assertEqual(tag, "network_timeout")

    def test_none_tls_failure_is_network_error(self):
        import socket
        from urllib.error import URLError

        tag, _ = self.mod.classify_network_error(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertEqual(tag, "network_error")

    def test_diagnostics_are_fixed_text_without_secrets(self):
        from urllib.error import URLError

        cases = [
            cert_error(),
            URLError(cert_error()),
            URLError(ssl.SSLError(f"tlsv1 alert {FAKE_SECRET}")),
            URLError(TimeoutError(FAKE_SECRET)),
            URLError(OSError(FAKE_SECRET)),
            OSError(FAKE_SECRET),
        ]
        for exc in cases:
            tag, message = self.mod.classify_network_error(exc)
            self.assertIn(tag, self.mod.NETWORK_MESSAGES)
            self.assertIs(message, self.mod.NETWORK_MESSAGES[tag])
            for leak in (FAKE_SECRET, FAKE_TOKEN, "http://", "https://", "?", "Authorization"):
                self.assertNotIn(leak, message, f"{tag} leaked {leak}")


class FetcherErrorPathTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)
        write_template(self.home)
        os.environ["WSJ_DJ_AUTHORIZATION"] = FAKE_TOKEN
        self.addCleanup(os.environ.pop, "WSJ_DJ_AUTHORIZATION", None)
        sleeper = mock.patch.object(self.mod.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _run(self, expect_code=1):
        code, err = fail_run(self.mod.main, ["--origin-id", ARTICLE_ID, "--allow-once"])
        self.assertEqual(code, expect_code)
        return err

    def test_401_stops_immediately_without_retry(self):
        err = _http_error("https://example.invalid", 401)
        with mock.patch.object(self.mod, "urlopen", side_effect=err) as urlopen:
            message = self._run()
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("401", message)
        self.assertNotIn(FAKE_TOKEN, message)
        state = json.loads((self.home / "state.json").read_text())
        self.assertEqual(state["attempts"][-1]["status"], 401)
        self.assertNotIn(ARTICLE_ID, json.dumps(state))

    def test_403_and_429_stop_immediately_without_retry(self):
        for code in (403, 429):
            with self.subTest(code=code):
                err = _http_error("https://example.invalid", code)
                with mock.patch.object(self.mod, "urlopen", side_effect=err) as urlopen:
                    message = self._run()
                self.assertEqual(urlopen.call_count, 1)
                self.assertIn(str(code), message)

    def test_server_error_still_stops_without_retry(self):
        err = _http_error("https://example.invalid", 500)
        with mock.patch.object(self.mod, "urlopen", side_effect=err) as urlopen:
            self._run()
        self.assertEqual(urlopen.call_count, 1)

    def test_tls_failure_is_classified_recorded_and_redacted(self):
        from urllib.error import URLError

        with mock.patch.object(self.mod, "urlopen", side_effect=URLError(cert_error())) as urlopen:
            message = self._run()
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("tls_certificate_untrusted", message)
        self.assertIn("No automatic retry was performed.", message)
        for leak in (FAKE_SECRET, FAKE_TOKEN, "shared-data.dowjones.io", "Authorization", "?"):
            self.assertNotIn(leak, message)
        state = json.loads((self.home / "state.json").read_text())
        self.assertEqual(state["attempts"][-1]["status"], "tls_certificate_untrusted")

    def test_request_uses_context_and_keeps_token_out_of_url(self):
        recorded = []
        with mock.patch.object(self.mod, "urlopen", fake_urlopen_factory(recorded)):
            self.mod.main(["--origin-id", ARTICLE_ID, "--allow-once"])
        self.assertEqual(len(recorded), 1)
        call = recorded[0]
        decoded = unquote(call["url"])
        self.assertIn(f'\"id\":\"{ARTICLE_ID}\"', decoded)
        self.assertIn('\"idType\":\"originid\"', decoded)
        self.assertNotIn(FAKE_TOKEN, call["url"])
        self.assertNotIn("Authorization", call["url"])
        headers = {k.lower(): v for k, v in call["headers"].items()}
        self.assertEqual(headers.get("authorization"), FAKE_TOKEN)
        self.assertIsNotNone(call["context"])
        self.assertEqual(call["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(call["context"].check_hostname)


class OfflineBodyRegressionTests(unittest.TestCase):
    """Existing body/markdown capability must keep working without network."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)
        os.environ.pop("WSJ_DJ_AUTHORIZATION", None)

    def test_from_json_still_builds_full_markdown(self):
        src = self.home / "response.json"
        src.write_bytes(response_payload())
        self.mod.main(["--from-json", str(src)])
        out = self.home / "articles" / f"{ARTICLE_ID}.md"
        self.assertTrue(out.exists())
        text = out.read_text("utf-8")
        self.assertTrue(text.startswith("# A Test Headline"))
        self.assertIn(f"- URL: {ARTICLE_URL}", text)
        self.assertIn("- Author: Jane Doe", text)
        self.assertIn("- Section: Business / Markets", text)
        self.assertIn(f"- Origin ID: {ARTICLE_ID}", text)
        self.assertIn("> Short deck", text)
        self.assertIn("Hello **bold** [link](https://example.com/x) world", text)
        self.assertIn("> Quoted line", text)
        self.assertIn("![Chart](https://img.example/1.jpg)", text)
        self.assertIn("A caption (Photo: Example)", text)
        self.assertIn("*Write to jane@example.com*", text)
        self.assertIn("🎧 [WSJ Podcasts: Pod title](https://pod.example/1)", text)
        self.assertNotIn("NewsletterInset", text)

    def test_from_json_needs_no_token_and_no_network(self):
        src = self.home / "response.json"
        src.write_bytes(response_payload(OTHER_ARTICLE_ID))
        with mock.patch.object(self.mod, "urlopen") as urlopen:
            self.mod.main(["--from-json", str(src)])
        urlopen.assert_not_called()
        self.assertTrue((self.home / "articles" / f"{OTHER_ARTICLE_ID}.md").exists())

    def test_from_json_empty_article_is_reported(self):
        src = self.home / "response.json"
        src.write_text(json.dumps({"data": {"articleContent": None}}))
        code, err = fail_run(self.mod.main, ["--from-json", str(src)])
        self.assertEqual(code, 1)
        self.assertIn("entitled", err)


class UrlResolutionTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)
        write_template(self.home)
        os.environ["WSJ_DJ_AUTHORIZATION"] = FAKE_TOKEN
        self.addCleanup(os.environ.pop, "WSJ_DJ_AUTHORIZATION", None)
        sleeper = mock.patch.object(self.mod.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _resolver_env(self):
        env = dict(os.environ)
        env["PATH"] = ""
        env.pop("WSJ_DJ_AUTHORIZATION", None)
        return env

    def test_webview_url_needs_no_browser(self):
        url = f"https://www.wsj.com/webview/{ARTICLE_ID}/example"
        proc = subprocess.run(
            [sys.executable, str(RESOLVER_PATH), url],
            capture_output=True,
            text=True,
            env=self._resolver_env(),
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), ARTICLE_ID)

    def test_browser_unavailable_is_an_explicit_error(self):
        proc = subprocess.run(
            [sys.executable, str(RESOLVER_PATH), ARTICLE_URL],
            capture_output=True,
            text=True,
            env=self._resolver_env(),
            timeout=60,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Resolution failed", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn(FAKE_SECRET, proc.stderr)

    def test_browser_unavailable_stops_the_fetch(self):
        with mock.patch.dict(os.environ, {"PATH": ""}):
            with mock.patch.object(self.mod, "urlopen") as urlopen:
                code, message = fail_run(
                    self.mod.main, ["--url", ARTICLE_URL, "--allow-once"]
                )
        self.assertEqual(code, 1)
        urlopen.assert_not_called()
        self.assertIn("Could not resolve an origin id from public metadata", message)
        self.assertIn("No authorized request was sent.", message)

    def test_browser_step_never_receives_the_token(self):
        seen = {}

        def _run(cmd, capture_output=True, text=True, timeout=None, env=None):
            seen["env"] = env or {}
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{ARTICLE_ID}\n", stderr="")

        recorded = []
        with mock.patch.object(self.mod.subprocess, "run", _run), mock.patch.object(
            self.mod, "urlopen", fake_urlopen_factory(recorded)
        ):
            self.mod.main(["--url", ARTICLE_URL, "--allow-once"])
        self.assertNotIn("WSJ_DJ_AUTHORIZATION", seen["env"])
        self.assertEqual(seen["cmd"][-1], ARTICLE_URL)
        self.assertIn(ARTICLE_ID, unquote(recorded[0]["url"]))

    def test_resolver_failure_output_is_surfaced(self):
        with mock.patch.object(
            self.mod.subprocess,
            "run",
            fake_resolver(1, stderr="Resolution failed: No readable article metadata\n"),
        ), mock.patch.object(self.mod, "urlopen") as urlopen:
            code, message = fail_run(
                self.mod.main, ["--url", ARTICLE_URL, "--allow-once"]
            )
        self.assertEqual(code, 1)
        urlopen.assert_not_called()
        self.assertIn("No readable article metadata", message)
        self.assertIn("Related/recommended-story ids are deliberately not used", message)

    def test_non_wsj_host_is_refused_before_the_browser_starts(self):
        with mock.patch.object(self.mod.subprocess, "run") as runner:
            code, message = fail_run(
                self.mod.resolve_origin_via_browser, "https://example.com/articles/x"
            )
        self.assertEqual(code, 1)
        runner.assert_not_called()
        self.assertIn("not wsj.com", message)

    # The former `--metadata-json` fixtures here described the removed
    # "collect every articleId in the page, then require exactly one" contract.
    # Their four behaviours (accept the current article, reject a related-story
    # id, reject a path mismatch, reject non-article ids) are now covered, with
    # the real JavaScript executed offline, by
    # BrowserMetadataAttributionTests above/below.

    def test_resolver_rejects_non_wsj_urls(self):
        proc = subprocess.run(
            [sys.executable, str(RESOLVER_PATH), "https://example.com/articles/x"],
            capture_output=True,
            text=True,
            env=self._resolver_env(),
            timeout=60,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Expected an HTTPS WSJ URL", proc.stderr)

    def test_fetch_module_exposes_no_html_scraping_resolver(self):
        source = FETCH_PATH.read_text("utf-8")
        self.assertNotIn("resolve_origin_from_url", source)
        self.assertNotIn("user_agents", source)
        self.assertIn("resolve_origin_via_browser", source)


class InsecureOptInTests(unittest.TestCase):
    """--insecure is explicit-only; the safe default is never downgraded."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)
        write_template(self.home)
        os.environ["WSJ_DJ_AUTHORIZATION"] = FAKE_TOKEN
        self.addCleanup(os.environ.pop, "WSJ_DJ_AUTHORIZATION", None)
        sleeper = mock.patch.object(self.mod.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _run_recorded(self, extra_args):
        recorded = []
        with mock.patch.object(self.mod, "urlopen", fake_urlopen_factory(recorded)):
            self.mod.main(["--origin-id", ARTICLE_ID, "--allow-once", *extra_args])
        return recorded

    def test_default_run_still_verifies_certificates(self):
        recorded = self._run_recorded([])
        ctx = recorded[0]["context"]
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.cert_store_stats().get("x509_ca", 0) > 0, True)

    def test_environment_variables_cannot_enable_insecure(self):
        with mock.patch.dict(
            os.environ,
            {"WSJ_INSECURE": "1", "WSJ_READER_INSECURE": "1", "SSL_VERIFY": "0"},
        ):
            recorded = self._run_recorded([])
        ctx = recorded[0]["context"]
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        reported = json.loads((self.home / "state.json").read_text())
        self.assertEqual(len(reported["attempts"]), 1)

    def test_insecure_flag_is_required_and_warns_without_secrets(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            recorded = self._run_recorded(["--insecure"])
        ctx = recorded[0]["context"]
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertFalse(ctx.check_hostname)
        self.assertEqual(len(recorded), 1)
        warning = err.getvalue()
        self.assertIn("--insecure", warning)
        self.assertIn("DISABLED", warning)
        self.assertIn("never automatic", warning)
        for leak in (FAKE_TOKEN, "Authorization", "shared-data.dowjones.io", ARTICLE_ID):
            self.assertNotIn(leak, warning)

    def test_certificate_failure_never_downgrades_or_retries(self):
        from urllib.error import URLError

        with mock.patch.object(
            self.mod, "urlopen", side_effect=URLError(cert_error())
        ) as urlopen:
            code, err = fail_run(
                self.mod.main,
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "2"],
            )
        self.assertEqual(code, 1)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(
            urlopen.call_args.kwargs["context"].verify_mode, ssl.CERT_REQUIRED
        )
        self.assertIn("tls_certificate_untrusted", err)
        self.assertIn("No automatic retry was performed.", err)


class NetworkRetryTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)
        write_template(self.home)
        os.environ["WSJ_DJ_AUTHORIZATION"] = FAKE_TOKEN
        self.addCleanup(os.environ.pop, "WSJ_DJ_AUTHORIZATION", None)
        sleeper = mock.patch.object(self.mod.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _seed_state(self, count: int) -> None:
        attempts = [
            {"at": self.mod.iso(), "id": "seed", "status": 200} for _ in range(count)
        ]
        (self.home / "state.json").write_text(json.dumps({"attempts": attempts}))

    def _run(self, side_effect, extra_args, expect_code=1):
        with mock.patch.object(self.mod, "urlopen", side_effect=side_effect) as urlopen:
            code, err = fail_run(
                self.mod.main,
                ["--origin-id", ARTICLE_ID, "--allow-once", *extra_args],
            )
        self.assertEqual(code, expect_code)
        return code, err, urlopen

    def test_retries_are_off_by_default_and_capped_at_two(self):
        self.assertEqual(self.mod.MAX_NETWORK_RETRIES, 2)
        reset = URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        _, err, urlopen = self._run([reset, reset, reset], [])
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("No automatic retry was performed.", err)

    def test_out_of_range_retries_rejected_before_any_request(self):
        for value in ("-1", "3", "99"):
            with self.subTest(value=value):
                with mock.patch.object(self.mod, "urlopen") as urlopen:
                    code, err = fail_run(
                        self.mod.main,
                        ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", value],
                    )
                self.assertEqual(code, 1)
                urlopen.assert_not_called()
                self.assertIn("--network-retries", err)
        with mock.patch.object(self.mod, "urlopen") as urlopen:
            code, err = fail_run(
                self.mod.main,
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "-1"],
            )
        self.assertEqual(code, 1)
        urlopen.assert_not_called()
        self.assertIn("no request was sent", err)
        self.assertFalse((self.home / "state.json").exists())

    def test_connection_reset_is_retried_then_succeeds(self):
        reset = URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        ok = FakeResponse(response_payload())
        with mock.patch.object(self.mod, "urlopen", side_effect=[reset, ok]) as urlopen:
            self.mod.main(
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "1"]
            )
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(
            urlopen.call_args_list[-1].kwargs["context"].verify_mode, ssl.CERT_REQUIRED
        )
        state = json.loads((self.home / "state.json").read_text())
        self.assertEqual([a["status"] for a in state["attempts"]], ["network_error", 200])
        self.assertTrue((self.home / "articles" / f"{ARTICLE_ID}.md").exists())

    def test_connect_timeout_and_temporary_dns_are_retried(self):
        import socket

        for exc in (
            URLError(TimeoutError("connect timed out")),
            URLError(socket.gaierror(-3, "Temporary failure in name resolution")),
        ):
            with self.subTest(exc=type(getattr(exc, "reason", exc)).__name__):
                ok = FakeResponse(response_payload())
                with mock.patch.object(self.mod, "urlopen", side_effect=[exc, ok]) as urlopen:
                    self.mod.main(
                        ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "1"]
                    )
                self.assertEqual(urlopen.call_count, 2)

    def test_permanent_dns_failure_is_not_retried(self):
        import socket

        exc = URLError(socket.gaierror(-2, "Name or service not known"))
        _, err, urlopen = self._run([exc, exc], ["--network-retries", "2"])
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("network_error", err)

    def test_tls_failures_are_never_retried(self):
        for exc in (cert_error(), URLError(ssl.SSLError("handshake failure"))):
            with self.subTest(kind=type(exc).__name__):
                _, err, urlopen = self._run([exc, exc], ["--network-retries", "2"])
                self.assertEqual(urlopen.call_count, 1)
                self.assertIn("tls_", err)
                self.assertIn("No automatic retry was performed.", err)

    def test_http_errors_are_never_retried(self):
        for code in (401, 403, 429, 500, 503):
            with self.subTest(code=code):
                exc = _http_error("https://example.invalid", code)
                _, err, urlopen = self._run([exc], ["--network-retries", "2"])
                self.assertEqual(urlopen.call_count, 1)
                self.assertIn(str(code), err)

    def test_exhausted_retry_budget_stops_with_a_bounded_note(self):
        reset = URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        _, err, urlopen = self._run([reset, reset, reset, reset], ["--network-retries", "1"])
        self.assertEqual(urlopen.call_count, 2)
        self.assertIn("attempts were made in this run under --network-retries=1", err)
        self.assertNotIn("No automatic retry was performed.", err)
        state = json.loads((self.home / "state.json").read_text())
        self.assertEqual(len(state["attempts"]), 2)

    def test_every_attempt_counts_against_the_hourly_limit(self):
        self._seed_state(6)
        reset = URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        with mock.patch.object(self.mod, "urlopen") as urlopen:
            code, err = fail_run(
                self.mod.main,
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "2"],
            )
        self.assertEqual(code, 1)
        urlopen.assert_not_called()
        self.assertIn("hourly limit", err)

    def test_retry_budget_is_limited_by_the_hourly_limit(self):
        self._seed_state(5)
        reset = URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        _, err, urlopen = self._run([reset, reset, reset], ["--network-retries", "2"])
        # 5 pre-existing + 1 attempt = 6 (the cap); the retry is refused, not sent.
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("hourly limit", err)

    def test_cooldown_blocks_the_first_attempt_only(self):
        self._seed_state(1)
        reset = URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        with mock.patch.object(self.mod, "urlopen") as urlopen:
            code, err = fail_run(
                self.mod.main, ["--origin-id", ARTICLE_ID, "--network-retries", "1"]
            )
        self.assertEqual(code, 1)
        urlopen.assert_not_called()
        self.assertIn("cooldown", err)

        with mock.patch.object(
            self.mod, "urlopen", side_effect=[reset, FakeResponse(response_payload())]
        ) as urlopen:
            self.mod.main(
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "1"]
            )
        self.assertEqual(urlopen.call_count, 2)
        self.assertTrue((self.home / "articles" / f"{ARTICLE_ID}.md").exists())

    def test_backoff_is_short_bounded_and_sequential(self):
        reset = URLError(TimeoutError("read timed out"))
        waits = []
        sleeper = mock.patch.object(self.mod.time, "sleep", side_effect=waits.append)
        sleeper.start()
        self.addCleanup(sleeper.stop)
        with mock.patch.object(
            self.mod, "urlopen", side_effect=[reset, reset, FakeResponse(response_payload())]
        ) as urlopen:
            self.mod.main(
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "2"]
            )
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(len(waits), 3)
        self.assertTrue(all(0 < w <= 10 for w in waits), waits)
        self.assertEqual([w for w in waits if w > 0][0], waits[0])


class _RedirectStub:
    """Local HTTP stub used to observe redirect handling. No external traffic.

    ``/start`` answers 302 -> ``/target``; ``/target`` answers 200 with a valid
    ArticleContent body, so a redirect-following client would "succeed" and the
    stub would have received the Authorization header twice.
    """

    def __init__(self):
        self.hits = []  # (path, Authorization header or None)
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802 (http.server API)
                # Query strings are dropped: only the path identifies the route.
                route = self.path.split("?", 1)[0]
                outer.hits.append((route, self.headers.get("Authorization")))
                if route == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/target")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif self.path == "/target":
                    body = response_payload()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def hits_for(self, path: str) -> list:
        return [h for h in self.hits if h[0] == path]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _ReadFailingResponse:
    """urlopen-compatible response whose *body read* fails."""

    def __init__(self, error: BaseException, status: int = 200):
        self.status = status
        self._error = error

    def read(self, *_args, **_kwargs) -> bytes:
        raise self._error

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def load_resolver_module():
    """Import resolve_origin_id.py fresh (main() is __main__-guarded: no side effects)."""
    spec = importlib.util.spec_from_file_location("resolve_origin_id_under_test", RESOLVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline_env(**extra) -> dict:
    """Environment for resolver runs that must not reach a real browser."""
    env = dict(os.environ)
    env.pop("WSJ_DJ_AUTHORIZATION", None)
    env.update(extra)
    return env


@unittest.skipUnless(shutil.which("node"), "node is required to execute the probe offline")
class BrowserMetadataAttributionTests(unittest.TestCase):
    """The origin id may only come from __NEXT_DATA__.props.pageProps.articleData.

    The browser step is played by a test double on the resolver's single
    shell-out seam (``resolve_origin_id.cli``). It captures the script the
    resolver really sends and executes it, with node, against a static page
    fixture (``tests/probe_node_harness.js`` + ``tests/fixtures/*.html``), so the
    JavaScript itself runs offline. The sibling browser process cannot be
    replaced by a fake binary here - the app intercepts any exec named
    ``minis-browser-use``, whatever its path - so that one seam is patched;
    argument parsing, unwrap, attribution validation and the exit status still
    run in the real resolver. Not covered by this harness: real page rendering /
    hydration, CSP behaviour, and anything the live browser does after load.

    The pre-patch code scanned every ``<script>`` with a whole-page regex, so a
    unique related-story ``"articleId"`` was accepted as the current article:
    the red assertions below fail on that code and pass on the patched resolver.
    """

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.resolver = load_resolver_module()

    def _probe_with_node(self, fixture: str, requested_path: str) -> dict:
        script_file = self.home / "sent_script.js"
        out = subprocess.run(
            [
                "node",
                str(HARNESS_PATH),
                str(script_file),
                str(FIXTURES / fixture),
                requested_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return {"ok": True, "result": {"value": json.loads(out.stdout)}}

    def _resolve(self, fixture: str, requested_path: str = REQUESTED_PATH):
        """Run the resolver in-process; the browser call is answered by node."""
        sent = {}
        script_file = self.home / "sent_script.js"

        def fake_cli(action, **kwargs):
            if action == "navigate":
                return {"ok": True, "tab_id": 1, "url": kwargs.get("url")}
            sent["script"] = kwargs.get("script") or ""
            script_file.write_text(sent["script"], "utf-8")
            return self._probe_with_node(fixture, requested_path)

        out_buf, err_buf = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(self.resolver, "cli", fake_cli), mock.patch.object(
            sys, "argv", ["resolve_origin_id.py", ARTICLE_URL]
        ), contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            try:
                self.resolver.main()
            except SystemExit as exc:
                code = exc.code or 0
        return code, out_buf.getvalue().strip(), err_buf.getvalue(), sent.get("script", "")

    def _resolve_with_json(self, payload: dict):
        fixture = self.home / "metadata.json"
        fixture.write_text(json.dumps(payload))
        return subprocess.run(
            [sys.executable, str(RESOLVER_PATH), ARTICLE_URL, "--metadata-json", str(fixture)],
            capture_output=True,
            text=True,
            env=offline_env(),
            timeout=60,
        )

    def test_accepts_the_dedicated_article_object(self):
        code, out, err, sent = self._resolve("article_dedicated.html")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, ARTICLE_ID)
        # The script handed to the browser must read the verified path only.
        self.assertIn("__NEXT_DATA__", sent)
        self.assertIn("pageProps", sent)
        self.assertIn("articleData", sent)
        self.assertNotIn("matchAll", sent)
        self.assertNotIn("querySelectorAll", sent)
        self.assertNotIn("relatedStories", sent)

    def test_accepts_a_tracking_id_when_origin_id_is_absent(self):
        code, out, err, _ = self._resolve("article_tracking_only.html")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, ARTICLE_ID)

    def test_related_story_id_is_never_accepted(self):
        code, out, err, _ = self._resolve("article_with_recommendation.html")
        self.assertNotIn(OTHER_ARTICLE_ID, out)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, ARTICLE_ID)

    def test_page_without_a_dedicated_object_is_refused(self):
        code, out, err, _ = self._resolve("page_without_article_data.html")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertNotIn(OTHER_ARTICLE_ID, out + err)
        self.assertIn("articleData", err)

    def test_source_url_path_mismatch_is_refused(self):
        code, out, err, _ = self._resolve("article_path_mismatch.html")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("does not match", err)

    def test_disagreeing_origin_and_tracking_ids_are_refused(self):
        code, out, err, _ = self._resolve("article_conflicting_ids.html")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("disagree", err)

    def test_probe_output_is_a_supported_offline_fixture(self):
        out = subprocess.run(
            [
                "node",
                str(HARNESS_PATH),
                str(PROBE_PATH),
                str(FIXTURES / "article_dedicated.html"),
                REQUESTED_PATH,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        fixture = self.home / "probe-output.json"
        fixture.write_text(out.stdout)
        proc = subprocess.run(
            [sys.executable, str(RESOLVER_PATH), ARTICLE_URL, "--metadata-json", str(fixture)],
            capture_output=True,
            text=True,
            env=offline_env(),
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), ARTICLE_ID)

    def test_offline_fixture_without_a_dedicated_object_is_refused(self):
        proc = self._resolve_with_json(
            {
                "ok": False,
                "code": "missing_article_data",
                "requestedUrl": ARTICLE_URL,
                "pagePath": REQUESTED_PATH,
            }
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertIn("articleData", proc.stderr)

    def test_offline_fixture_with_disagreeing_ids_is_refused(self):
        proc = self._resolve_with_json(
            {
                "ok": True,
                "hasArticleData": True,
                "requestedUrl": ARTICLE_URL,
                "pagePath": REQUESTED_PATH,
                "originId": ARTICLE_ID,
                "trackingArticleId": OTHER_ARTICLE_ID,
                "sourceUrl": ARTICLE_URL,
                "canonicalUrl": ARTICLE_URL,
            }
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertIn("disagree", proc.stderr)

    def test_offline_fixture_with_a_non_article_id_is_refused(self):
        for bad in ("12345", "related-story-slug", "WP-WSJ-", ""):
            with self.subTest(origin_id=bad):
                proc = self._resolve_with_json(
                    {
                        "ok": True,
                        "hasArticleData": True,
                        "requestedUrl": ARTICLE_URL,
                        "pagePath": REQUESTED_PATH,
                        "originId": bad,
                        "trackingArticleId": None,
                        "sourceUrl": ARTICLE_URL,
                        "canonicalUrl": ARTICLE_URL,
                    }
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(proc.stdout.strip(), "")

    def test_offline_fixture_without_any_path_field_is_refused(self):
        proc = self._resolve_with_json(
            {
                "ok": True,
                "hasArticleData": True,
                "requestedUrl": ARTICLE_URL,
                "pagePath": REQUESTED_PATH,
                "originId": ARTICLE_ID,
                "trackingArticleId": None,
                "sourceUrl": None,
                "canonicalUrl": None,
            }
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")


class RedirectRefusalTests(unittest.TestCase):
    """The authorized request must refuse every redirect and send no second request.

    Pre-patch evidence (same stub): urllib's default ``HTTPRedirectHandler``
    re-sent the request - including the ``Authorization`` header - to
    ``/target``, so the token reached a second, redirect-chosen path.
    """

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)
        self.stub = _RedirectStub()
        self.addCleanup(self.stub.close)
        os.environ["WSJ_DJ_AUTHORIZATION"] = FAKE_TOKEN
        self.addCleanup(os.environ.pop, "WSJ_DJ_AUTHORIZATION", None)
        sleeper = mock.patch.object(self.mod.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.endpoint = self.stub.url("/start")
        template = json.loads(EXAMPLE_TEMPLATE.read_text("utf-8"))
        template["endpoint"] = self.endpoint
        (self.home / "template.json").write_text(json.dumps(template))

    def test_redirect_is_refused_and_the_target_is_never_contacted(self):
        with mock.patch.object(self.mod, "ENDPOINT_ALLOWED", self.endpoint):
            code, err = fail_run(
                self.mod.main,
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "2"],
            )
        self.assertEqual(code, 1)
        # Exactly one request, to the configured endpoint only.
        self.assertEqual(len(self.stub.hits_for("/start")), 1)
        self.assertEqual(self.stub.hits_for("/target"), [])
        self.assertEqual({h[1] for h in self.stub.hits}, {FAKE_TOKEN})
        self.assertIn("redirect", err.lower())
        self.assertIn("never re-sent", err)
        for leak in (FAKE_TOKEN, "127.0.0.1", "Authorization", "?"):
            self.assertNotIn(leak, err)
        state = json.loads((self.home / "state.json").read_text())
        self.assertEqual([a["status"] for a in state["attempts"]], [302])
        self.assertNotIn(FAKE_TOKEN, json.dumps(state))
        self.assertFalse((self.home / "articles").exists())

    def test_module_urlopen_raises_instead_of_following(self):
        with self.assertRaises(HTTPError) as caught:
            self.mod.urlopen(
                Request(self.endpoint, headers={"Authorization": FAKE_TOKEN}, method="GET"),
                timeout=10,
                context=None,
            )
        self.assertEqual(caught.exception.code, 302)
        self.assertEqual(len(self.stub.hits_for("/start")), 1)
        self.assertEqual(self.stub.hits_for("/target"), [])


class TwoPhaseTransportRetryTests(unittest.TestCase):
    """--network-retries covers the connect phase and the body-read phase.

    Both phases are retried only for the idempotent ``GET``, only for transient
    timeout/reset/truncation faults, and each real attempt is recorded with its
    phase. Pre-patch the body-read phase either had no phase accounting
    (``phase`` missing) or crashed outright on a truncated body
    (``IncompleteRead`` escaped ``main`` as an unhandled traceback).
    """

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_fetch_module(self.home)
        write_template(self.home)
        os.environ["WSJ_DJ_AUTHORIZATION"] = FAKE_TOKEN
        self.addCleanup(os.environ.pop, "WSJ_DJ_AUTHORIZATION", None)
        sleeper = mock.patch.object(self.mod.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _state(self) -> dict:
        return json.loads((self.home / "state.json").read_text())

    def test_retries_are_restricted_to_the_idempotent_get(self):
        self.assertEqual(set(self.mod.RETRY_METHODS), {"GET"})

    def test_body_read_interruption_is_retried_then_succeeds(self):
        from http.client import IncompleteRead

        flaky = _ReadFailingResponse(IncompleteRead(partial=b'{"data":'))
        with mock.patch.object(
            self.mod, "urlopen", side_effect=[flaky, FakeResponse(response_payload())]
        ) as urlopen:
            self.mod.main(
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "1"]
            )
        self.assertEqual(urlopen.call_count, 2)
        self.assertTrue((self.home / "articles" / f"{ARTICLE_ID}.md").exists())
        state = self._state()
        self.assertEqual(
            [a["status"] for a in state["attempts"]], ["network_body_interrupted", 200]
        )
        self.assertEqual([a.get("phase") for a in state["attempts"]], ["body", None])

    def test_body_read_timeout_is_retried_and_recorded_as_the_body_phase(self):
        flaky = _ReadFailingResponse(TimeoutError("read timed out"))
        with mock.patch.object(
            self.mod, "urlopen", side_effect=[flaky, FakeResponse(response_payload())]
        ) as urlopen:
            self.mod.main(
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "1"]
            )
        self.assertEqual(urlopen.call_count, 2)
        state = self._state()
        self.assertEqual(
            [a["status"] for a in state["attempts"]], ["network_timeout", 200]
        )
        self.assertEqual(state["attempts"][0].get("phase"), "body")

    def test_truncated_body_without_a_retry_budget_stops_with_a_fixed_category(self):
        from http.client import IncompleteRead

        flaky = _ReadFailingResponse(IncompleteRead(partial=b"SECRET-BODY"))
        with mock.patch.object(self.mod, "urlopen", side_effect=[flaky]) as urlopen:
            code, err = fail_run(self.mod.main, ["--origin-id", ARTICLE_ID, "--allow-once"])
        self.assertEqual(code, 1)
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("network_body_interrupted", err)
        self.assertIn("No automatic retry was performed.", err)
        for leak in (FAKE_TOKEN, "SECRET-BODY", "shared-data.dowjones.io", "Authorization"):
            self.assertNotIn(leak, err)
        self.assertEqual(
            [a["status"] for a in self._state()["attempts"]], ["network_body_interrupted"]
        )

    def test_connect_phase_failures_are_recorded_as_the_connect_phase(self):
        reset = URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
        with mock.patch.object(
            self.mod, "urlopen", side_effect=[reset, FakeResponse(response_payload())]
        ):
            self.mod.main(
                ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "1"]
            )
        state = self._state()
        self.assertEqual(
            [a["status"] for a in state["attempts"]], ["network_error", 200]
        )
        self.assertEqual(state["attempts"][0].get("phase"), "connect")

    def test_http_and_tls_failures_keep_no_phase_and_no_retry(self):
        cases = [
            _http_error("https://example.invalid", 503),
            URLError(ssl.SSLError("handshake failure")),
        ]
        for exc in cases:
            with self.subTest(kind=type(exc).__name__):
                shutil.rmtree(self.home / "state.json", ignore_errors=True)
                with mock.patch.object(self.mod, "urlopen", side_effect=[exc]) as urlopen:
                    code, err = fail_run(
                        self.mod.main,
                        ["--origin-id", ARTICLE_ID, "--allow-once", "--network-retries", "2"],
                    )
                self.assertEqual(code, 1)
                self.assertEqual(urlopen.call_count, 1)
                self.assertIsNone(self._state()["attempts"][-1].get("phase"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
