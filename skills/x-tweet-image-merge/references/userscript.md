# Tampermonkey branch

Only select this workflow for an explicit userscript/install/customize request. Copy `assets/x-tweet-horizontal-merge.user.js` into the requested repository or provide it for installation; do not replace the user's ordinary post-URL request with code.

Preserve `@grant GM_xmlhttpRequest` and `@connect pbs.twimg.com`: download blobs before Canvas export to avoid tainting. Preserve native left-click and ScrollSnap gestures; stop propagation only on the action overlay button. Select `tweetPhoto` links matching the same `/status/ID/photo/N`, order by N and ignore quoted posts. Request `name=orig`, align at the top, and uniformly scale only when Canvas would exceed its 16,384-pixel edge limit.

The existing asset intentionally shows its merge button only on multi-image posts. If missing, allow carousel rendering or swipe once. Prefer stable test IDs and numbered photo links over generated CSS classes. Run `node --check assets/x-tweet-horizontal-merge.user.js`; a live multi-photo check is recommended when customizing the asset. The direct Python branch, unlike the Canvas branch, never silently scales.
