---
name: bilibili-hub
description: >
  A skill for reading and writing Bilibili data with Python + UV, using bilibili-api-python + aiohttp.
  It automatically obtains cookies through `browser_use get_cookies` for authentication, so no manual copying is required.
  Supports video details, subtitles, AI summaries, comments, user profiles, search, popular videos/rankings, following dynamics feed,
  favorites, Watch Later, viewing history, interactions (likes, coins, triple action), publishing and deleting dynamics, and more.
  When a user mentions "Bilibili," "bilibili," "Bilibili videos," "Bilibili popular," "bilibili-hub,"
  "get Bilibili data," "Bilibili subtitles," "Bilibili comments," "Bilibili favorites," "Bilibili dynamics,"
  or any scenario that requires programmatically reading or writing Bilibili content, this skill must be triggered.
---

# bilibili-hub

> **Modified from**: [jackwener/bilibili-cli](https://github.com/jackwener/bilibili-cli) (Apache-2.0)
>
> This skill simplifies and modifies the original repository as follows:
> - Removed the `browser-cookie3` / `click` / `rich` / `PyYAML` / `qrcode` dependencies
> - Changed cookie authentication to accept a `dict` directly or read from environment variables, without automatic browser extraction
> - Removed the CLI layer (`commands/`), QR login, formatters, and related components
> - Kept all API methods and wrapped them uniformly as synchronous interfaces (`asyncio.run`)
> - Core dependency: `bilibili-api-python`, a third-party SDK that reverse engineers the Bilibili API
> - In the Minis environment, cookies are obtained automatically through `browser_use get_cookies`

---

## File Structure

```text
{baseDir}/                          # 本技能目录（Minis 中为 /var/minis/skills/bilibili-hub）
├── SKILL.md
├── pyproject.toml          # bilibili-api-python (>=17.4,<18) + aiohttp
├── uv.lock                 # 锁定依赖（与 pyproject.toml 约束一致）
├── env.sh                  # 可选：把 BILI_COOKIE 拆成 BILI_SESSDATA/BILI_JCT/... 分字段变量
├── scripts/
│   ├── __init__.py
│   ├── exceptions.py       # 6 structured exception types
│   ├── payloads.py         # Data structure normalization (normalize_* functions)
│   └── client.py           # BiliClient core class (all API methods)
└── tests/
    └── test_contract.py    # 离线 mock 契约测试（公开方法返回规范 + 异常行为，无网络/无真实凭据）
```

路径一律相对 `{baseDir}` 解析，不要假设固定的 checkout 路径。

---

## Authentication Methods

使用单一环境变量 `BILI_COOKIE` 保存完整 Cookie 请求头：

```text
BILI_COOKIE="SESSDATA=...; bili_jct=...; DedeUserID=...; buvid3=..."
```

`BiliClient.from_env()` 优先读取 `BILI_COOKIE` 并解析全部 Cookie；未设置时兼容旧变量。创建客户端后调用 `client.validate_cookie()` 验证登录状态。验证失败时，应通过浏览器重新获取 Cookie，并覆盖写入环境变量 `BILI_COOKIE`，然后重新创建客户端验证。

Cookie 刷新由调用方完成，因为浏览器 Cookie 获取和环境变量写入属于 Minis 运行时操作。推荐流程：

1. 打开 `https://www.bilibili.com`，确认已登录。
2. 调用浏览器 Cookie 获取功能。
3. 在不输出 Cookie 值的情况下，将全部 `COOKIE_*` 变量拼接为 Cookie 请求头。
4. 通过 Minis 环境变量设置界面覆盖 `BILI_COOKIE`。
5. 使用 `BiliClient.from_env(validate=True)` 重新验证。

### Ways to pass cookies

```python
client = BiliClient.from_env()
me = client.validate_cookie()
```


---

## Quick Start

### Environment setup

在技能目录（`{baseDir}`，Minis 中为 `/var/minis/skills/bilibili-hub`）下执行：

```bash
cd {baseDir}
uv sync
```

`pyproject.toml` 与 `uv.lock` 都固定在 `bilibili-api-python 17.4.x`（`>=17.4,<18`），
代码中的所有 SDK 调用形态均按 17.4.2 的签名编写；不要依赖“任意最新版本”漂移。

### Running the offline contract tests

```bash
cd {baseDir}
python3 -m unittest discover -s tests -v
```

测试完全离线：SDK 符号与 `aiohttp` 会话都被替身接管，不需要 Cookie，也不会发起任何真实请求。

### Calling as a Python library

```python
import sys
sys.path.insert(0, "{baseDir}")   # 替换为实际技能目录，如 /var/minis/skills/bilibili-hub
from scripts.client import BiliClient

client = BiliClient.from_env()

# Current user information
me = client.whoami()
print("User:", me.get("name"), "UID:", me.get("id"))

# Search videos
videos = client.search_videos("Python Tutorial", count=5)
for v in videos:
    print(f"  {v['bvid']} {v['title']} ({v['duration']})")

# Get video details (including subtitles)
detail = client.get_video("BV1xx411c7mD", subtitle=True)
print(detail["video"]["title"])
print(detail["subtitle"]["text"][:200])
if detail["warnings"]:
    print("degraded features:", detail["warnings"])

# Popular videos
hot = client.get_hot(count=10)
for v in hot:
    print(f"  {v['bvid']} {v['title']} 👁{v['stats']['view']}")
```

---

## API Method Quick Reference

### Account

| Method | Description |
|------|------|
| `whoami()` | Get information about the currently logged-in user (SDK `user.get_self_info`) |
| `validate_cookie()` | Verify the current Cookie still works (same call as `whoami()`; raises `AuthenticationError` when missing/expired) |

### Video

| Method | Description |
|------|------|
| `get_video(bvid, *, subtitle, subtitle_timeline, ai_summary, comments, related)` | Get video details (optional subtitles/AI summary/comments/related videos) |

`bvid` supports a BV number or full URL and is extracted automatically.

`get_video` returns `video` / `subtitle` / `ai_summary` / `comments` / `related` / `warnings`.
`comments=True` uses the comment **list** API (`comment.get_comments`). When an optional extra is
requested and the interface call *succeeds* but carries no usable content (e.g. the AI-summary
response has an empty `model_result.summary`), the payload keeps the empty value **and** appends an
**observation** entry to `warnings` — it never asserts a reason the code cannot prove. Real failures
raise a `BiliError` subclass instead of silently degrading, and no error code is interpreted as
"this video has no AI summary".

### Users

| Method | Description |
|------|------|
| `get_user(uid)` | Get user profile information + following/follower counts |
| `get_user_videos(uid, count=20)` | Get videos posted by a user |

### Search

| Method | Description |
|------|------|
| `search_videos(keyword, page=1, count=20)` | Search videos |
| `search_users(keyword, page=1)` | Search users |

### Discover

| Method | Description |
|------|------|
| `get_hot(page=1, count=20)` | Site-wide popular videos |
| `get_rank(day=3, count=50)` | **Site-wide** video ranking (`RankType.All`). `day` is a **deprecated no-op** kept for call compatibility: the pinned SDK only passes `day` to the PGC (bangumi) chart, so the all-site chart ignores it and every `day` value returns the same data |
| `get_feed(offset=None)` | Followed **dynamic items** feed (login required); returns the raw SDK dict with `items` / `offset` / `has_more` |
| `get_my_dynamics(offset=0)` | Dynamics I published (login required), one page as a normalized list. **Legacy contract**: **int** cursor from the old `space_history` API (`cards` / `next_offset`) |
| `get_my_dynamics_page(offset="")` | Independent **new** API (`polymer/web-dynamic/v1/feed/space`), **str** cursor: `{"items", "offset", "has_more"}` |
| `post_dynamic(text)` | Post a text dynamic (login + `bili_jct` required) |
| `delete_dynamic(dynamic_id)` | Delete a dynamic (login + `bili_jct` required) |

Dynamic paging: `get_feed(offset=...)` and `get_my_dynamics_page(offset=...)` take the `offset`
returned by the previous page (`None`, `0` and `""` all mean "first page"; string cursors are
forwarded unchanged — they may be large integers that must not be re-parsed). `get_my_dynamics()`
is a **separate legacy path** whose cursor is an **int** (`next_offset` of the old `space_history`
API); the two cursor types are **not interchangeable**. `get_feed` returns **dynamic items**, not
the list of followed UPs. `published_at` is filled from `modules.module_author.pub_ts` (new polymer
items) or the legacy `desc.timestamp`, and stays `""` only when neither exists.

### Favorites / History

| Method | Description |
|------|------|
| `get_favorites()` | Get the favorites folder list (login required) |
| `get_favorites(folder_id)` | Get videos in a favorites folder |
| `get_following(page=1)` | Get the following list (login required) |
| `get_watch_later()` | Get the Watch Later list (login required) |
| `get_history()` | Get viewing history (login required) |

### Download

| Method | Description |
|------|------|
| `download_video(bvid, output_dir, filename=None)` | Download the full video (`mp4`), automatically handling DASH merging |
| `download_audio(bvid, output_dir, filename=None)` | Download only the audio stream (`m4a`), suitable for ASR transcription |

**Download process**:
- DASH streams (common): download the video stream and audio stream separately -> merge with `ffmpeg copy` -> if merging fails, keep the silent video
- FLV/MP4 streams (rare): download directly, no merging required
- Without logging in, downloads are limited to 480P; after logging in, 1080P is available (premium members can download higher quality)

### Interactions

| Method | Description |
|------|------|
| `like(bvid)` / `like(bvid, undo=True)` | Like / unlike (requires `bili_jct`) |
| `coin(bvid, num=1)` | Give 1 or 2 coins (requires `bili_jct`) |
| `triple(bvid)` | Perform the one-click triple action (requires `bili_jct`) |
| `unfollow(uid)` | Unfollow a user (requires `bili_jct`) |

---

## Error Handling

```python
from scripts.exceptions import (
    AuthenticationError,  # Cookie missing or expired
    RateLimitError,       # Triggered risk control (412)
    NotFoundError,        # Video/user does not exist
    NetworkError,         # Network/timeout error
    InvalidBvidError,     # Invalid BV number format
    BiliError,            # Other API error (base class)
)

try:
    detail = client.get_video("BV1xx411c7mD")
except AuthenticationError:
    print("Cookie has expired. Please retrieve it again.")
except RateLimitError:
    print("Risk control triggered. Try again later.")
except NotFoundError:
    print("Video does not exist.")
except BiliError as e:
    print(f"API error: {e}")
```

---

## Important Notes

- `SESSDATA` is the minimum requirement for read operations. Write operations (likes, coins, posting dynamics) also require `bili_jct`.
- Cookies are usually valid for several days to several weeks. After they expire, retrieve them again through `browser_use get_cookies`.
- Bilibili applies risk control to high-frequency requests (HTTP 412). An operation interval of at least 1 second is recommended.
- Failures are surfaced, not swallowed: authentication/rate-limit/network/API errors raise the structured exceptions above. A legitimate empty result (no comments, no history, no subtitles) is returned as an empty value. For optional extras, `get_video(...)["warnings"]` may additionally carry an **observation** entry, and only when the interface call itself succeeded but contained no usable content (or no `cid` was available). Warnings **never** assert a reason the code cannot prove — e.g. no error code is treated as "this video has no AI summary"; the SDK-invented generic code `-1` is raised as an error like any other unexpected code.
- `env.sh` is optional and only splits `BILI_COOKIE` into per-field variables for callers that need them; it no longer sets any TLS/SSL switch (the old `BILI_SSL_VERIFY=0` export had no consumer and was removed — TLS verification is never disabled by this skill).
- Pinned dependency: `bilibili-api-python>=17.4,<18`. The calls in `scripts/client.py` follow 17.4.2 signatures (`comment.get_comments`, `Video.get_ai_conclusion(cid=...)`, `user.get_toview_list`, `dynamic.get_dynamic_page_info`, `User.get_dynamics(offset: int)`, `User.get_dynamics_new(offset: str)`, `rank.get_rank(type_=RankType.All)`); upgrading the SDK requires re-checking them against the new signatures.
- The offline contract tests under `tests/` use mock stand-ins for most behaviour checks: they pin *this client's* contract under **assumed** response shapes and are **not** evidence of what Bilibili actually returns. Only the signature-compliance tests and the request-parameter snapshot test touch the real SDK (verifying call/request shape, still not real responses).
- `bilibili-api-python` is a community-maintained reverse-engineering project, and its interfaces may break when Bilibili updates.
- Write operations (coins, triple action, etc.) cannot be reversed. Use them with caution.
