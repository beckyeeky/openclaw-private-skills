#!/usr/bin/env python3
"""Offline unit tests for the DeepSeek Search CLI.

Every HTTP call is replaced with a fake ``_urlopen``; these tests never use the
network, a real API key, or a billable request. Standard library only:

    python3 scripts/tests/test_query.py -v
"""

from __future__ import annotations

import email.message
import io
import json
import os
import ssl
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import query  # noqa: E402

KEY = "sk-test-not-a-real-key"


def result_item(**overrides):
    item = {
        "rerank_score": 0.91,
        "title": "Example result",
        "url": "https://example.com/article",
        "snippet": "A snippet",
        "summary": "A summary",
        "content": "# Page\n\nBody",
        "site_name": "Example",
        "site_icon": "https://example.com/icon.png",
        "date": "2026-01-02",
        "authority": "high",
    }
    item.update(overrides)
    return item


class FakeResponse:
    def __init__(self, payload, status=200, chunk_size=None):
        if isinstance(payload, bytes):
            self._body = payload
        else:
            self._body = json.dumps(payload).encode("utf-8")
        self.status = status
        self.chunk_size = chunk_size
        self._offset = 0

    def read(self, amount=-1):
        if amount is None or amount < 0:
            chunk = self._body[self._offset :]
            self._offset = len(self._body)
            return chunk
        if self.chunk_size is not None:
            amount = min(amount, self.chunk_size)
        chunk = self._body[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def http_error(status, body=b"", retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(
        query.SEARCH_URL,
        status,
        "server-reason-that-must-not-be-printed",
        headers,
        io.BytesIO(body),
    )


def run_cli(argv, key=KEY):
    env = {} if key is None else {query.ENV_VAR: key}
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True):
        with redirect_stdout(out), redirect_stderr(err):
            code = query.main(argv)
    return code, out.getvalue(), err.getvalue()


def error_record(stderr):
    return json.loads(stderr)["error"]


class RequestShapeTests(unittest.TestCase):
    def test_search_minimal_request(self):
        payload = {"results": [result_item()]}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ) as opener:
            code, out, err = run_cli(["search", "hello"])

        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), payload)
        self.assertEqual(opener.call_count, 1)

        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, query.SEARCH_URL)
        self.assertEqual(request.get_method(), "POST")
        # urllib stores added header names with Python's str.capitalize(),
        # so compare through the header mapping rather than exact casing.
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(request.headers["Accept"], "application/json")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {KEY}")
        self.assertEqual(
            dict(request.header_items())["Authorization"], f"Bearer {KEY}"
        )
        self.assertEqual(request.headers["User-agent"], query.USER_AGENT)
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(request.unredirected_hdrs["Authorization"], f"Bearer {KEY}")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")), {"query": "hello", "count": 10}
        )
        self.assertEqual(opener.call_args.kwargs["timeout"], query.DEFAULT_TIMEOUT)
        self.assertNotIn(KEY, out + err)

    def test_search_flags_are_mapped(self):
        payload = {"results": []}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ) as opener:
            code, _, _ = run_cli(
                [
                    "search",
                    "deepseek api",
                    "--count",
                    "50",
                    "--content",
                    "--original-question",
                    "what is new?",
                    "--localization",
                    "2001:0db8:0:0:0:0:0:1",
                ]
            )
        self.assertEqual(code, query.EXIT_OK)
        body = json.loads(opener.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "query": "deepseek api",
                "count": 50,
                "ori_question": "what is new?",
                "localization": "2001:db8::1",
                "need_content": True,
            },
        )

    def test_fetch_request(self):
        payload = {"title": "Page", "content": "# Heading\n\nText"}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ) as opener:
            code, out, err = run_cli(
                ["fetch", "https://example.com/page", "--timeout", "12.5"]
            )
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), payload)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, query.FETCH_URL)
        self.assertEqual(json.loads(request.data), {"url": "https://example.com/page"})
        self.assertEqual(opener.call_args.kwargs["timeout"], 12.5)

    def test_no_custom_api_base_option(self):
        with mock.patch.object(query, "_urlopen") as opener:
            code, out, err = run_cli(
                ["search", "q", "--api-base", "https://attacker.example"]
            )
        self.assertEqual(code, query.EXIT_USAGE)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "invalid_arguments")
        opener.assert_not_called()

    def test_argument_errors_are_structured_and_do_not_echo_values(self):
        cases = [
            ["search", "q", "--timeout", "not-a-number"],
            ["search", "q", "--api-key", KEY],
            ["unknown-command"],
        ]
        for argv in cases:
            with self.subTest(argv=argv[:2]):
                with mock.patch.object(query, "_urlopen") as opener:
                    code, out, err = run_cli(argv)
                self.assertEqual(code, query.EXIT_USAGE)
                self.assertEqual(out, "")
                self.assertEqual(error_record(err)["code"], "invalid_arguments")
                self.assertNotIn(KEY, out + err)
                self.assertNotIn("not-a-number", err)
                opener.assert_not_called()


class ParameterBoundaryTests(unittest.TestCase):
    def assert_usage_error(self, argv, code_name):
        with mock.patch.object(query, "_urlopen") as opener:
            code, out, err = run_cli(argv)
        self.assertEqual(code, query.EXIT_USAGE)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], code_name)
        opener.assert_not_called()

    def test_query_length_boundaries(self):
        payload = {"results": []}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ):
            code, _, _ = run_cli(["search", "中" * 128])
        self.assertEqual(code, query.EXIT_OK)
        self.assert_usage_error(["search", "中" * 129], "invalid_argument")
        self.assert_usage_error(["search", ""], "invalid_argument")
        self.assert_usage_error(["search", "   "], "invalid_argument")

    def test_count_boundaries(self):
        for count in (1, 50):
            with self.subTest(count=count):
                payload = {"results": []}
                with mock.patch.object(
                    query, "_urlopen", return_value=FakeResponse(payload)
                ) as opener:
                    code, _, _ = run_cli(["search", "q", "--count", str(count)])
                self.assertEqual(code, query.EXIT_OK)
                body = json.loads(opener.call_args.args[0].data)
                self.assertEqual(body["count"], count)
        for count in (0, -1, 51):
            with self.subTest(count=count):
                self.assert_usage_error(
                    ["search", "q", f"--count={count}"], "invalid_count"
                )

    def test_original_question_boundaries(self):
        payload = {"results": []}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ) as opener:
            code, _, _ = run_cli(
                ["search", "q", "--original-question", "x" * 128]
            )
        self.assertEqual(code, query.EXIT_OK)
        body = json.loads(opener.call_args.args[0].data)
        self.assertEqual(body["ori_question"], "x" * 128)
        self.assert_usage_error(
            ["search", "q", "--original-question", "x" * 129],
            "invalid_argument",
        )

    def test_localization_validation(self):
        payload = {"results": []}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ) as opener:
            code, _, _ = run_cli(["search", "q", "--localization", "203.0.113.7"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(
            json.loads(opener.call_args.args[0].data)["localization"],
            "203.0.113.7",
        )
        for bad in ("us", "999.1.1.1", "not-an-ip", "1.2.3.4/24"):
            with self.subTest(value=bad):
                self.assert_usage_error(
                    ["search", "q", "--localization", bad],
                    "invalid_localization",
                )

    def test_timeout_boundaries(self):
        for bad in ("0", "-1", "inf", "nan"):
            with self.subTest(timeout=bad):
                self.assert_usage_error(
                    ["search", "q", f"--timeout={bad}"], "invalid_timeout"
                )
        payload = {"results": []}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ) as opener:
            code, _, _ = run_cli(["search", "q", "--timeout", "0.1"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(opener.call_args.kwargs["timeout"], 0.1)

        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ) as opener:
            code, _, _ = run_cli(["search", "q", "--timeout", "601"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(opener.call_args.kwargs["timeout"], 601.0)

    def test_retries_boundaries(self):
        for bad in ("-1", "6"):
            with self.subTest(retries=bad):
                self.assert_usage_error(
                    ["search", "q", f"--retries={bad}"], "invalid_retries"
                )
        for good in ("0", "5"):
            with self.subTest(retries=good):
                with mock.patch.object(
                    query, "_urlopen", return_value=FakeResponse({"results": []})
                ):
                    code, _, _ = run_cli(["search", "q", f"--retries={good}"])
                self.assertEqual(code, query.EXIT_OK)

    def test_fetch_url_validation(self):
        valid = "https://example.com/" + "a" * (query.MAX_FETCH_URL_CHARS - 20)
        self.assertEqual(len(valid), query.MAX_FETCH_URL_CHARS)
        with mock.patch.object(
            query,
            "_urlopen",
            return_value=FakeResponse({"title": "T", "content": "Body"}),
        ) as opener:
            code, _, _ = run_cli(["fetch", valid])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(json.loads(opener.call_args.args[0].data)["url"], valid)

        invalid = [
            "ftp://example.com/page",
            "file:///etc/passwd",
            "https:///missing-host",
            "https://user:pass@example.com/page",
            "https://example.com/a b",
            "https://example.com:99999/page",
            "https://example.com/" + "a" * (query.MAX_FETCH_URL_CHARS - 19),
        ]
        for url in invalid:
            with self.subTest(url=url[:60]):
                self.assert_usage_error(["fetch", url], "invalid_fetch_url")


class AuthenticationTests(unittest.TestCase):
    def test_missing_key(self):
        for key in (None, "", "   "):
            with self.subTest(key=key):
                with mock.patch.object(query, "_urlopen") as opener:
                    code, out, err = run_cli(["search", "q"], key=key)
                self.assertEqual(code, query.EXIT_AUTH)
                self.assertEqual(out, "")
                self.assertEqual(error_record(err)["code"], "missing_api_key")
                self.assertIn(query.ENV_VAR, err)
                opener.assert_not_called()

    def test_invalid_key_never_echoed(self):
        for bad_key in ("sk-test key", "sk-test\nkey", "sk-密钥"):
            with self.subTest(key=bad_key[:12]):
                with mock.patch.object(query, "_urlopen") as opener:
                    code, out, err = run_cli(["search", "q"], key=bad_key)
                self.assertEqual(code, query.EXIT_AUTH)
                self.assertEqual(out, "")
                self.assertEqual(error_record(err)["code"], "invalid_api_key")
                self.assertNotIn(bad_key, out + err)
                opener.assert_not_called()


class HTTPErrorTests(unittest.TestCase):
    def test_final_client_errors_are_not_retried(self):
        for status in (400, 401, 402, 403, 404, 413):
            with self.subTest(status=status):
                body = ("SERVER-BODY " + KEY).encode("utf-8")
                with mock.patch.object(
                    query, "_urlopen", side_effect=http_error(status, body)
                ) as opener:
                    code, out, err = run_cli(["search", "q", "--retries", "5"])
                self.assertEqual(code, query.EXIT_HTTP)
                self.assertEqual(out, "")
                record = error_record(err)
                self.assertEqual(record["code"], "http_error")
                self.assertEqual(record["status"], status)
                self.assertFalse(record["retryable"])
                self.assertEqual(opener.call_count, 1)
                self.assertNotIn(KEY, out + err)
                self.assertNotIn("SERVER-BODY", out + err)
                self.assertNotIn("server-reason", out + err)

    def test_redirect_is_blocked_without_retry(self):
        with mock.patch.object(
            query, "_urlopen", side_effect=http_error(302)
        ) as opener:
            code, out, err = run_cli(["search", "q", "--retries", "5"])
        self.assertEqual(code, query.EXIT_HTTP)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "redirect_blocked")
        self.assertEqual(error_record(err)["status"], 302)
        self.assertEqual(opener.call_count, 1)

    def test_redirect_handler_refuses(self):
        handler = query._NoRedirect()
        self.assertIsNone(
            handler.redirect_request(
                None, None, 302, "Found", {}, "https://attacker.example/"
            )
        )


class RetryTests(unittest.TestCase):
    def test_retryable_statuses_retry_then_succeed(self):
        for status in (408, 429, 500, 503):
            with self.subTest(status=status):
                payload = {"results": []}
                with mock.patch.object(query, "_sleep") as sleeper:
                    with mock.patch.object(
                        query,
                        "_urlopen",
                        side_effect=[
                            http_error(status),
                            FakeResponse(payload),
                        ],
                    ) as opener:
                        code, out, err = run_cli(["search", "q"])
                self.assertEqual(code, query.EXIT_OK)
                self.assertEqual(err, "")
                self.assertEqual(json.loads(out), payload)
                self.assertEqual(opener.call_count, 2)
                self.assertEqual(
                    [call.args[0] for call in sleeper.call_args_list], [0.5]
                )

    def test_retry_after_is_honoured_and_capped(self):
        payload = {"results": []}
        with mock.patch.object(query, "_sleep") as sleeper:
            with mock.patch.object(
                query,
                "_urlopen",
                side_effect=[
                    http_error(429, retry_after=1),
                    FakeResponse(payload),
                ],
            ):
                code, _, _ = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(
            [call.args[0] for call in sleeper.call_args_list], [1.0]
        )

    def test_exponential_backoff_is_bounded(self):
        errors = [http_error(500) for _ in range(3)]
        with mock.patch.object(query, "_sleep") as sleeper:
            with mock.patch.object(query, "_urlopen", side_effect=errors) as opener:
                code, out, err = run_cli(["search", "q", "--retries", "2"])
        self.assertEqual(code, query.EXIT_NETWORK)
        self.assertEqual(out, "")
        record = error_record(err)
        self.assertEqual(record["code"], "retry_exhausted")
        self.assertEqual(record["status"], 500)
        self.assertTrue(record["retryable"])
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in sleeper.call_args_list], [0.5, 1.0]
        )

    def test_total_retry_wait_is_bounded(self):
        errors = [http_error(429, retry_after=9999) for _ in range(6)]
        with mock.patch.object(query, "_sleep") as sleeper:
            with mock.patch.object(query, "_urlopen", side_effect=errors) as opener:
                code, _, err = run_cli(["search", "q", "--retries", "5"])
        self.assertEqual(code, query.EXIT_NETWORK)
        self.assertEqual(error_record(err)["code"], "retry_exhausted")
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in sleeper.call_args_list], [8.0, 8.0]
        )

    def test_zero_retries_does_not_retry(self):
        with mock.patch.object(query, "_sleep") as sleeper:
            with mock.patch.object(
                query, "_urlopen", side_effect=http_error(429)
            ) as opener:
                code, out, err = run_cli(["search", "q", "--retries", "0"])
        self.assertEqual(code, query.EXIT_NETWORK)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "retry_exhausted")
        self.assertEqual(opener.call_count, 1)
        sleeper.assert_not_called()

    def test_returned_retryable_status_retries(self):
        payload = {"results": []}
        with mock.patch.object(query, "_sleep"):
            with mock.patch.object(
                query,
                "_urlopen",
                side_effect=[
                    FakeResponse(payload, status=500),
                    FakeResponse(payload),
                ],
            ) as opener:
                code, _, _ = run_cli(["search", "q", "--retries", "1"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(opener.call_count, 2)

    def test_returned_redirect_status_is_blocked(self):
        with mock.patch.object(query, "_sleep") as sleeper:
            with mock.patch.object(
                query,
                "_urlopen",
                return_value=FakeResponse({"results": []}, status=301),
            ):
                code, out, err = run_cli(["search", "q", "--retries", "5"])
        self.assertEqual(code, query.EXIT_HTTP)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "redirect_blocked")
        sleeper.assert_not_called()


class NetworkFailureTests(unittest.TestCase):
    def test_transient_network_error_retries_then_succeeds(self):
        payload = {"results": []}
        with mock.patch.object(query, "_sleep") as sleeper:
            with mock.patch.object(
                query,
                "_urlopen",
                side_effect=[
                    urllib.error.URLError(ConnectionResetError("reset")),
                    FakeResponse(payload),
                ],
            ) as opener:
                code, _, _ = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in sleeper.call_args_list], [0.5]
        )

    def test_network_error_is_bounded(self):
        errors = [
            urllib.error.URLError(ConnectionResetError("reset")),
            urllib.error.URLError(ConnectionResetError("reset")),
        ]
        with mock.patch.object(query, "_sleep"):
            with mock.patch.object(query, "_urlopen", side_effect=errors) as opener:
                code, out, err = run_cli(["search", "q", "--retries", "1"])
        self.assertEqual(code, query.EXIT_NETWORK)
        self.assertEqual(out, "")
        record = error_record(err)
        self.assertEqual(record["code"], "network_error")
        self.assertTrue(record["retryable"])
        self.assertEqual(opener.call_count, 2)

    def test_timeout_is_reported(self):
        with mock.patch.object(query, "_sleep"):
            with mock.patch.object(
                query,
                "_urlopen",
                side_effect=[TimeoutError("timed out"), FakeResponse({"results": []})],
            ) as opener:
                code, _, _ = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(opener.call_count, 2)

        with mock.patch.object(
            query,
            "_urlopen",
            side_effect=urllib.error.URLError(TimeoutError("timed out")),
        ):
            code, out, err = run_cli(["search", "q", "--retries", "0"])
        self.assertEqual(code, query.EXIT_NETWORK)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "request_timeout")

    def test_certificate_failure_is_final(self):
        cert_errors = [
            ssl.SSLCertVerificationError("certificate verify failed"),
            urllib.error.URLError(
                ssl.SSLCertVerificationError("certificate verify failed")
            ),
        ]
        for cert_error in cert_errors:
            with self.subTest(kind=type(cert_error).__name__):
                with mock.patch.object(query, "_sleep") as sleeper:
                    with mock.patch.object(
                        query, "_urlopen", side_effect=cert_error
                    ) as opener:
                        code, out, err = run_cli(
                            ["search", "q", "--retries", "5"]
                        )
                self.assertEqual(code, query.EXIT_NETWORK)
                self.assertEqual(out, "")
                self.assertEqual(
                    error_record(err)["code"], "tls_verification_failed"
                )
                self.assertEqual(opener.call_count, 1)
                sleeper.assert_not_called()

    def test_unexpected_error_is_sanitized(self):
        with mock.patch.object(
            query, "_urlopen", side_effect=RuntimeError("boom " + KEY)
        ):
            code, out, err = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_INTERNAL)
        self.assertEqual(out, "")
        record = error_record(err)
        self.assertEqual(record["code"], "internal_error")
        self.assertIn("RuntimeError", record["message"])
        self.assertNotIn(KEY, out + err)
        self.assertNotIn("boom", out + err)

    def test_tls_context_verifies(self):
        context = query._make_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)


class ResponseValidationTests(unittest.TestCase):
    def assert_schema_error(self, command_argv, payload):
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ) as opener:
            code, out, err = run_cli(command_argv)
        self.assertEqual(code, query.EXIT_RESPONSE)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "invalid_response")
        self.assertEqual(opener.call_count, 1)

    def test_empty_search_is_success(self):
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse({"results": []})
        ):
            code, out, err = run_cli(["search", "nothing"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), {"results": []})

    def test_invalid_search_payloads(self):
        payloads = [
            [],
            {},
            {"results": "not-a-list"},
            {"results": [1]},
            {"results": [{"title": "TITLE-MARKER"}]},
            {"results": [{"url": "https://example.com/no-title"}]},
            {"results": [{"title": "T", "url": "/relative"}]},
            {"results": [{"title": "T", "url": "ftp://example.com/x"}]},
        ]
        for payload in payloads:
            with self.subTest(payload=str(payload)[:60]):
                self.assert_schema_error(["search", "q"], payload)

    def test_schema_error_does_not_echo_payload(self):
        payload = {"results": [{"title": "TITLE-MARKER"}]}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ):
            code, out, err = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_RESPONSE)
        self.assertEqual(out, "")
        self.assertNotIn("TITLE-MARKER", out + err)

    def test_invalid_fetch_payloads(self):
        payloads = [
            [],
            {},
            {"content": "Body"},
            {"title": "T"},
            {"title": "T", "content": ""},
            {"title": "T", "content": "   "},
            {"title": 1, "content": "Body"},
        ]
        for payload in payloads:
            with self.subTest(payload=str(payload)[:60]):
                self.assert_schema_error(["fetch", "https://example.com/x"], payload)

    def test_non_json_response(self):
        with mock.patch.object(
            query,
            "_urlopen",
            return_value=FakeResponse(b"<html>SERVER-SECRET-MARKER</html>"),
        ):
            code, out, err = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_RESPONSE)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "invalid_response")
        self.assertNotIn("SERVER-SECRET-MARKER", out + err)

    def test_oversized_response_is_rejected(self):
        with mock.patch.object(query, "MAX_RESPONSE_BYTES", 8):
            with mock.patch.object(
                query, "_urlopen", return_value=FakeResponse(b"123456789")
            ):
                code, out, err = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_RESPONSE)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "response_too_large")

    def test_response_is_read_across_short_reads(self):
        payload = {"results": [result_item(title="T" * 200)]}
        with mock.patch.object(
            query,
            "_urlopen",
            return_value=FakeResponse(payload, chunk_size=7),
        ):
            code, out, err = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), payload)

    def test_empty_body_is_invalid_response(self):
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(b"")
        ):
            code, out, err = run_cli(["search", "q"])
        self.assertEqual(code, query.EXIT_RESPONSE)
        self.assertEqual(out, "")
        self.assertEqual(error_record(err)["code"], "invalid_response")

    def test_fetch_success(self):
        payload = {"title": "Page", "content": "# Heading\n\nText"}
        with mock.patch.object(
            query, "_urlopen", return_value=FakeResponse(payload)
        ):
            code, out, err = run_cli(["fetch", "http://example.com/page"])
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), payload)


class OutputTests(unittest.TestCase):
    def test_stdout_by_default_and_no_file_created(self):
        payload = {"results": [result_item()]}
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.object(
                    query, "_urlopen", return_value=FakeResponse(payload)
                ):
                    code, out, err = run_cli(["search", "q"])
                self.assertEqual(os.listdir(tmp), [])
            finally:
                os.chdir(previous)
        self.assertEqual(code, query.EXIT_OK)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), payload)

    def test_output_file_is_written(self):
        payload = {"results": [result_item()]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            with mock.patch.object(
                query, "_urlopen", return_value=FakeResponse(payload)
            ):
                code, out, err = run_cli(["search", "q", "--output", str(path)])
            self.assertEqual(code, query.EXIT_OK)
            self.assertEqual(out, "")
            self.assertEqual(err, "")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.json"
            path.write_text("sentinel", encoding="utf-8")
            with mock.patch.object(
                query, "_urlopen", return_value=FakeResponse({"results": []})
            ) as opener:
                code, out, err = run_cli(["search", "q", "--output", str(path)])
            self.assertEqual(code, query.EXIT_OUTPUT)
            self.assertEqual(out, "")
            self.assertEqual(error_record(err)["code"], "output_exists")
            self.assertEqual(path.read_text(encoding="utf-8"), "sentinel")
            # Preflight avoids paying for a request whose result cannot be saved.
            opener.assert_not_called()

    def test_missing_output_directory_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing" / "result.json"
            with mock.patch.object(
                query, "_urlopen", return_value=FakeResponse({"results": []})
            ) as opener:
                code, out, err = run_cli(["search", "q", "--output", str(path)])
            self.assertEqual(code, query.EXIT_OUTPUT)
            self.assertEqual(out, "")
            self.assertEqual(error_record(err)["code"], "output_error")
            self.assertFalse(path.exists())
            opener.assert_not_called()

    def test_failed_request_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            with mock.patch.object(
                query, "_urlopen", side_effect=http_error(401)
            ):
                code, _, _ = run_cli(
                    ["search", "q", "--output", str(path), "--retries", "0"]
                )
            self.assertEqual(code, query.EXIT_HTTP)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
