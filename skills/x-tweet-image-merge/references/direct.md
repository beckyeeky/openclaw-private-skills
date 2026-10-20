# Direct export troubleshooting

The command prints one JSON object and exits nonzero on failure. `execute_js` CLI output is a JSON envelope whose `data.text` starts with the returned JSON and may append `tab_id`; the script decodes the first JSON value, not the whole text.

## Channels

- `metadata` (default under `--via auto`): `https://cdn.syndication.twimg.com/tweet-result?id=<ID>&token=a`. No login, cookie or browser. Uses only top-level `photos`, else top-level `mediaDetails` filtered to `type=photo` with `ext_media_availability.status=Available`. Quotes/replies are never traversed; dedupe keys on the media path because the endpoint rewrites every `expanded_url` to `.../photo/1`; order is the array order (`/photo/1..N`).
- `browser`: `minis-browser-use` DOM extraction, the only channel that sees login, age-gate or sensitive-content posts.
- `--via metadata` / `--via browser`: no cross-channel fallback, must fail loudly.
- `--verify-both`: runs both, metadata stays authoritative, disagreement lands in `completeness.mismatch` (never silently pick the smaller count).

Metadata raises a legal fallback only for: HTTP 404, tombstone, `photos` + `mediaDetails` both missing, or 429/5xx/timeout/non-JSON twice. Anything else — an unexpected status, or a tweet whose media fields stopped parsing (`SchemaDrift`) — is a hard error, never "0 photos". One retry maximum, no loops.

## Failures

- Login/access blocks or missing target article: inspect target DOM or ask the user to log in. Do not claim the post has no photos when the post itself did not render.
- Virtualized carousel: visible numbered links cannot prove a total count, especially missing trailing cards. Inspect the target carousel, optionally swipe it manually, and rerun with a reliable `--expected-count`. Do not scan unrelated articles or make unlimited retries.
- No photos + video node: reports no photo export; the video node may belong to a quote, so it is not definitive proof the target is video-only.
- Curl failure or corrupt media: nonzero exit; no new final PNG is published. Existing output from previous runs is not evidence of success.
- Outputs above 150 million pixels are refused, not resized. Individual images are decoded with Pillow's standard decompression-bomb protections.
- Script-created tabs are left open for inspection. Close the tab you created when finished; existing `--tab-id` tabs stay owned by the caller.

## Output path

`--output` > `MINIS_ATTACHMENTS_DIR` > `./x-<tweet_id>-merged.png`. `output` is always absolute; `minis_url` appears only when the file really sits under `/var/minis` or `MINIS_ATTACHMENTS_DIR`, and is never fabricated. No browser cookies or tokens are exported.

## Layout and blank area

Blank area is geometry, not a layout bug: `white_pct = 1 − (photo area ÷ canvas area)`. Re-grouping photos cannot change it — with two 1152×2048 portraits and two 2048×1152 landscapes, `row`, `grid` and `stack` all report 28.0%, only the shape of the gap moves. Compact the canvas by resampling or do not merge at all.

- `--layout auto` (default): equal heights → `row`, pixel-exact, `resampled=false`, `white_pct=0`. Mixed heights → `fit` to the smallest height (downscale only, never invent pixels), `resampled=true`, `scale_factors` per photo, `white_pct=0`.
- `--layout row|grid|stack`: original pixels, honest `white_pct`. `grid` uses `ceil(sqrt(n))` columns.
- `--fit-height min|max|<px>`: `min` never upscales; `max` keeps the tallest and upscales the rest; a number forces that height.
- `--background white|black|transparent`: transparent keeps RGBA (gaps become alpha 0) instead of painting white.
- `--singles`: writes each source photo untouched as `x-<id>-NN.<ext>` beside the merged PNG and lists them under `singles`. Best answer when the user cares about the originals.

Pixel dimensions are otherwise preserved (no EXIF rotation). Outputs above 150 million pixels are refused before encoding.
