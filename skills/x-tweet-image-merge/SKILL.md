---
name: x-tweet-image-merge
version: 2.1.0
description: Merge photos from one X/Twitter post into a downloadable horizontal PNG. Use for /x-tweet-image-merge followed by a post URL, or requests to merge tweet images; also supports creating or installing the bundled Tampermonkey userscript when explicitly requested.
---

# X Tweet Image Merge

## Route by intent

- **Post URL / merge or download images (default):** produce the actual merged PNG, not userscript code.
- **Explicit Tampermonkey / userscript / install or customize request:** read [userscript workflow](references/userscript.md), then use the real bundled asset.
- No post URL for direct export: request the target post URL. Do not apply this skill to unrelated web images.

## Direct PNG workflow

1. Check `python3`, `curl` and `from PIL import Image`; install missing Alpine packages (`py3-pillow`, `curl`) only as needed. `minis-browser-use` is optional: without it the metadata channel still exports every public post.
2. Run `python3 {baseDir}/scripts/merge_tweet.py 'POST_URL'`. Default `--via auto` asks X's syndication `tweet-result` endpoint first — no tab, no cookies, no login, and the photo count is declared by the platform instead of inferred from the DOM.
3. Only `--via auto` degrades: if metadata returns HTTP 404, a tombstone, no `photos`/`mediaDetails`, or twice 429/5xx/timeout/non-JSON, and `minis-browser-use` exists, it falls back to the browser channel and reports `fallback_reason`. `--via metadata` and `--via browser` never cross over; `--via browser` opens its own tab, and if no tab slot is available inspect `minis-browser-use list_tabs` and pass `--tab-id N` for a tab you own. Never guess tab IDs or change another agent's tab.
4. If a reliable user-provided or target-specific count is known, pass `--expected-count N`. Never infer total count from all page images. `--verify-both` runs both channels, keeps metadata authoritative and sets `completeness.mismatch` when the DOM disagrees.
5. Accept only `status=ok`: inspect `source`, `photo_count`, `source_sizes`, `width`, `height`, `bytes` and `completeness`. Deliver the PNG from the absolute `output` path; `minis_url` is present only when the file really lives under a minis mount. One photo is exported as one PNG. Downloads request original media; no resizing, top-aligned white background, PNG without expensive optimization.
6. Be honest: `photo_count` is the number actually downloaded and merged, and `completeness.total_from_metadata` is what the platform declared. Do not write “all photos” unless those two agree. Failed expected count or a gapped photo sequence must not be called success. Video-only posts yield `no photos visible; video present`; do not substitute video frames.

No screenshots, viewport changes, UA switches or whole-page image scans by default. Bounded retries only cover absent/incomplete media (at most three DOM extraction attempts, one metadata retry). For login blocks, virtualized cards, changed markup, resource limits or download failures, read [direct troubleshooting](references/direct.md); do not repeat blindly.

## Maintenance

Run `node {baseDir}/tests/extract.test.js` and `python3 {baseDir}/tests/test_merge.py`; check userscript syntax with `node --check {baseDir}/assets/x-tweet-horizontal-merge.user.js`. Preserve the userscript capability and asset when updating the default direct-export route.
