"""Deterministic tests: no live requests, credentials, uploads or publication."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import archive_core as core
import image_assets as assets
from test_image_assets import FakeR2


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetcher = load("fetch-wechat")
publisher = load("publish-telegraph")
URL = "https://mp.weixin.qq.com/s/example"
TEXT = "This is a useful article about science and careful local preservation."
RAW = f'<html><title>Article</title><div id="js_content"><p>{TEXT}</p></div></html>'.encode()


def article(raw=RAW, content=TEXT, **extra):
    return {"title": "Same title", "content": content, "_raw_html": raw, **extra}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {"HOME": str(self.root), "WECHAT_ARTICLE_OUTPUT_DIR": str(self.root / "archive")}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        for target in ("socket.socket.connect", "urllib.request.urlopen", "image_assets.urlopen"):
            guard = patch(target, side_effect=AssertionError("Live network forbidden in offline tests"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_output_precedence_and_default(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "home", return_value=self.root):
            self.assertEqual(core.output_directory(), self.root / ".local/share/wechat-articles")
            os.environ["XDG_DATA_HOME"] = str(self.root / "xdg")
            self.assertEqual(core.output_directory(), self.root / "xdg/wechat-articles")
            os.environ["WECHAT_ARTICLE_OUTPUT_DIR"] = str(self.root / "configured")
            self.assertEqual(core.output_directory(), self.root / "configured")
            self.assertEqual(core.output_directory("./override"), Path("override"))

    def test_token_and_r2_environment_are_not_consent(self):
        legacy = self.root / ".hermes/telegraph_token"
        legacy.parent.mkdir()
        legacy.write_text("fake-test-token")
        with patch.dict(os.environ, {"TELEGRAPH_ACCESS_TOKEN": "fake", "CF_R2_ACCOUNT_ID": "fake"}), \
                patch.object(fetcher, "fetch", return_value=article()), \
                patch.object(fetcher, "publish_telegraph") as pub, \
                patch.object(fetcher, "telegraph_token") as token, \
                patch.object(fetcher, "R2Client") as r2:
            self.assertEqual(fetcher.main([URL]), 0)
            self.assertEqual(fetcher.main([URL, "--no-telegraph"]), 0)
            pub.assert_not_called()
            token.assert_not_called()
            r2.assert_not_called()

    def test_publish_is_explicit_and_independent(self):
        with patch.object(fetcher, "fetch", return_value=article()), \
                patch.object(fetcher, "telegraph_token", return_value="fake"), \
                patch.object(fetcher, "publish_telegraph", return_value="https://telegra.ph/test") as pub, \
                patch.object(fetcher, "R2Client") as r2:
            self.assertEqual(fetcher.main([URL, "--publish"]), 0)
            pub.assert_called_once()
            r2.assert_not_called()
        with self.assertRaises(SystemExit):
            fetcher.build_parser().parse_args([URL, "--publish", "--no-telegraph"])

    def test_raw_metadata_hashes_and_revision_preservation(self):
        data = article(author='Author "Quoted"', published="2020-04-05", _fetched_at="2026-10-09T12:00:00+00:00")
        first, _, _ = fetcher.save_markdown(URL, data)
        self.assertEqual(Path(first).with_suffix(".html").read_bytes(), RAW)
        header = Path(first).read_text().split("---\n")[1]
        meta = {k: json.loads(v) for k, v in (line.split(": ", 1) for line in header.splitlines())}
        self.assertEqual(meta["source_url"], URL)
        self.assertEqual(meta["author"], data["author"])
        self.assertEqual(meta["publish_date"], "2020-04-05")
        self.assertEqual(meta["fetched_at"], data["_fetched_at"])
        same, _, _ = fetcher.save_markdown(URL, data)
        other, _, _ = fetcher.save_markdown(URL + "2", data)
        revision, _, _ = fetcher.save_markdown(URL, article(raw=RAW + b"\n"))
        self.assertEqual(first, same)
        self.assertNotEqual(first, other)
        self.assertNotEqual(first, revision)
        self.assertTrue(Path(first).exists())
        unknown = Path(revision).read_text()
        self.assertIn('author: "unknown"', unknown)
        self.assertIn('publish_date: "unknown"', unknown)
        self.assertFalse(list(self.root.rglob("*.part")))

    def test_error_pages_and_insufficient_extractions_fail(self):
        phrases = ["环境异常", "已被发布者删除", "请在微信客户端打开", "captcha", "Access denied", "Just a moment", "该内容无法查看"]
        for phrase in phrases:
            with self.subTest(phrase=phrase), self.assertRaises(ValueError):
                raw = f"<html><title>{phrase}</title><p>{phrase} 请重试</p></html>".encode()
                core.validate_article(raw, {"title": phrase, "content": phrase + " 请重试"})
        for data in ({"title": "", "content": TEXT}, {"title": "Title", "content": "..."}, {"title": "Title", "content": "OK"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                core.validate_article(b"<html></html>", data)

    def test_quoted_phrases_short_and_image_articles_are_valid(self):
        text = '教程解释“环境异常”和“请在微信客户端打开”的含义，并不表示这篇文章本身出错。'
        core.validate_article(f'<article>{text}</article>'.encode(), {"title": "错误提示教程", "content": text})
        core.validate_article(f'<div>{text}</div>'.encode(), {"title": "错误提示教程", "content": text})
        core.validate_article(b'<article>Short notice.</article>', {"title": "Notice", "content": "Short notice."})
        core.validate_article(b'<article><img src="https://example.com/a.png"></article>', {"title": "Photo", "content": "![photo](https://example.com/a.png)"})
        core.validate_article('<script>captcha 环境异常</script><article>'.encode() + TEXT.encode() + b'</article>', article())

    def test_fetch_uses_exact_package_and_cleans_temporary_source(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command[0] == "curl":
                Path(command[-1]).write_bytes(RAW)
                return subprocess.CompletedProcess(command, 0)
            return subprocess.CompletedProcess(command, 0, json.dumps({"title": "Article", "content": TEXT}))
        with patch.object(fetcher.subprocess, "run", side_effect=run):
            data = fetcher.fetch(URL)
        self.assertEqual(data["_raw_html"], RAW)
        self.assertIn("defuddle@0.19.4", calls[1])
        self.assertFalse(Path(calls[0][-1]).exists())

    def test_http_200_junk_never_succeeds_or_publishes(self):
        def run(command, **kwargs):
            if command[0] == "curl":
                Path(command[-1]).write_bytes('<title>环境异常</title><p>环境异常，请验证</p>'.encode())
            return subprocess.CompletedProcess(command, 0, json.dumps({"title": "环境异常", "content": "环境异常，请验证"}))
        with patch.object(fetcher.subprocess, "run", side_effect=run), patch.object(fetcher, "publish_telegraph") as pub:
            self.assertEqual(fetcher.main([URL, "--publish"]), 2)
            pub.assert_not_called()
        self.assertFalse(list(self.root.rglob("*.md")))

    def test_r2_upload_happens_after_local_commit_and_does_not_publish(self):
        image = "![x](https://mmbiz.qpic.cn/x.png)"
        client = FakeR2()
        def fail_upload(path, key):
            self.assertTrue(path.exists())
            self.assertTrue(list(self.root.rglob("*.md")))
            self.assertTrue(list(self.root.rglob("*.html")))
            raise OSError("simulated upload failure")
        client.upload_file = fail_upload
        with patch.object(fetcher, "fetch", return_value=article(content=TEXT + image)), \
                patch.object(fetcher.R2Config, "from_env", return_value=client.config), \
                patch.object(fetcher, "R2Client", return_value=client), \
                patch.object(assets, "_download_image", return_value=(b"\x89PNG\r\n\x1a\nfake", "image/png")), \
                patch.object(fetcher, "publish_telegraph") as pub:
            self.assertEqual(fetcher.main([URL, "--images", "r2"]), 1)
            pub.assert_not_called()
        self.assertEqual(len(list(self.root.rglob("*.png"))), 1)
        self.assertIn("assets/", next(self.root.rglob("*.md")).read_text())

    def test_missing_r2_config_and_telegraph_failure_preserve_archive(self):
        with patch.object(fetcher, "fetch", return_value=article()):
            self.assertEqual(fetcher.main([URL, "--images", "r2"]), 1)
            self.assertEqual(fetcher.main([URL, "--publish"]), 1)
        self.assertTrue(list(self.root.rglob("*.md")))
        self.assertTrue(list(self.root.rglob("*.html")))
        with patch.object(fetcher, "fetch", return_value=article()), \
                patch.object(fetcher, "telegraph_token", return_value="fake"), \
                patch.object(fetcher, "publish_telegraph", side_effect=OSError("simulated")):
            self.assertEqual(fetcher.main([URL, "--publish"]), 1)
        self.assertTrue(list(self.root.rglob("*.md")))

    def test_standalone_requires_opt_in_and_understands_frontmatter(self):
        path, _, _ = fetcher.save_markdown(URL, article(author="A", published="2021-01-01"))
        with patch.object(publisher, "publish", return_value="https://telegra.ph/test") as pub, \
                patch.object(publisher, "telegraph_token", return_value="fake"):
            with self.assertRaises(SystemExit):
                publisher.main([path])
            pub.assert_not_called()
            self.assertEqual(publisher.main([path, "--publish"]), 0)
            args = pub.call_args.args
            self.assertEqual(args[:3], ("Same title", "A", URL))
            self.assertNotIn("fetched_at:", args[3])
        Path(path).write_text("# Local images\n\n![local](assets/photo.png)")
        with patch.object(publisher, "publish") as pub:
            self.assertEqual(publisher.main([path, "--publish"]), 1)
            pub.assert_not_called()

    def test_atomic_write_failure_leaves_existing_snapshot_and_no_parts(self):
        path = self.root / "keep.md"
        path.write_text("original")
        with patch.object(core.os, "replace", side_effect=OSError("simulated disk error")):
            with self.assertRaises(OSError):
                core.atomic_write(path, "replacement")
        self.assertEqual(path.read_text(), "original")
        self.assertFalse(list(self.root.glob("*.part")))

    def test_download_cap_referer_retry_and_non_image_rejection(self):
        class Response(io.BytesIO):
            headers = {"Content-Type": "image/png"}
        requests = []
        def too_large(request, **kwargs):
            requests.append(request)
            return Response(b"\x89PNG\r\n\x1a\n" + b"x" * 50)
        with patch.object(assets, "urlopen", side_effect=too_large), patch.object(assets.time, "sleep"):
            with self.assertRaises(assets.ImageAssetError):
                assets._download_image("https://mmbiz.qpic.cn/x", URL, max_bytes=20)
        self.assertEqual(assets.DEFAULT_MAX_IMAGE_BYTES, 20 * 1024 * 1024)
        self.assertEqual(len(requests), 4)
        self.assertEqual({r.get_header("Referer") for r in requests}, {URL, "https://mp.weixin.qq.com/"})
        self.assertEqual(len({r.get_header("User-agent") for r in requests}), 2)
        with patch.object(assets, "urlopen", side_effect=lambda *a, **k: Response(b"<html>captcha</html>")), patch.object(assets.time, "sleep"):
            with self.assertRaises(assets.ImageAssetError):
                assets._download_image("https://mmbiz.qpic.cn/x", URL)

    def test_failed_image_rename_cleans_part_and_retains_original_url(self):
        md = "![x](https://mmbiz.qpic.cn/a.png)"
        with patch.object(assets, "_download_image", return_value=(b"\x89PNG\r\n\x1a\ndata", "image/png")), \
                patch.object(assets.os, "replace", side_effect=OSError("disk")):
            result = assets.rewrite_images(md, self.root, "test", URL)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.local_markdown, md)
        self.assertFalse(list(self.root.rglob("*.part")))

    def test_successful_explicit_r2_changes_only_publication_copy(self):
        client = FakeR2()
        image = "![one](https://mmbiz.qpic.cn/a.png)"
        with patch.object(fetcher.R2Config, "from_env", return_value=client.config), \
                patch.object(fetcher, "R2Client", return_value=client), \
                patch.object(assets, "_download_image", return_value=(b"\x89PNG\r\n\x1a\nfake", "image/png")):
            path, public, result = fetcher.save_markdown(URL, article(content=TEXT + image), "r2")
        self.assertEqual(result.uploaded, 1)
        self.assertIn("https://pub.example.r2.dev/", public)
        self.assertIn("assets/", Path(path).read_text())
        self.assertNotIn("https://pub.example.r2.dev/", Path(path).read_text())

    def test_long_multilingual_title_and_invalid_schema(self):
        path, _, _ = fetcher.save_markdown(URL, article(title="很长的中文标题" * 30))
        self.assertLess(len(Path(path).name.encode()), 255)
        for data in ([], {"title": [], "content": TEXT}, {"title": "Title", "content": {}}):
            with self.assertRaises(ValueError):
                core.validate_article(RAW, data)

    def test_invalid_r2_public_urls_are_rejected(self):
        for base in ["http://public.example", "https://a.r2.cloudflarestorage.com", "https://user:secret@example.com", "https://example.com/?token=x"]:
            with self.subTest(base=base), self.assertRaises(ValueError):
                assets.R2Config("a", "b", "c", "bucket", base)


if __name__ == "__main__":
    unittest.main()
