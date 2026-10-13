#!/usr/bin/env python3
"""Offline contract tests for scripts/generate.py (codex-image).

No credentials, no network, no image generation, no cost:

* ``HOME`` points at a throwaway temp directory that holds a *dummy*
  ``~/.codex/auth.json`` (never a real token).
* In-process tests replace ``urllib.request.urlopen`` with a recorder that
  fails before any socket is created (and block ``socket.socket`` as well).
* CLI tests run in a minimal environment whose ``http_proxy``/``https_proxy``
  point at 127.0.0.1:9 (nothing listens there), so even a mistaken request can
  never leave the device.
* No test reaches a success path; the output directory must stay empty.

Run from the repository root:

    python3 -m unittest discover -s skills/codex-image/tests -v
    # or
    python3 skills/codex-image/tests/test_generate_offline.py
"""

import importlib.util
import io
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

TESTS_DIR = pathlib.Path(__file__).resolve().parent
SCRIPT = TESTS_DIR.parent / "scripts" / "generate.py"

DUMMY_TOKEN = "DUMMY-NOT-A-REAL-TOKEN"
DEAD_PROXY = "http://127.0.0.1:9"


def _blocked_socket(*args, **kwargs):
    raise AssertionError("offline test harness: network access is blocked")


class NetworkRecorder:
    """Stand-in for urllib.request.urlopen that records calls and never dials out."""

    def __init__(self, error_factory):
        self.calls = []
        self._error_factory = error_factory

    def __call__(self, req, *args, **kwargs):
        url = getattr(req, "full_url", req)
        self.calls.append((url, kwargs.get("timeout")))
        raise self._error_factory()


def _http_error(code):
    def factory():
        return urllib.error.HTTPError("https://example.invalid/backend", code, "error", {}, None)

    return factory


class GenerateOfflineBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="codex-image-offline-")
        cls.home = pathlib.Path(cls._tmp.name)
        cls._home_patch = mock.patch.dict(os.environ, {"HOME": str(cls.home)})
        cls._home_patch.start()
        spec = importlib.util.spec_from_file_location("codex_generate_offline", SCRIPT)
        cls.gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gen)

    @classmethod
    def tearDownClass(cls):
        cls._home_patch.stop()
        cls._tmp.cleanup()

    def setUp(self):
        self.codex_dir = self.home / ".codex"
        self.codex_dir.mkdir(parents=True, exist_ok=True)
        self.auth_file = self.codex_dir / "auth.json"
        self._remove_auth()

    def _remove_auth(self):
        if self.auth_file.is_dir():
            self.auth_file.rmdir()
        elif self.auth_file.exists():
            self.auth_file.unlink()

    def write_auth(self, raw):
        self._remove_auth()
        self.auth_file.write_text(raw, encoding="utf-8")

    def write_auth_obj(self, obj):
        self.write_auth(json.dumps(obj))

    def output_dir(self):
        return self.home / ".hermes" / "codex-images"


class InputHelpersOfflineTest(GenerateOfflineBase):
    """Unit tests for the bounded reader and the oversized-input classifier."""

    def test_read_bounded_never_over_reads(self):
        gen = self.gen
        text, truncated, err = gen._read_bounded(io.BytesIO(b"x" * 10), 4)
        self.assertEqual((text, truncated, err), ("xxxx", True, None))
        text, truncated, err = gen._read_bounded(io.BytesIO("héllo".encode("utf-8")), 1024)
        self.assertEqual((text, truncated, err), ("héllo", False, None))
        text, truncated, err = gen._read_bounded(io.BytesIO(b"\xff\xfe"), 1024)
        self.assertIsNone(text)
        self.assertIn("UTF-8", err)

    def test_read_bounded_is_bounded(self):
        read_sizes = []

        class Spy(io.BytesIO):
            def read(self, size=-1):
                read_sizes.append(size)
                return super().read(size)

        self.gen._read_bounded(Spy(b"a" * 5000), 100)
        self.assertLessEqual(max(read_sizes), 101)

    def test_read_bounded_truncation_mid_utf8_is_not_reported_as_invalid(self):
        # The limit can fall inside a 3-byte character of otherwise valid UTF-8.
        # The read is already flagged as truncated and the dropped text is never
        # parsed, so a strict-decode failure here must not surface as an error.
        raw = "中文".encode("utf-8") * 2  # 12 bytes, valid UTF-8
        text, truncated, err = self.gen._read_bounded(io.BytesIO(raw), 4)
        self.assertTrue(truncated)
        self.assertIsNone(err)
        self.assertIsNotNone(text)

    def test_classify_oversized_input_never_asserts_prompt_size(self):
        gen = self.gen
        # An over-budget document is dropped before parsing; whatever the prompt
        # holds, the classifier may not claim prompt_too_large nor that the
        # prompt is within budget.
        for label in ("stdin JSON", "prompt-file JSON"):
            rec = gen._classify_oversized_input(label)
            self.assertEqual(rec["code"], "input_too_large", label)
            self.assertIn(label, rec["error"])
            self.assertIn("cannot be determined", rec["error"])
            self.assertNotIn("itself is not over", rec["error"])
            self.assertNotIn("while the 'prompt' value", rec["error"])


class AuthErrorOfflineTest(GenerateOfflineBase):
    """auth.json failures must be structured JSON, never a traceback, never a leak."""

    def test_missing_auth_file_is_no_auth(self):
        token, err = self.gen._load_token()
        self.assertIsNone(token)
        self.assertEqual(err["code"], "no_auth")
        self.assertIn("codex login", err["error"])

    def test_invalid_json_is_not_reported_as_logged_out(self):
        self.write_auth('{"tokens": {"access_token": "' + DUMMY_TOKEN + '"\n')
        token, err = self.gen._load_token()
        self.assertIsNone(token)
        self.assertEqual(err["code"], "auth_invalid")
        self.assertNotIn(DUMMY_TOKEN, json.dumps(err))
        self.assertIn("corrupt", err["error"])
        self.assertIn("not merely logged out", err["error"])

    def test_wrong_structure_is_malformed_not_logged_out(self):
        for raw in ("[]", '"text"', '{"tokens": []}', '{"tokens": {"access_token": 12345}}'):
            self.write_auth(raw)
            token, err = self.gen._load_token()
            self.assertIsNone(token, raw)
            self.assertEqual(err["code"], "auth_malformed", raw)
            self.assertIn("corrupt", err["error"], raw)
            self.assertIn("not merely logged out", err["error"], raw)

    def test_structurally_valid_without_token_is_no_auth(self):
        for raw in ('{"tokens": {}}', '{"foo": 1}', '{"tokens": {"access_token": ""}}'):
            self.write_auth(raw)
            token, err = self.gen._load_token()
            self.assertIsNone(token, raw)
            self.assertEqual(err["code"], "no_auth", raw)

    def test_unreadable_auth_file_is_structured(self):
        self._remove_auth()
        self.auth_file.mkdir()
        token, err = self.gen._load_token()
        self.assertIsNone(token)
        self.assertEqual(err["code"], "auth_unreadable")
        self.assertIn("not a logged-out state", err["error"])

    def test_valid_dummy_token_is_returned(self):
        self.write_auth_obj({"tokens": {"access_token": DUMMY_TOKEN}})
        token, err = self.gen._load_token()
        self.assertIsNone(err)
        self.assertEqual(token, DUMMY_TOKEN)

    def test_refresh_that_leaves_no_token_is_no_auth_not_auth_stale(self):
        # An expired-looking JWT (exp in the past) forces the refresh branch.
        import base64 as b64
        payload = b64.urlsafe_b64encode(json.dumps({"exp": 1}).encode()).rstrip(b"=").decode()
        expired = f"header.{payload}.sig"
        self.write_auth_obj({"tokens": {"access_token": expired}})

        def fake_refresh():
            self.write_auth_obj({"tokens": {}})

        with mock.patch.object(self.gen, "_refresh_token", fake_refresh):
            token, err = self.gen._load_token()
        self.assertIsNone(token)
        self.assertEqual(err["code"], "no_auth")

    def test_refresh_fallback_branch_reports_no_auth(self):
        # The `if not refreshed` guard is defensive (today _extract_token always
        # reports the error first); if it is ever reached it must say no_auth,
        # never auth_stale.
        import base64 as b64
        payload = b64.urlsafe_b64encode(json.dumps({"exp": 1}).encode()).rstrip(b"=").decode()
        expired = f"header.{payload}.sig"
        self.write_auth_obj({"tokens": {"access_token": expired}})
        with mock.patch.object(self.gen, "_refresh_token", lambda: None), \
                mock.patch.object(self.gen, "_extract_token", side_effect=[(expired, None), (None, None)]):
            token, err = self.gen._load_token()
        self.assertIsNone(token)
        self.assertEqual(err["code"], "no_auth")


class NoNetworkOfflineTest(GenerateOfflineBase):
    """generate_image must stop locally; no socket, no retry on network failure."""

    def _run_generate(self, recorder):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(socket, "socket", _blocked_socket), \
                mock.patch.object(self.gen.urllib.request, "urlopen", recorder), \
                mock.patch.object(self.gen.time, "sleep", lambda *_: None), \
                mock.patch.object(self.gen, "_refresh_token", lambda: None), \
                mock.patch.object(sys, "stdout", out), \
                mock.patch.object(sys, "stderr", err):
            result = self.gen.generate_image("offline test prompt")
        self.assertNotIn(DUMMY_TOKEN, out.getvalue() + err.getvalue())
        return result, out.getvalue()

    def test_network_error_is_structured_and_not_retried(self):
        self.write_auth_obj({"tokens": {"access_token": DUMMY_TOKEN}})
        recorder = NetworkRecorder(lambda: urllib.error.URLError("blocked by test"))
        result, stdout = self._run_generate(recorder)
        self.assertIsNone(result)
        self.assertEqual(len(recorder.calls), 1)
        payload = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(payload["code"], "connection_error")
        self.assertNotIn(DUMMY_TOKEN, stdout)

    def test_401_retries_three_times_then_reports_auth_stale(self):
        self.write_auth_obj({"tokens": {"access_token": DUMMY_TOKEN}})
        recorder = NetworkRecorder(_http_error(401))
        result, stdout = self._run_generate(recorder)
        self.assertIsNone(result)
        self.assertEqual(len(recorder.calls), 3)
        payload = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(payload["code"], "auth_stale")

    def test_429_is_retried_then_reports_max_retries(self):
        self.write_auth_obj({"tokens": {"access_token": DUMMY_TOKEN}})
        recorder = NetworkRecorder(_http_error(429))
        result, stdout = self._run_generate(recorder)
        self.assertIsNone(result)
        self.assertEqual(len(recorder.calls), 3)
        payload = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(payload["code"], "max_retries")

    def test_content_filter_is_not_retried(self):
        self.write_auth_obj({"tokens": {"access_token": DUMMY_TOKEN}})

        class FakeResponse:
            def __init__(self):
                self._lines = [
                    b"data: " + json.dumps({"type": "response.completed", "response": {"status": "completed", "output": []}}).encode() + b"\n"
                ]

            def readline(self):
                return self._lines.pop(0) if self._lines else b""

            def close(self):
                pass

        recorder = NetworkRecorder(lambda: None)

        def fake_urlopen(req, *args, **kwargs):
            recorder.calls.append((getattr(req, "full_url", req), kwargs.get("timeout")))
            return FakeResponse()

        result, stdout = self._run_generate(fake_urlopen)
        self.assertIsNone(result)
        self.assertEqual(len(recorder.calls), 1)
        payload = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(payload["code"], "filtered")

    def test_empty_token_without_error_is_reported_as_no_auth(self):
        # _load_token returning (None, None) is not reachable today, but the
        # public entry must still refuse to send "Bearer None".
        self.write_auth_obj({"tokens": {"access_token": DUMMY_TOKEN}})
        recorder = NetworkRecorder(lambda: urllib.error.URLError("blocked by test"))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(socket, "socket", _blocked_socket), \
                mock.patch.object(self.gen.urllib.request, "urlopen", recorder), \
                mock.patch.object(self.gen, "_load_token", lambda: (None, None)), \
                mock.patch.object(sys, "stdout", out), \
                mock.patch.object(sys, "stderr", err):
            result = self.gen.generate_image("offline test prompt")
        self.assertIsNone(result)
        self.assertEqual(len(recorder.calls), 0)
        payload = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual(payload["code"], "no_auth")

    def test_lone_surrogate_prompt_is_invalid_input_not_a_traceback(self):
        # generate_image is a public entry point: hash/encode must not raise.
        self.write_auth_obj({"tokens": {"access_token": DUMMY_TOKEN}})
        recorder = NetworkRecorder(lambda: urllib.error.URLError("blocked by test"))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(socket, "socket", _blocked_socket), \
                mock.patch.object(self.gen.urllib.request, "urlopen", recorder), \
                mock.patch.object(sys, "stdout", out), \
                mock.patch.object(sys, "stderr", err):
            result = self.gen.generate_image("bad \ud800 surrogate")
        self.assertIsNone(result)
        self.assertEqual(len(recorder.calls), 0)
        payload = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual(payload["code"], "invalid_input")
        self.assertIn("not valid UTF-8", payload["error"])


class CliContractOfflineTest(GenerateOfflineBase):
    """CLI-level contract: stdout is JSON only, exit codes stable, no traceback."""

    def run_cli(self, args=(), stdin=""):
        env = {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
            "http_proxy": DEAD_PROXY,
            "https_proxy": DEAD_PROXY,
            "HTTP_PROXY": DEAD_PROXY,
            "HTTPS_PROXY": DEAD_PROXY,
        }
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        # stdout must be JSON only (the core contract of generate.py)
        for line in proc.stdout.splitlines():
            if line.strip():
                json.loads(line)
        self.assertNotIn("Traceback", proc.stderr)
        return proc

    def last_json(self, proc):
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, f"no JSON on stdout (stderr: {proc.stderr})")
        return json.loads(lines[-1])

    def assert_error(self, proc, code):
        payload = self.last_json(proc)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["code"], code)
        self.assertEqual(proc.returncode, 1)
        return payload

    # ---- auth.json handling -------------------------------------------------

    def test_cli_missing_auth_is_no_auth(self):
        self._remove_auth()
        self.assert_error(self.run_cli(stdin='{"prompt": "p"}'), "no_auth")

    def test_cli_corrupt_auth_is_structured_and_does_not_leak(self):
        self.write_auth('{"tokens": {"access_token": "' + DUMMY_TOKEN + '"\n')
        proc = self.run_cli(stdin='{"prompt": "p"}')
        payload = self.assert_error(proc, "auth_invalid")
        self.assertIn("corrupt", payload["error"])
        self.assertNotIn(DUMMY_TOKEN, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.count("\n"), 1)

    def test_cli_list_shaped_auth_is_malformed(self):
        self.write_auth("[]")
        self.assert_error(self.run_cli(stdin='{"prompt": "p"}'), "auth_malformed")

    def test_cli_valid_dummy_token_stops_before_the_network(self):
        self.write_auth_obj({"tokens": {"access_token": DUMMY_TOKEN}})
        proc = self.run_cli(stdin='{"prompt": "p"}')
        payload = self.assert_error(proc, "connection_error")
        self.assertNotIn(DUMMY_TOKEN, proc.stdout + proc.stderr)
        self.assertTrue(payload["prompt_sha256"])

    # ---- bounded input / prompt size ---------------------------------------

    def test_cli_oversized_stdin_prompt_is_prompt_too_large(self):
        prompt = "a" * 70000
        proc = self.run_cli(stdin=json.dumps({"prompt": prompt}))
        self.assert_error(proc, "prompt_too_large")

    def test_cli_oversized_prompt_file_is_prompt_too_large(self):
        path = self.home / "big.json"
        path.write_text(json.dumps({"prompt": "a" * 70000}), encoding="utf-8")
        self.assert_error(self.run_cli(["--prompt-file", str(path)]), "prompt_too_large")

    def test_cli_prompt_byte_limit_boundary(self):
        at_limit = self.gen.MAX_PROMPT_BYTES
        proc = self.run_cli(stdin=json.dumps({"prompt": "a" * at_limit}))
        self.assert_error(proc, "no_auth")  # passes validation, then no credentials
        proc = self.run_cli(stdin=json.dumps({"prompt": "a" * (at_limit + 1)}))
        self.assert_error(proc, "prompt_too_large")

    def test_cli_multibyte_prompt_is_measured_in_bytes(self):
        # 32769 CJK characters = 98307 UTF-8 bytes > 64 KiB
        proc = self.run_cli(stdin=json.dumps({"prompt": "\u6d4b" * 32769}, ensure_ascii=True))
        self.assert_error(proc, "prompt_too_large")

    def test_cli_long_non_prompt_fields_are_not_misclassified(self):
        doc = {"prompt": "ok", "references": ["x" * 200000], "notes": "y" * 200000}
        proc = self.run_cli(stdin=json.dumps(doc))
        # Legal JSON whose extra fields exceed MAX_PROMPT_BYTES must reach the
        # auth check, not be reported as invalid_input/prompt_too_large.
        self.assert_error(proc, "no_auth")

    def test_cli_beyond_budget_with_small_prompt_is_input_too_large(self):
        doc = '{"prompt": "ok", "blob": "' + "x" * (self.gen.MAX_INPUT_BYTES + 5000) + '"}'
        payload = self.assert_error(self.run_cli(stdin=doc), "input_too_large")
        self.assertIn("cannot be determined", payload["error"])

    def test_cli_beyond_budget_with_huge_prompt_is_input_too_large(self):
        # Over-budget input is dropped at the cut before parsing, so the prompt
        # size is unknowable: a huge prompt is reported as input_too_large, not
        # asserted to be prompt_too_large from a truncated scan.
        doc = '{"prompt": "' + "a" * (self.gen.MAX_INPUT_BYTES + 5000) + '"}'
        payload = self.assert_error(self.run_cli(stdin=doc), "input_too_large")
        self.assertNotIn("prompt_too_large", payload["error"])

    def test_cli_oversized_document_without_prompt_key_is_input_too_large(self):
        # No 'prompt' key at all: the document is too big to parse, so it must
        # not be reported as a missing-key invalid_input fabricated from the cut.
        doc = '{"notes": "' + "x" * (self.gen.MAX_INPUT_BYTES + 5000) + '"}'
        self.assert_error(self.run_cli(stdin=doc), "input_too_large")

    def test_cli_truncation_mid_utf8_character_is_not_invalid_utf8(self):
        # A valid UTF-8 document cut in the middle of a 3-byte character must be
        # classified by size, never as "input is not valid UTF-8".
        prefix = '{"prompt": "'
        unit = "中"  # 3 UTF-8 bytes
        count = (self.gen.MAX_INPUT_BYTES - len(prefix.encode("utf-8"))) // 3 + 2
        raw = (prefix + unit * count + '"}, "pad": "y"}').encode("utf-8")
        self.assertGreater(len(raw), self.gen.MAX_INPUT_BYTES)
        path = self.home / "straddle.json"
        path.write_bytes(raw)
        proc = self.run_cli(["--prompt-file", str(path)])
        payload = self.assert_error(proc, "input_too_large")
        self.assertNotIn("not valid UTF-8", payload["error"])

    def test_cli_never_truncates_valid_json(self):
        # 200 KB of legal JSON around a small prompt must parse as a whole.
        doc = {"prompt": "ok", "pad": "z" * 200000}
        proc = self.run_cli(stdin=json.dumps(doc))
        payload = self.last_json(proc)
        self.assertNotIn(payload["code"], ("invalid_input", "prompt_too_large", "input_too_large"))

    # ---- malformed input ----------------------------------------------------

    def test_cli_malformed_inputs_are_structured(self):
        cases = [
            ('{"prompt": "x"', "invalid_input"),
            ("", "invalid_input"),
            ("not json", "invalid_input"),
            ("[1, 2]", "invalid_input"),
            ("{}", "invalid_input"),
            ('{"prompt": 123}', "invalid_input"),
            ('{"prompt": "   "}', "invalid_input"),
            ('{"prompt": "p", "reference": 7}', "invalid_input"),
        ]
        for stdin, code in cases:
            with self.subTest(stdin=stdin):
                # Empty stdin falls through to the positional/--prompt-file path
                args = ("--prompt-file", str(TESTS_DIR / "does-not-exist.json")) if stdin == "" else ()
                self.assert_error(self.run_cli(args, stdin=stdin), code)

    def test_cli_lone_surrogate_prompt_is_structured_invalid_input(self):
        # json.loads('{"prompt": "\\ud800"}') yields a lone surrogate; strict
        # UTF-8 encoding must not raise out of the CLI.
        proc = self.run_cli(stdin='{"prompt": "\\ud800"}')
        payload = self.assert_error(proc, "invalid_input")
        self.assertIn("not valid UTF-8", payload["error"])
        self.assertEqual(proc.stdout.count("\n"), 1)
        self.assertNotIn("surrogates not allowed", proc.stderr)

    def test_cli_lone_surrogate_in_prompt_file_is_invalid_input(self):
        path = self.home / "surrogate.json"
        path.write_bytes(b'{"prompt": "\\udfff"}')
        self.assert_error(self.run_cli(["--prompt-file", str(path)]), "invalid_input")

    def test_cli_lone_surrogate_reference_is_invalid_input(self):
        proc = self.run_cli(stdin='{"prompt": "p", "reference": "\\ud800/x.png"}')
        self.assert_error(proc, "invalid_input")

    # ---- CLI compatibility --------------------------------------------------

    def test_cli_positional_prompt_still_works_and_warns(self):
        proc = self.run_cli(("a cat in space",), stdin="")
        self.assert_error(proc, "no_auth")
        self.assertIn("deprecated", proc.stderr)

    def test_cli_prompt_file_and_missing_reference(self):
        path = self.home / "prompt.json"
        path.write_text(json.dumps({"prompt": "p", "reference": str(self.home / "nope.png")}), encoding="utf-8")
        self.assert_error(self.run_cli(("--prompt-file", str(path)), stdin=""), "ref_not_found")

    def test_cli_bad_mime_reference(self):
        prompt_file = self.home / "prompt2.json"
        ref = self.home / "ref.jpg"
        ref.write_bytes(b"definitely not an image")
        prompt_file.write_text(json.dumps({"prompt": "p", "reference": str(ref)}), encoding="utf-8")
        self.assert_error(self.run_cli(("--prompt-file", str(prompt_file)), stdin=""), "bad_mime")

    def test_cli_flag_surface_is_unchanged(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            env={"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("--verbose", proc.stdout)
        for flag in ("--reference", "--prompt-file", "--output"):
            self.assertIn(flag, proc.stdout)
        # Unknown flags still fail with the argparse usage error (exit 2)
        bad = self.run_cli(("--verbose",), stdin='{"prompt": "p"}')
        self.assertEqual(bad.returncode, 2)

    # ---- no images, no cost -------------------------------------------------

    def test_no_image_was_written_during_the_suite(self):
        out_dir = self.output_dir()
        if out_dir.exists():
            self.assertEqual(list(out_dir.iterdir()), [])
