#!/usr/bin/env python3
"""Convert archived Markdown into Telegraph Node arrays.

This is the single implementation shared by ``fetch-wechat.py`` (direct
publication after fetching) and ``publish-telegraph.py`` (publishing an
existing Markdown file).  Both entry points used to carry their own copy of the
converter, and both copies treated any image line that also contained longer
text as a plain paragraph, leaking literal ``![alt](url)`` Markdown into the
published page.

Contract:
- Every Markdown image becomes an ``<img>`` node at the position it occupies
  in the source line; surrounding text on that line is preserved as its own
  paragraph(s) before/after the image.  A line only becomes a single paragraph
  or heading when it contains no image.
- ``figcaption`` is emitted only when the image has alternative text.
- The image URL is taken verbatim from the shared ``MARKDOWN_IMAGE_RE`` match
  (query strings preserved); the module never rewrites or normalises URLs.
"""

from __future__ import annotations

from image_assets import MARKDOWN_IMAGE_RE, _extract_url

# Lines that carry WeChat chrome instead of article content.  Matched exactly,
# so legitimate body text is never removed.
SKIP_LINES = {
    "李姝 李姝", "在小说阅读器读本章", "去阅读",
    "微信扫一扫", "微信扫一扫  ", "使用小程序",
    "继续滑动看下一个", "潇湘晨报", "向上滑动看下一个",
}


def _image_node(alt: str, src: str) -> dict:
    image = {"tag": "img", "attrs": {"src": src}}
    if alt:
        return {"tag": "figure", "children": [
            image, {"tag": "figcaption", "children": [alt]},
        ]}
    return image


def _paragraph_nodes(text: str) -> list:
    text = text.strip()
    return [{"tag": "p", "children": [text]}] if text else []


def _plain_line_nodes(line: str) -> list:
    """Heading / paragraph handling for lines without any image."""
    if line.startswith("## "):
        return [{"tag": "h3", "children": [line[3:].strip("**")]}]
    if line.startswith("**") and line.endswith("**") and len(line) > 4:
        return [{"tag": "h4", "children": [line.strip("*")]}]
    return [{"tag": "p", "children": [line]}]


def md_to_telegraph_nodes(md_text: str) -> list:
    """Convert Markdown text into a Telegraph Node array."""
    nodes: list = []
    for raw_line in md_text.split("\n"):
        line = raw_line.strip()
        if not line or line in SKIP_LINES:
            continue
        matches = list(MARKDOWN_IMAGE_RE.finditer(line))
        if not matches:
            nodes.extend(_plain_line_nodes(line))
            continue
        # Keep images in place and keep whatever text surrounds them.
        position = 0
        for match in matches:
            nodes.extend(_paragraph_nodes(line[position:match.start()]))
            nodes.append(_image_node(match.group(1), _extract_url(match.group(2))))
            position = match.end()
        nodes.extend(_paragraph_nodes(line[position:]))
    return nodes


__all__ = ["md_to_telegraph_nodes", "SKIP_LINES"]
