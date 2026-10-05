# Direct export troubleshooting

The command prints one JSON object and exits nonzero on failure. `execute_js` CLI output is a JSON envelope whose `data.text` starts with the returned JSON and may append `tab_id`; the script decodes the first JSON value, not the whole text.

- Login/access blocks or missing target article: inspect target DOM or ask the user to log in. Do not claim the post has no photos when the post itself did not render.
- Virtualized carousel: visible numbered links cannot prove a total count, especially missing trailing cards. Inspect the target carousel, optionally swipe it manually, and rerun with a reliable `--expected-count`. Do not scan unrelated articles or make unlimited retries.
- No photos + video node: reports no photo export; the video node may belong to a quote, so it is not definitive proof the target is video-only.
- Curl failure or corrupt media: nonzero exit; no new final PNG is published. Existing output from previous runs is not evidence of success.
- Outputs above 150 million pixels are refused, not resized. Individual images are decoded with Pillow's standard decompression-bomb protections.
- Script-created tabs are left open for inspection. Close the tab you created when finished; existing `--tab-id` tabs stay owned by the caller.

`--output /var/minis/attachments/name.png` controls destination. Use a path beneath `/var/minis/` for a tappable result URL. Transparent inputs are composited onto white; pixel dimensions are preserved (no EXIF rotation or rescaling). No browser cookies or tokens are exported.
