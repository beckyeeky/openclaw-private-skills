---
name: x-tweet-image-merge
description: Create, adapt, or install a Tampermonkey userscript that collects all images in a single X/Twitter post, stitches them horizontally, and downloads one PNG. Use when a user asks to combine, merge, stitch, or download the multiple images in an X/Twitter tweet, including X's ScrollSnap carousel layout.
---

# X Tweet Image Merge

Use the bundled userscript at `{baseDir}/assets/x-tweet-horizontal-merge.user.js` as the default deliverable. It preserves X's native image click and swipe behavior, adds a **横向合并下载** button to multi-image posts, downloads original media through `GM_xmlhttpRequest`, and saves a horizontally stitched PNG.

## Workflow

1. Copy the bundled asset into the requested userscript repository or provide its contents for manual Tampermonkey installation. Do not reimplement it unless the user needs a behavior change.
2. Keep the `@grant GM_xmlhttpRequest` and `@connect pbs.twimg.com` metadata. Canvas export requires downloading images as blobs first; normal page `fetch()` can produce a tainted canvas.
3. Preserve native left-click and ScrollSnap gesture behavior. Put the action in an overlay button and stop propagation only for that button.
4. Extract only images beneath `data-testid="tweetPhoto"` whose containing link is a `/status/<id>/photo/<n>` URL. Sort by `<n>` and ignore media from quoted tweets.
5. Request each `pbs.twimg.com/media/...` image with `name=orig`, preserve each image's aspect ratio, align them at the top, and encode one PNG. Scale uniformly only when Canvas would exceed its 16,384-pixel edge limit.
6. Validate changes with `node --check <userscript>`; if live X access is available, also test a two-or-more-image post in the current carousel layout.

## Troubleshooting

- If the action button is missing, wait for X to render all carousel cards or swipe through the post once; X may virtualize unloaded media.
- If a single-image post shows no button, this is intentional: horizontal merging needs at least two images.
- If X changes its markup, inspect a live post first. Prefer `data-testid="tweetPhoto"`, `pbs.twimg.com/media/`, and `/photo/N` rather than generated CSS class names.
