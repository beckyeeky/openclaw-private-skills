"""
Bilibili API Client — 基于 bilibili-api-python 的异步封装。

改造来源：jackwener/bilibili-cli
https://github.com/jackwener/bilibili-cli/blob/main/bili_cli/client.py

主要改动：
- 移除 browser-cookie3 / click / rich / PyYAML / qrcode 依赖
- 认证改为直接传入 Cookie dict，不做浏览器自动提取
- 移除 QR 登录、formatter 等 CLI 层代码
- 保留全部 API 方法，统一用 asyncio.run() 提供同步接口
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

import aiohttp
from bilibili_api import comment, dynamic, favorite_list, hot, rank, search, user, video
from bilibili_api.utils.network import Credential

# 兼容 bilibili-api-python 17.x 异常体系
try:
    from bilibili_api.exceptions import (
        ApiException, CredentialNoBiliJctException, CredentialNoSessdataException,
        NetworkException, ResponseCodeException, ResponseException,
    )
except ImportError:
    # 17.x 部分异常路径不同，用基类兜底
    ApiException = Exception
    CredentialNoBiliJctException = Exception
    CredentialNoSessdataException = Exception
    NetworkException = Exception
    ResponseCodeException = Exception
    ResponseException = Exception

from .exceptions import (
    AuthenticationError,
    BiliError,
    InvalidBvidError,
    NetworkError,
    NotFoundError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

_BVID_RE = re.compile(r"\bBV[0-9A-Za-z]{10}\b")


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def extract_bvid(url_or_bvid: str) -> str:
    """从 URL 或字符串中提取 BV 号。"""
    match = _BVID_RE.search(url_or_bvid)
    if match:
        return match.group(0)
    raise InvalidBvidError(f"无法提取 BV 号: {url_or_bvid}")


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    """解析浏览器 Cookie 请求头，保留完整键值对。"""
    cookies: dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def cookie_header(cookies: dict[str, str]) -> str:
    """将 Cookie dict 序列化为可存储的请求头字符串。"""
    return "; ".join(f"{name}={value}" for name, value in cookies.items() if value)


def make_credential(cookies: dict[str, str]) -> Credential:
    """从 Cookie dict 构建 bilibili-api Credential 对象。"""
    return Credential(
        sessdata=cookies.get("SESSDATA", ""),
        bili_jct=cookies.get("bili_jct", ""),
        ac_time_value=cookies.get("ac_time_value", ""),
        buvid3=cookies.get("buvid3", ""),
        buvid4=cookies.get("buvid4", ""),
        dedeuserid=cookies.get("DedeUserID", ""),
    )


def _map_error(action: str, exc: Exception) -> BiliError:
    if isinstance(exc, BiliError):
        return exc
    if isinstance(exc, (CredentialNoSessdataException, CredentialNoBiliJctException)):
        return AuthenticationError(f"{action}: {exc}")
    if isinstance(exc, ResponseCodeException):
        code = getattr(exc, "code", None)
        if code in {-101, -111}:   return AuthenticationError(f"{action}: {exc}")
        if code in {-404, 62002}:  return NotFoundError(f"{action}: {exc}")
        if code in {-412, 412}:    return RateLimitError(f"{action}: {exc}")
        return BiliError(f"{action}: [{code}] {exc}")
    if isinstance(exc, (NetworkException, ResponseException, aiohttp.ClientError, asyncio.TimeoutError)):
        return NetworkError(f"{action}: {exc}")
    if isinstance(exc, ApiException):
        return BiliError(f"{action}: {exc}")
    return BiliError(f"{action}: {exc}")


async def _call(action: str, awaitable):
    try:
        return await awaitable
    except Exception as exc:
        raise _map_error(action, exc) from exc


def _run(coro):
    """在同步环境中运行异步协程。"""
    return asyncio.run(coro)


# ─── 下载工具 ──────────────────────────────────────────────────────────────────

_DOWNLOAD_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Referer": "https://www.bilibili.com",
}

_SAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(title: str, max_len: int = 80) -> str:
    """将视频标题转换为安全的文件名。"""
    name = _SAFE_FILENAME_RE.sub("_", title).strip(". ")
    return name[:max_len] or "video"


async def _download_stream(url: str, dest: str) -> int:
    """下载单个流到文件，返回字节数。支持 3 次重试。"""
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=600)
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url, headers=_DOWNLOAD_HEADERS) as resp:
                    if resp.status != 200:
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise NetworkError(f"下载失败: HTTP {resp.status}")
                    total = 0
                    with open(dest, "wb") as f:
                        async for chunk in resp.content.iter_chunked(256 * 1024):
                            f.write(chunk)
                            total += len(chunk)
                    return total
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
            else:
                raise NetworkError(f"下载失败: {e}") from e
    raise NetworkError("下载失败: 重试耗尽")


def _ffmpeg_merge(video_path: str, audio_path: str, output_path: str) -> None:
    """用 ffmpeg 合并视频流和音频流（copy 模式，不重编码）。"""
    import shutil, subprocess
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise BiliError("ffmpeg 未安装，无法合并音视频流。请先: apk add ffmpeg")
    cmd = [
        ffmpeg, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy", "-c:a", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise BiliError(f"ffmpeg 合并失败:\n{result.stderr[-500:]}")


async def _get_download_urls(bvid: str, cred: Credential | None = None) -> dict:
    """
    获取视频和音频的下载地址。
    返回 {"video_url": ..., "audio_url": ..., "is_flv": bool}
    """
    from bilibili_api.video import VideoDownloadURLDataDetecter
    v = video.Video(bvid=bvid, credential=cred)
    data = await _call("获取下载地址", v.get_download_url(page_index=0))
    detector = VideoDownloadURLDataDetecter(data)
    is_flv = detector.check_flv_mp4_stream()

    if is_flv:
        # FLV/MP4 流：视频音频合一，直接下载
        streams = detector.detect_best_streams()
        url = streams[0].url if streams and streams[0] else None
        if not url:
            raise BiliError("无法获取 FLV 流地址")
        return {"video_url": url, "audio_url": None, "is_flv": True}
    else:
        # DASH 流：视频和音频分离，需要下载后合并
        try:
            from bilibili_api.video import AudioQuality
        except ImportError:  # pragma: no cover - 17.4.x 固定提供该枚举
            # 仅“符号不存在”时退回无参调用；其余异常一律上抛，不再静默降级
            streams = detector.detect_best_streams()
        else:
            streams = detector.detect_best_streams(
                audio_max_quality=AudioQuality._192K,
                no_dolby_audio=True,
                no_hires=True,
            )

        video_url = streams[0].url if len(streams) > 0 and streams[0] else None
        audio_url = streams[1].url if len(streams) > 1 and streams[1] else None

        if not video_url:
            raise BiliError("无法获取视频流地址")
        return {"video_url": video_url, "audio_url": audio_url, "is_flv": False}


# ─── 视频 ─────────────────────────────────────────────────────────────────────

async def _get_video_info(bvid: str, cred: Credential | None = None) -> dict:
    v = video.Video(bvid=bvid, credential=cred)
    return await _call("获取视频信息", v.get_info())

async def _get_video_subtitle(bvid: str, cred: Credential | None = None) -> tuple[str, list]:
    v = video.Video(bvid=bvid, credential=cred)
    pages = await _call("获取视频分P", v.get_pages())
    if not pages:
        return "", []
    cid = pages[0].get("cid")
    if not cid:
        return "", []
    player_info = await _call("获取播放器信息", v.get_player_info(cid=cid))
    subtitle_info = player_info.get("subtitle", {})
    if not subtitle_info or not subtitle_info.get("subtitles"):
        return "", []
    subtitle_list = subtitle_info["subtitles"]
    subtitle_url = None
    for sub in subtitle_list:
        if "zh" in sub.get("lan", "").lower():
            subtitle_url = sub.get("subtitle_url", "")
            break
    if not subtitle_url and subtitle_list:
        subtitle_url = subtitle_list[0].get("subtitle_url", "")
    if not subtitle_url:
        return "", []
    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(subtitle_url) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
    except Exception as e:
        raise NetworkError(f"下载字幕失败: {e}") from e
    if "body" in data:
        raw = data["body"]
        return "\n".join(item.get("content", "") for item in raw), raw
    return "", []

async def _get_video_comments(bvid: str, cred: Credential | None = None, page_index: int = 1) -> list:
    """获取视频评论列表。

    17.4.2 的列表接口是 ``comment.get_comments(oid, type_, page_index, order, credential)``；
    ``comment.Comment`` 只用于“对单条评论的操作”，其构造需要必填 ``rpid``，不适用于列表。
    """
    v = video.Video(bvid=bvid, credential=cred)
    info = await _call("获取视频信息", v.get_info())
    aid = info.get("aid")
    if not aid:
        raise BiliError("获取视频信息: 响应中缺少 aid，无法获取评论")
    result = await _call("获取评论", comment.get_comments(
        oid=int(aid),
        type_=comment.CommentResourceType.VIDEO,
        page_index=page_index,
        credential=cred,
    ))
    return result.get("replies") or []

async def _get_related_videos(bvid: str, cred: Credential | None = None) -> list:
    v = video.Video(bvid=bvid, credential=cred)
    return await _call("获取相关视频", v.get_related())

# 注意：不再有任何「按错误码判定视频无 AI 总结」的白名单。SDK 的 _process_response 会在
# 「响应未含 code 字段」或「旧式 OK != 1」时**自造**通用错误码 -1；把它当成「该视频没有
# 总结」等于把未知服务错误重新静默降级为良性空值。因此所有 ResponseCodeException 一律按
# _map_error 上抛；「无总结」只保留**正向证据**路径（见下方 _get_ai_summary 的空 payload 分支）。

def _extract_ai_summary(result: dict) -> str:
    model_result = result.get("model_result") if isinstance(result, dict) else None
    if not isinstance(model_result, dict):
        return ""
    summary = model_result.get("summary")
    return summary if isinstance(summary, str) else ""

async def _get_ai_summary(bvid: str, cred: Credential | None = None) -> tuple[str, dict | None]:
    """
    获取视频 AI 总结。

    返回 ``(summary, notice)``：

    - 有总结：``("...", None)``
    - 接口返回成功但 payload 里没有可用的总结内容：``("", {"code": "ai_summary_empty", ...})``。
      只陈述「本次响应没有内容」这一**观测事实**，**不**推断「该视频没有 AI 总结」。
    - 缺少可用 cid：``("", {"code": "ai_summary_no_cid", ...})``（同样只陈述事实）。
    - 其它任何错误（含所有 ``ResponseCodeException``）：抛出 BiliError 家族
      （NetworkError / AuthenticationError / RateLimitError / ...），不再有任何「错误码 → 无总结」
      的静默降级。特别地，SDK 自造的通用错误码 ``-1`` 会以
      ``BiliError("获取 AI 总结: [-1] <msg>")`` 上抛，保留原始 code 与 message。
    """
    v = video.Video(bvid=bvid, credential=cred)
    pages = await _call("获取视频分P", v.get_pages())
    cid = next((p.get("cid") for p in pages if isinstance(p, dict) and p.get("cid")), None)
    if not cid:
        return "", {
            "code": "ai_summary_no_cid",
            "message": "视频分P信息中缺少可用的 cid，未能请求 AI 总结",
        }
    try:
        # 17.4.2: get_ai_conclusion(cid=..., page_index=..., up_mid=...) 没有 credential 形参，
        # 认证由 Video 对象自带（构造 v 时已传入 cred）。
        result = await v.get_ai_conclusion(cid=cid)
    except Exception as exc:
        # ResponseCodeException（含 SDK 自造的 -1）与其余错误一律映射后上抛，不做任何
        # 「按 code 判定无总结」的降级。
        raise _map_error("获取 AI 总结", exc) from exc
    summary = _extract_ai_summary(result)
    if not summary:
        return "", {
            "code": "ai_summary_empty",
            "message": "AI 总结接口返回成功但未包含可用的总结内容（model_result.summary 为空）；"
                       "该结果不表示该视频没有总结",
        }
    return summary, None

# ─── 用户 ─────────────────────────────────────────────────────────────────────

async def _get_user_info(uid: int, cred: Credential | None = None) -> dict:
    u = user.User(uid=uid, credential=cred)
    return await _call("获取用户信息", u.get_user_info())

async def _get_user_relation(uid: int, cred: Credential | None = None) -> dict:
    u = user.User(uid=uid, credential=cred)
    return await _call("获取用户关系", u.get_relation_info())

async def _get_self_info(cred: Credential) -> dict:
    return await _call("获取自身信息", user.get_self_info(cred))

async def _get_user_videos(uid: int, count: int = 10, cred: Credential | None = None) -> list:
    u = user.User(uid=uid, credential=cred)
    results = []
    page = 1
    while len(results) < count:
        batch = await _call("获取用户视频", u.get_videos(pn=page))
        items = batch.get("list", {}).get("vlist", [])
        if not items:
            break
        results.extend(items)
        page += 1
        if len(items) < 30:
            break
    return results[:count]# ─── 搜索 ─────────────────────────────────────────────────────────────────────

async def _search_users(keyword: str, page: int = 1) -> list:
    from bilibili_api.search import SearchObjectType
    result = await _call("搜索用户", search.search_by_type(
        keyword, search_type=SearchObjectType.USER, page=page,
    ))
    return result.get("result", []) or []

async def _search_videos(keyword: str, page: int = 1, count: int = 20) -> list:
    from bilibili_api.search import SearchObjectType
    result = await _call("搜索视频", search.search_by_type(
        keyword, search_type=SearchObjectType.VIDEO, page=page,
    ))
    return (result.get("result", []) or [])[:count]

# ─── 发现 ─────────────────────────────────────────────────────────────────────

async def _get_hot(page: int = 1, count: int = 20) -> list:
    result = await _call("获取热门", hot.get_hot_videos(pn=page, ps=count))
    return result.get("list", []) or []

async def _get_rank(day: int = 3, count: int = 100) -> list:
    """获取**全站**视频排行榜（``RankType.All``）。

    ``day`` 是**已废弃的兼容参数（deprecated no-op）**：17.4.2 的 ``rank.get_rank`` 只有在
    ``RankType`` 的 ``api_type == "pgc"`` 分支（番剧类榜单）才会把 ``day`` 放进请求；全站榜
    ``RankType.All``（``api_type == "x"``）走 ``/x/web-interface/ranking/v2`` 接口，SDK 会
    **忽略** ``day``，请求参数只有 ``web_location`` 与 ``rid``。

    因此本方法**不伪造**「三日榜/周榜」语义：无论 ``day`` 取何值，都返回同一份全站视频榜；
    ``day`` 仅用于兼容旧调用签名，不会出现在请求中，也不再做 3/7 校验（旧实现的
    ``day=1`` 抛错只是暴露了它对 ``RankDayType`` 的误用，而非真实语义）。

    Args:
        day: 已废弃的兼容参数，取值不影响结果（见上）。
        count: 截断返回条数。
    """
    from bilibili_api.rank import RankType
    result = await _call("获取排行榜", rank.get_rank(type_=RankType.All))
    items = result.get("list", []) or []
    return items[:count]

def _normalize_feed_offset(offset: int | str | None) -> int | str | None:
    """规范化动态流分页游标。

    动态页接口返回的 ``offset`` 是“下一页第一条动态”的游标（JS 端会丢精度，故可能是字符串）。
    这里对 ``None`` / ``0`` / ``""`` / ``"0"`` 统一视为首页，其余**原样透传**：
    ``int`` 保持 ``int``、``str`` 保持 ``str``，避免把大整数游标转换后再传回去时发生精度损失。
    """
    if offset is None:
        return None
    if isinstance(offset, str):
        offset = offset.strip()
        return offset if offset and offset != "0" else None
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TypeError(f"offset 必须是 int、str 或 None，收到 {type(offset).__name__}")
    return offset if offset != 0 else None

async def _get_feed(offset: int | str | None = None, cred: Credential | None = None) -> dict:
    """获取关注动态**条目流**。

    17.4.2 中带 offset 的接口是 ``dynamic.get_dynamic_page_info``（动态页动态信息，返回
    ``items`` / ``offset`` / ``has_more``）。``get_dynamic_page_UPs_info`` 的语义是
    “动态页 UP 主列表”（关注对象清单），不是动态条目流，且不接受 offset 参数。
    """
    return await _call("获取动态 Feed", dynamic.get_dynamic_page_info(
        credential=cred,
        offset=_normalize_feed_offset(offset),
    ))

async def _get_my_dynamics(uid: int, offset: int = 0, cred: Credential | None = None) -> dict:
    """获取我发布的动态（**旧版** ``dynamic_svr/space_history`` 接口）。

    17.4.2 的 ``User.get_dynamics(offset: int = 0, need_top: bool = False)`` 返回
    ``cards`` / ``next_offset``。``offset``（int）是「下一页第一条动态 ID」，``0`` 为第一页。
    旧卡片顶层含 ``desc``（``dynamic_id_str`` / ``timestamp``）与内嵌 JSON ``card``，
    由 ``payloads.normalize_dynamic_item`` 的旧格式分支处理。
    """
    u = user.User(uid=uid, credential=cred)
    return await _call("获取我的动态", u.get_dynamics(offset=offset or 0))

async def _get_my_dynamics_new(uid: int, offset: str = "", cred: Credential | None = None) -> dict:
    """获取我发布的动态（**新版**聚合物 ``polymer/web-dynamic/v1/feed/space`` 接口）。

    17.4.2 的 ``User.get_dynamics_new(offset: str = "")`` 返回 ``items`` / ``offset`` /
    ``has_more``。其 ``offset``（str）与旧接口的 int 游标**不可互用**。
    """
    u = user.User(uid=uid, credential=cred)
    return await _call("获取我的动态(新版)", u.get_dynamics_new(offset=offset or ""))

async def _post_dynamic(text: str, cred: Credential) -> dict:
    if not text.strip():
        raise BiliError("发布动态: 文本不能为空")
    info = dynamic.BuildDynamic.empty().add_text(text.strip())
    return await _call("发布动态", dynamic.send_dynamic(info=info, credential=cred))

async def _delete_dynamic(dynamic_id: int, cred: Credential) -> dict:
    d = dynamic.Dynamic(dynamic_id=dynamic_id, credential=cred)
    return await _call("删除动态", d.delete())

# ─── 收藏 ─────────────────────────────────────────────────────────────────────

async def _get_favorite_folders(uid: int, cred: Credential | None = None) -> list:
    result = await _call("获取收藏夹", favorite_list.get_video_favorite_list(uid=uid, credential=cred))
    return result.get("list", []) or []

async def _get_favorite_videos(folder_id: int, page: int = 1, count: int = 20, cred: Credential | None = None) -> list:
    result = await _call("获取收藏视频", favorite_list.get_video_favorite_list_content(
        media_id=folder_id, page=page, credential=cred,
    ))
    return (result.get("medias", []) or [])[:count]

async def _get_following(uid: int, page: int = 1, cred: Credential | None = None) -> list:
    u = user.User(uid=uid, credential=cred)
    result = await _call("获取关注列表", u.get_followings(pn=page))
    return result.get("list", []) or []

async def _get_watch_later(cred: Credential) -> list:
    # 17.4.2：稍后再看属于 user 模块（favorite_list 没有 get_video_toview_list 这个符号）
    result = await _call("获取稍后再看", user.get_toview_list(credential=cred))
    return result.get("list", []) or []

async def _get_history(cred: Credential) -> list:
    """获取观看历史（17.4.2：user.get_self_history）。

    不再吞异常：认证/限流/网络/接口错误按 BiliError 家族上抛；账号确实没有历史时，
    接口返回空 ``list``，同样得到空列表（合法空态与错误由此区分）。
    """
    result = await _call("获取历史记录", user.get_self_history(credential=cred))
    return result.get("list", []) or []

# ─── 互动 ─────────────────────────────────────────────────────────────────────

async def _like_video(bvid: str, cred: Credential, undo: bool = False) -> dict:
    v = video.Video(bvid=bvid, credential=cred)
    return await _call("点赞", v.like(status=not undo))

async def _coin_video(bvid: str, cred: Credential, num: int = 1) -> dict:
    v = video.Video(bvid=bvid, credential=cred)
    return await _call("投币", v.pay_coin(num=num))

async def _triple_video(bvid: str, cred: Credential) -> dict:
    v = video.Video(bvid=bvid, credential=cred)
    return await _call("一键三连", v.triple())

async def _unfollow_user(uid: int, cred: Credential) -> dict:
    u = user.User(uid=uid, credential=cred)
    return await _call("取消关注", u.modify_relation(relation=user.RelationType.UNSUBSCRIBE))


# ═══════════════════════════════════════════════════════════════════════════════
# BiliClient — 同步封装，对外暴露的主类
# ═══════════════════════════════════════════════════════════════════════════════

class BiliClient:
    """
    哔哩哔哩 API 客户端。

    Cookie 通过单一环境变量存储：
        BILI_COOKIE="SESSDATA=...; bili_jct=...; DedeUserID=...; buvid3=..."

    from_env(validate=True) 会调用 whoami() 验证 Cookie；失效时抛出 AuthenticationError。
    """

    def __init__(self, cookies: dict[str, str] | None = None):
        self._cred: Credential | None = None
        if cookies:
            if not cookies.get("SESSDATA"):
                raise ValueError("cookies 必须包含 'SESSDATA' 字段")
            self._cred = make_credential(cookies)

    @classmethod
    def from_env(cls, *, validate: bool = False) -> "BiliClient":
        """从 BILI_COOKIE 构建客户端，可选验证登录状态。"""
        raw_cookie = os.environ.get("BILI_COOKIE", "").strip()
        if raw_cookie:
            cookies = parse_cookie_header(raw_cookie)
        else:
            cookies = {
                "SESSDATA": os.environ.get("BILI_SESSDATA", ""),
                "bili_jct": os.environ.get("BILI_JCT", ""),
                "DedeUserID": os.environ.get("BILI_USERID", ""),
                "buvid3": os.environ.get("BILI_BUVID3", ""),
            }
        if not cookies.get("SESSDATA"):
            raise ValueError("环境变量 BILI_COOKIE 未设置或不含 SESSDATA")
        client = cls(cookies)
        if validate:
            client.validate_cookie()
        return client

    @staticmethod
    def normalize_cookie_header(cookie_header_value: str) -> str:
        """校验并规范化完整 Cookie 请求头，供写入 BILI_COOKIE。"""
        cookies = parse_cookie_header(cookie_header_value)
        if not cookies.get("SESSDATA"):
            raise ValueError("Cookie 必须包含 SESSDATA")
        return cookie_header(cookies)

    def _auth(self, require_write: bool = False) -> Credential:
        """获取认证凭证，未登录时抛出 AuthenticationError。"""
        if not self._cred or not self._cred.sessdata:
            raise AuthenticationError("未登录，请先传入 Cookie")
        if require_write and not self._cred.bili_jct:
            raise AuthenticationError("写操作需要 bili_jct Cookie")
        return self._cred

    # ── 账号 ──────────────────────────────────────────────────────────────

    def whoami(self) -> dict:
        """获取当前登录用户信息（用于 Cookie 校验）。

        17.4.2 中自身信息接口是 ``user.get_self_info(credential)``；未登录/凭据缺失时
        抛 ``AuthenticationError``，Cookie 失效（code -101/-111）时同样映射为
        ``AuthenticationError``。
        """
        from .payloads import normalize_user
        info = _run(_get_self_info(self._auth()))
        return normalize_user(info)

    def validate_cookie(self) -> dict:
        """验证当前 Cookie 是否仍可用于登录操作。

        成功返回当前用户信息（同 ``whoami()``）；失败抛出 ``AuthenticationError``
        或 ``BiliError`` 子类。
        """
        return self.whoami()

    # ── 视频 ──────────────────────────────────────────────────────────────

    def get_video(
        self,
        bvid: str,
        *,
        subtitle: bool = False,
        subtitle_timeline: bool = False,
        ai_summary: bool = False,
        comments: bool = False,
        related: bool = False,
    ) -> dict:
        """
        获取视频详情。

        bvid: BV 号或包含 BV 号的 URL
        subtitle: 是否获取字幕（纯文本）
        subtitle_timeline: 是否获取带时间轴字幕
        ai_summary: 是否获取 AI 总结（需登录）
        comments: 是否获取热门评论
        related: 是否获取相关视频
        """
        bvid = extract_bvid(bvid)
        cred = self._cred
        warnings: list[dict[str, str]] = []

        async def _fetch():
            info = await _get_video_info(bvid, cred)
            sub_text, sub_raw = "", []
            if subtitle or subtitle_timeline:
                sub_text, sub_raw = await _get_video_subtitle(bvid, cred)
            ai, ai_notice = ("", None)
            if ai_summary:
                ai, ai_notice = await _get_ai_summary(bvid, cred)
                if ai_notice:
                    # 接口调用成功但没有可用内容（或缺少 cid）：保留空 summary，同时追加一条
                    # **观测性** warning（code=ai_summary_empty / ai_summary_no_cid）。
                    # warning 既不推断“该视频没有 AI 总结”，也不掩盖任何真实错误。
                    warnings.append(ai_notice)
            cmts = await _get_video_comments(bvid, cred) if comments else []
            rels = await _get_related_videos(bvid, cred) if related else []
            return info, sub_text, sub_raw, ai, cmts, rels

        info, sub_text, sub_raw, ai, cmts, rels = _run(_fetch())

        from .payloads import normalize_video_command_payload
        return normalize_video_command_payload(
            info,
            subtitle_text=sub_text,
            subtitle_items=sub_raw if subtitle_timeline else None,
            ai_summary=ai,
            comments=cmts,
            related=rels,
            warnings=warnings,
        )

    # ── 用户 ──────────────────────────────────────────────────────────────

    def get_user(self, uid: int) -> dict:
        """获取用户主页信息。"""
        async def _fetch():
            info = await _get_user_info(uid, self._cred)
            rel  = await _get_user_relation(uid, self._cred)
            return info, rel
        info, rel = _run(_fetch())
        from .payloads import normalize_user, normalize_relation
        return {"user": normalize_user(info), "relation": normalize_relation(rel)}

    def get_user_videos(self, uid: int, count: int = 20) -> list:
        """获取用户发布的视频列表。"""
        from .payloads import normalize_video_summary
        items = _run(_get_user_videos(uid, count, self._cred))
        return [normalize_video_summary(v) for v in items]

    # ── 搜索 ──────────────────────────────────────────────────────────────

    def search_users(self, keyword: str, page: int = 1) -> list:
        """搜索用户。"""
        from .payloads import normalize_search_user
        items = _run(_search_users(keyword, page))
        return [normalize_search_user(u) for u in items]

    def search_videos(self, keyword: str, page: int = 1, count: int = 20) -> list:
        """搜索视频。"""
        from .payloads import normalize_search_video
        items = _run(_search_videos(keyword, page, count))
        return [normalize_search_video(v) for v in items]

    # ── 发现 ──────────────────────────────────────────────────────────────

    def get_hot(self, page: int = 1, count: int = 20) -> list:
        """获取热门视频。"""
        from .payloads import normalize_video_summary
        items = _run(_get_hot(page, count))
        return [normalize_video_summary(v) for v in items]

    def get_rank(self, day: int = 3, count: int = 50) -> list:
        """获取**全站**视频排行榜（``RankType.All``）。

        Args:
            day: **已废弃的兼容参数（deprecated no-op）**。17.4.2 中 ``day`` 只对
                ``api_type == "pgc"`` 的番剧类榜单生效；全站榜（``RankType.All``）走
                ``ranking/v2`` 接口并**忽略** ``day``。保留该形参只为不破坏旧调用签名，
                取值不影响返回结果，也**不代表**「三日榜/周榜」。
            count: 截断返回条数。
        """
        from .payloads import normalize_video_summary
        items = _run(_get_rank(day, count))
        return [normalize_video_summary(v) for v in items]

    def get_feed(self, offset: int | str | None = None) -> dict:
        """获取关注动态条目流（需登录）。

        17.4.2 用 ``dynamic.get_dynamic_page_info``（动态页动态信息）。

        Args:
            offset: 分页游标，取上一页返回结果中的 ``offset`` 字段值；``None`` / ``0`` /
                ``""`` 表示从第一页开始。

        Returns:
            SDK 原始 dict，主要键：``items``（动态条目列表，聚合物格式，可用
            ``payloads.normalize_dynamic_item`` 规范化）、``offset``（下一页游标）、
            ``has_more``（是否还有下一页）。返回的是**条目流**，不是 UP 主列表。
        """
        return _run(_get_feed(offset, self._auth()))

    def _resolve_self_uid(self, cred: Credential) -> int:
        """从自身信息解析当前登录用户 mid；解析不到时抛 AuthenticationError。"""
        info = _run(_get_self_info(cred))
        uid = int(info.get("mid", 0) or 0)
        if not uid:
            raise AuthenticationError("无法从自身信息中解析 mid，请检查 Cookie 是否有效")
        return uid

    def get_my_dynamics(self, offset: int = 0) -> list:
        """获取我发布的动态（需登录），返回一页规范化动态列表。

        **运行契约与历史版本一致**：``offset`` 为 **int** 游标（旧版
        ``dynamic_svr/space_history`` 的 ``next_offset``，``0`` 表示第一页），返回**列表**。
        旧卡片由 ``payloads.normalize_dynamic_item`` 的旧格式分支读取（``cards`` 与内嵌
        JSON ``card``）。本次返修只修正了旧实现读错键（``items`` → ``cards``）的问题。

        如需**新版聚合物接口**（``polymer/web-dynamic/v1/feed/space``）的**字符串游标**与
        ``has_more``，请改用 ``get_my_dynamics_page()``；两者游标类型不同，**不可混用**。
        """
        from .payloads import normalize_dynamic_item
        cred = self._auth()
        uid = self._resolve_self_uid(cred)
        result = _run(_get_my_dynamics(uid, offset, cred))
        cards = result.get("cards") or []
        return [normalize_dynamic_item(c) for c in cards]

    def get_my_dynamics_page(self, offset: str = "") -> dict:
        """获取我发布的动态（需登录，**新版聚合物接口**），返回一页数据与下一页游标。

        这是与 ``get_my_dynamics()`` **相互独立**的新 API：``offset`` 为 **str** 游标
        （``polymer/web-dynamic/v1/feed/space`` 的 ``offset``，``""`` 表示第一页）。旧
        ``get_my_dynamics(offset: int)`` 的 int 游标与此**不可互用**，请勿混用。

        Args:
            offset: 上一页返回结果中的 ``offset``（字符串）。

        Returns:
            ``{"items": [<规范化动态>, ...], "offset": <下一页游标或 "">, "has_more": bool}``
        """
        from .payloads import normalize_dynamic_item
        cred = self._auth()
        uid = self._resolve_self_uid(cred)
        result = _run(_get_my_dynamics_new(uid, offset, cred))
        items = result.get("items") or []
        return {
            "items": [normalize_dynamic_item(i) for i in items],
            "offset": result.get("offset") or "",
            "has_more": bool(result.get("has_more")),
        }

    def post_dynamic(self, text: str) -> dict:
        """发布文字动态（需登录）。"""
        return _run(_post_dynamic(text, self._auth(require_write=True)))

    def delete_dynamic(self, dynamic_id: int) -> dict:
        """删除动态（需登录）。"""
        return _run(_delete_dynamic(dynamic_id, self._auth(require_write=True)))

    # ── 收藏 ──────────────────────────────────────────────────────────────

    def get_favorites(self, folder_id: int | None = None, page: int = 1, count: int = 20) -> list | dict:
        """
        获取收藏夹。
        - folder_id=None: 返回收藏夹列表
        - folder_id=<id>: 返回该收藏夹内的视频
        """
        cred = self._auth()
        if folder_id is None:
            info = _run(_get_self_info(cred))
            uid  = int(info.get("mid", 0))
            from .payloads import normalize_favorite_folder
            items = _run(_get_favorite_folders(uid, cred))
            return [normalize_favorite_folder(f) for f in items]
        from .payloads import normalize_favorite_media
        items = _run(_get_favorite_videos(folder_id, page, count, cred))
        return [normalize_favorite_media(v) for v in items]

    def get_following(self, page: int = 1) -> list:
        """获取关注列表（需登录）。"""
        cred = self._auth()
        info = _run(_get_self_info(cred))
        uid  = int(info.get("mid", 0))
        from .payloads import normalize_following_user
        items = _run(_get_following(uid, page, cred))
        return [normalize_following_user(u) for u in items]

    def get_watch_later(self) -> list:
        """获取稍后再看列表（需登录）。"""
        from .payloads import normalize_watch_later_item
        items = _run(_get_watch_later(self._auth()))
        return [normalize_watch_later_item(v) for v in items]

    def get_history(self) -> list:
        """获取观看历史（需登录）。"""
        from .payloads import normalize_history_item
        items = _run(_get_history(self._auth()))
        return [normalize_history_item(v) for v in items]

    # ── 互动 ──────────────────────────────────────────────────────────────

    def like(self, bvid: str, undo: bool = False) -> dict:
        """点赞 / 取消点赞。"""
        from .payloads import action_result
        bvid = extract_bvid(bvid)
        _run(_like_video(bvid, self._auth(require_write=True), undo=undo))
        return action_result("like" if not undo else "unlike", bvid=bvid)

    def coin(self, bvid: str, num: int = 1) -> dict:
        """投币（1 或 2 枚）。"""
        from .payloads import action_result
        bvid = extract_bvid(bvid)
        _run(_coin_video(bvid, self._auth(require_write=True), num=num))
        return action_result("coin", bvid=bvid, num=num)

    def triple(self, bvid: str) -> dict:
        """一键三连（点赞 + 投币 + 收藏）。"""
        from .payloads import action_result
        bvid = extract_bvid(bvid)
        _run(_triple_video(bvid, self._auth(require_write=True)))
        return action_result("triple", bvid=bvid)

    def unfollow(self, uid: int) -> dict:
        """取消关注用户。"""
        from .payloads import action_result
        _run(_unfollow_user(uid, self._auth(require_write=True)))
        return action_result("unfollow", uid=uid)

    # ── 下载 ──────────────────────────────────────────────────────────────

    def download_video(
        self,
        bvid: str,
        output_dir: str = "/var/minis/workspace",
        filename: str | None = None,
    ) -> str:
        """
        下载视频到本地文件，返回输出文件路径。

        流程：
        1. 获取视频信息（标题）和下载地址
        2. 若为 DASH 流（音视频分离）：
           a. 分别下载视频流（.video.mp4）和音频流（.audio.m4a）
           b. 尝试用 bilibili-api 内置方式合并
           c. 失败则 fallback 到 ffmpeg 合并
        3. 若为 FLV/MP4 流（音视频合一）：直接下载，无需合并

        Args:
            bvid:       BV 号或包含 BV 号的 URL
            output_dir: 输出目录（默认 /var/minis/workspace）
            filename:   自定义文件名（不含扩展名），默认用视频标题

        Returns:
            最终输出文件的绝对路径
        """
        import tempfile

        bvid = extract_bvid(bvid)
        cred = self._cred

        async def _fetch():
            info = await _get_video_info(bvid, cred)
            urls = await _get_download_urls(bvid, cred)
            return info, urls

        info, urls = _run(_fetch())

        title = info.get("title", bvid)
        safe = filename or _safe_filename(title)
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"{safe}.mp4")

        if urls["is_flv"]:
            # ── FLV/MP4：直接下载，无需合并 ──────────────────────────────
            logger.info("FLV/MP4 流，直接下载 → %s", out_path)
            size = _run(_download_stream(urls["video_url"], out_path))
            logger.info("下载完成: %.1f MB", size / 1024 / 1024)
            return out_path

        # ── DASH：分别下载视频流和音频流，再合并 ─────────────────────────
        with tempfile.TemporaryDirectory() as tmp:
            v_tmp = os.path.join(tmp, "video.mp4")
            a_tmp = os.path.join(tmp, "audio.m4a")

            logger.info("下载视频流 → %s", v_tmp)
            v_size = _run(_download_stream(urls["video_url"], v_tmp))
            logger.info("视频流: %.1f MB", v_size / 1024 / 1024)

            if urls.get("audio_url"):
                logger.info("下载音频流 → %s", a_tmp)
                a_size = _run(_download_stream(urls["audio_url"], a_tmp))
                logger.info("音频流: %.1f MB", a_size / 1024 / 1024)

                # 合并：ffmpeg copy 模式（不重编码）
                logger.info("合并音视频 → %s", out_path)
                try:
                    _ffmpeg_merge(v_tmp, a_tmp, out_path)
                    logger.info("ffmpeg 合并成功")
                except BiliError as e:
                    # ffmpeg 失败：至少保留视频流（无声）
                    import shutil
                    shutil.copy2(v_tmp, out_path)
                    logger.warning("ffmpeg 合并失败，已保存无声视频: %s\n原因: %s", out_path, e)
                    return out_path
            else:
                # 无音频流（少见），直接用视频流
                import shutil
                shutil.copy2(v_tmp, out_path)

        return out_path

    def download_audio(
        self,
        bvid: str,
        output_dir: str = "/var/minis/workspace",
        filename: str | None = None,
    ) -> str:
        """
        仅下载视频的音频流，保存为 .m4a 文件，返回输出路径。

        适合需要提取音频做转写（ASR）的场景。

        Args:
            bvid:       BV 号或包含 BV 号的 URL
            output_dir: 输出目录（默认 /var/minis/workspace）
            filename:   自定义文件名（不含扩展名），默认用视频标题

        Returns:
            输出 .m4a 文件的绝对路径
        """
        bvid = extract_bvid(bvid)
        cred = self._cred

        async def _fetch():
            info = await _get_video_info(bvid, cred)
            urls = await _get_download_urls(bvid, cred)
            return info, urls

        info, urls = _run(_fetch())

        title = info.get("title", bvid)
        safe = filename or _safe_filename(title)
        os.makedirs(output_dir, exist_ok=True)

        if urls["is_flv"]:
            # FLV 流音视频合一，只能下完整视频再用 ffmpeg 提取音频
            import tempfile, shutil, subprocess
            out_path = os.path.join(output_dir, f"{safe}.m4a")
            with tempfile.TemporaryDirectory() as tmp:
                v_tmp = os.path.join(tmp, "video.mp4")
                _run(_download_stream(urls["video_url"], v_tmp))
                import shutil as _shutil
                ffmpeg = _shutil.which("ffmpeg")
                if ffmpeg:
                    cmd = [ffmpeg, "-y", "-i", v_tmp, "-vn", "-acodec", "copy", out_path]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        raise BiliError(f"ffmpeg 提取音频失败:\n{result.stderr[-300:]}")
                else:
                    # 无 ffmpeg：直接复制视频文件（兜底）
                    out_path = os.path.join(output_dir, f"{safe}.mp4")
                    shutil.copy2(v_tmp, out_path)
            return out_path

        # DASH：直接下载音频流
        if not urls.get("audio_url"):
            raise BiliError("该视频没有独立音频流")

        out_path = os.path.join(output_dir, f"{safe}.m4a")
        size = _run(_download_stream(urls["audio_url"], out_path))
        logger.info("音频下载完成: %.1f MB → %s", size / 1024 / 1024, out_path)
        return out_path
