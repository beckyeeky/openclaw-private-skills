#!/usr/bin/env python3
"""Small standard-library tests for the article image pipeline."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from image_assets import R2Client, R2Config, make_slug, rewrite_images


class FakeR2:
    def __init__(self):
        self.config = R2Config(
            account_id="a" * 32,
            access_key_id="access-key",
            secret_access_key="secret-key",
            bucket="wechat-images",
            public_base_url="https://pub.example.r2.dev",
            key_prefix="wechat",
        )
        self.uploads = []

    def upload_file(self, local_path: Path, key: str) -> None:
        self.uploads.append((local_path.name, key))

    def public_url(self, key: str) -> str:
        return self.config.public_base_url + "/" + key


def main() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp)
        markdown = (
            "before\n\n"
            "![one](https://mmbiz.qpic.cn/a.jpg)\n\n"
            "![same](https://mmbiz.qpic.cn/a.jpg)\n\n"
            "![two](https://mmbiz.qpic.cn/b.webp)\n"
        )
        fake_downloads = {
            "https://mmbiz.qpic.cn/a.jpg": (b"\xff\xd8\xfffake", "image/jpeg"),
            "https://mmbiz.qpic.cn/b.webp": (b"RIFFxxxxWEBPdata", "image/webp"),
        }

        def fake_download(url, source_page_url, max_bytes, timeout=30):
            return fake_downloads[url]

        with patch("image_assets._download_image", side_effect=fake_download):
            result = rewrite_images(
                markdown,
                root,
                make_slug("测试文章"),
                "https://mp.weixin.qq.com/s/example",
                mode="local",
            )

        assert result.discovered == 2
        assert result.downloaded == 2
        assert result.failed == 0
        assert result.local_markdown.count("assets/测试文章/") == 3
        assert len(list((root / "assets" / "测试文章").iterdir())) == 2
        assert result.publication_markdown.count("https://mmbiz.qpic.cn/") == 3

        fake_r2 = FakeR2()
        with patch("image_assets._download_image", side_effect=fake_download):
            r2_result = rewrite_images(
                markdown,
                root,
                make_slug("测试文章"),
                "https://mp.weixin.qq.com/s/example",
                mode="r2",
                r2_client=fake_r2,
            )
        assert r2_result.discovered == 2
        assert r2_result.downloaded == 2
        assert r2_result.uploaded == 2
        assert len(fake_r2.uploads) == 2
        assert "https://pub.example.r2.dev/wechat/测试文章/" in r2_result.publication_markdown

        # A failed download must not prevent the article Markdown from being
        # generated or count as a successful local asset.
        with patch("image_assets._download_image", side_effect=RuntimeError("network")):
            failed = rewrite_images(
                "![bad](https://mmbiz.qpic.cn/bad.jpg)",
                root,
                "failed",
                "https://mp.weixin.qq.com/s/example",
                mode="local",
            )
        assert failed.discovered == 1
        assert failed.downloaded == 0
        assert failed.failed == 1
        assert "https://mmbiz.qpic.cn/bad.jpg" in failed.local_markdown

    try:
        R2Config.from_env()
    except ValueError as exc:
        assert "CF_R2_ACCOUNT_ID" in str(exc)
    else:
        raise AssertionError("missing R2 environment must be rejected")

    config = R2Config(
        account_id="a" * 32,
        access_key_id="access-key",
        secret_access_key="secret-key",
        bucket="wechat-images",
        public_base_url="https://pub.example.r2.dev/",
    )
    client = R2Client(config)
    url, headers = client._authorization("wechat/test.jpg", b"abc", "image/jpeg")
    assert url.endswith("/wechat-images/wechat/test.jpg")
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert "secret-key" not in headers["Authorization"]
    print("image_assets tests: OK")


if __name__ == "__main__":
    main()
