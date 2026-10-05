---
name: x-tweet-image-merge
version: 2.0.0
description: Merge photos from one X/Twitter post into a downloadable horizontal PNG. Use for /x-tweet-image-merge followed by a post URL, or requests to merge tweet images; also supports creating or installing the bundled Tampermonkey userscript when explicitly requested.
---

# X Tweet Image Merge

## Route by intent

- **Post URL / merge or download images (default):** produce the actual merged PNG, not userscript code.
- **Explicit Tampermonkey / userscript / install or customize request:** read [userscript workflow](references/userscript.md), then use the real bundled asset.
- No post URL for direct export: request the target post URL. Do not apply this skill to unrelated web images.

## Direct PNG workflow

1. Check `python3`, `curl`, `minis-browser-use`, and `from PIL import Image`; install missing Alpine packages (`py3-pillow`, `curl`) only as needed.
2. Run `python3 {baseDir}/scripts/merge_tweet.py 'POST_URL'`. It opens its own tab. If no tab slot is available, inspect `minis-browser-use list_tabs` and pass `--tab-id N` for a tab you own. Never guess tab IDs or change another agent's tab.
3. If a reliable user-provided or target-specific count is known, pass `--expected-count N`. Never infer total count from all page images. The extractor scopes numbered `/status/ID/photo/N` links inside tweet photo nodes, sorts and deduplicates, and excludes other tweet IDs (quotes/replies).
4. Accept only `status=ok`: inspect `photo_count`, `source_sizes`, `width`, `height`, `bytes`, and `completeness`. Return the PNG using the reported `minis_url`. One photo is exported as one PNG. Downloads request original media; no resizing, top-aligned white background, PNG without expensive optimization.
5. Be honest: DOM-visible photos are not proof of a complete carousel. If total count is unknown, state the number actually exported, not “all photos”. Failed expected count/gapped order must not be called success. Video-only posts yield no photo export; do not substitute video frames.

No screenshots, viewport changes, UA switches or whole-page image scans by default. Bounded retries only cover absent/incomplete media (at most three extraction attempts). For login blocks, virtualized cards, changed markup, resource limits or download failures, read [direct troubleshooting](references/direct.md); do not repeat blindly.

## Maintenance

Run `node {baseDir}/tests/extract.test.js` and `python3 {baseDir}/tests/test_merge.py`; check userscript syntax with `node --check {baseDir}/assets/x-tweet-horizontal-merge.user.js`. Preserve the userscript capability and asset when updating the default direct-export route.
