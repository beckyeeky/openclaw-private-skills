"""bilibili-hub 离线契约测试（公开方法返回规范 + 异常行为）。

设计约束（与审计边界一致）：

- **不使用真实凭据**：所有 Cookie 均为 ``DUMMY_NOT_A_REAL_*`` 占位值；不读取、不打印
  ``BILI_COOKIE`` 的真实内容（需要 ``BILI_COOKIE`` 的用例用 ``patch.dict`` 覆盖为占位值）。
- **完全离线**：SDK 层符号（``user`` / ``video`` / ``comment`` / ``dynamic`` / ``favorite_list``
  / ``hot`` / ``rank`` / ``search``）与 ``aiohttp.ClientSession`` 全部被替身接管；
  测试期间 ``aiohttp.ClientSession`` 被替换为“一旦调用即断言失败”的哨兵，
  因此任何真实网络请求都会让测试立即失败。
- **无写操作**：``post_dynamic`` / ``delete_dynamic`` / 互动类方法只验证“缺 bili_jct 时的
  认证异常”与“替身被正确调用”的路径，绝不触发真实写入。

**证据边界（务必注意）**：本模块的绝大多数行为用例使用 ``AsyncMock`` 替身，它们证明的是
「client 在**假定**的输入形状下产出预期输出」，**不能**作为 Bilibili 真实返回值的证据——
真实返回结构（字段是否存在、字段含义、错误码语义）均**未**在此验证。只有
``TestSdkSignatureCompliance``（绑定**真实** 17.4.2 签名）与 ``TestUserSearchDiscover``
中的 ``test_get_rank_request_params_ignore_day``（用**真实** ``rank.get_rank`` + 假 ``Api``
捕获真实请求参数）触及 SDK 本体；即便这两类，也只是“调用形态/请求形态”级别的证据，仍不代表
真实响应数据。任何关于“真实接口返回什么”的结论都必须在联网环境另行验证。

运行（在技能目录下）::

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aiohttp  # noqa: E402
from bilibili_api import favorite_list as sdk_favorite_list  # noqa: E402
from bilibili_api import user as sdk_user  # noqa: E402
from bilibili_api.exceptions import (  # noqa: E402
    CredentialNoBiliJctException,
    CredentialNoSessdataException,
    NetworkException,
    ResponseCodeException,
    ResponseException,
)

from scripts import client as client_mod  # noqa: E402
from scripts.client import (  # noqa: E402
    BiliClient,
    _map_error,
    cookie_header,
    extract_bvid,
    parse_cookie_header,
)
from scripts.exceptions import (  # noqa: E402
    AuthenticationError,
    BiliError,
    InvalidBvidError,
    NetworkError,
    NotFoundError,
    RateLimitError,
)

# ─── 占位凭据（绝不是真实值） ─────────────────────────────────────────────────

SESSDATA_DUMMY = "DUMMY_NOT_A_REAL_SESSDATA"
JCT_DUMMY = "DUMMY_NOT_A_REAL_JCT"
COOKIES = {
    "SESSDATA": SESSDATA_DUMMY,
    "bili_jct": JCT_DUMMY,
    "DedeUserID": "1",
    "buvid3": "DUMMY_NOT_A_REAL_BUVID3",
}
READ_ONLY_COOKIES = {"SESSDATA": SESSDATA_DUMMY}  # 无 bili_jct


# ─── 网络哨兵 ─────────────────────────────────────────────────────────────────

class NetworkForbidden(AssertionError):
    """真实网络访问被测试哨兵拦截。"""


def _network_forbidden(*_args, **_kwargs):
    raise NetworkForbidden("测试禁止真实网络请求：aiohttp.ClientSession 被调用")


_NET_PATCH = patch.object(aiohttp, "ClientSession", _network_forbidden)


def setUpModule():  # noqa: D103
    _NET_PATCH.start()


def tearDownModule():  # noqa: D103
    _NET_PATCH.stop()


# ─── 替身工厂 ─────────────────────────────────────────────────────────────────

VIDEO_INFO = {
    "bvid": "BV1xx411c7mD",
    "aid": 12345,
    "title": "示例<em>视频</em>",
    "desc": "desc",
    "duration": 125,
    "owner": {"mid": 7, "name": "UP 主"},
    "stat": {"view": 10, "danmaku": 1, "like": 2, "coin": 3, "favorite": 4, "share": 5},
}
USER_INFO = {"mid": 42, "name": "测试用户", "level": 3, "coins": 5, "sign": "s", "vip": {}}
RELATION = {"following": 11, "follower": 22}


def fake_video_cls(*, get_info=None, get_pages=None, ai_result=None, ai_exc=None,
                   get_related=None, player_info=None):
    """构造一个替身 ``video.Video`` 类（返回可断言调用的实例）。"""
    inst = MagicMock()
    inst.get_info = AsyncMock(return_value=VIDEO_INFO if get_info is None else get_info)
    inst.get_pages = AsyncMock(return_value=[{"cid": 999, "page": 1}] if get_pages is None else get_pages)
    if ai_exc is not None:
        inst.get_ai_conclusion = AsyncMock(side_effect=ai_exc)
    else:
        inst.get_ai_conclusion = AsyncMock(
            return_value={"model_result": {"summary": "AI 总结"}} if ai_result is None else ai_result
        )
    inst.get_related = AsyncMock(return_value=[] if get_related is None else get_related)
    inst.get_player_info = AsyncMock(return_value={} if player_info is None else player_info)
    inst.like = AsyncMock(return_value={})
    inst.pay_coin = AsyncMock(return_value={})
    inst.triple = AsyncMock(return_value={})
    inst.get_download_url = AsyncMock(return_value={})
    return MagicMock(return_value=inst), inst


def fake_user_cls(*, user_info=None, relation=None, videos=None, followings=None,
                  dynamics=None, dynamics_new=None):
    inst = MagicMock()
    inst.get_user_info = AsyncMock(return_value=USER_INFO if user_info is None else user_info)
    inst.get_relation_info = AsyncMock(return_value=RELATION if relation is None else relation)
    inst.get_videos = AsyncMock(return_value={"list": {"vlist": []}} if videos is None else videos)
    inst.get_followings = AsyncMock(return_value={"list": []} if followings is None else followings)
    # 旧接口（dynamic_svr/space_history）：返回 cards / next_offset
    inst.get_dynamics = AsyncMock(
        return_value={"cards": [], "next_offset": 0} if dynamics is None else dynamics
    )
    # 新接口（polymer/web-dynamic/v1/feed/space）：返回 items / offset / has_more
    inst.get_dynamics_new = AsyncMock(return_value={"items": [], "offset": ""} if dynamics_new is None else dynamics_new)
    inst.modify_relation = AsyncMock(return_value={})
    return MagicMock(return_value=inst), inst


class ClientCase(unittest.TestCase):
    """公共基类：构造带占位 Cookie 的客户端。"""

    def client(self, cookies=None):
        return BiliClient(COOKIES if cookies is None else cookies)

    def read_only_client(self):
        return BiliClient(READ_ONLY_COOKIES)


# ═══ 1. 网络哨兵自检 ═══════════════════════════════════════════════════════════

class TestNetworkIsForbidden(ClientCase):
    def test_aiohttp_session_is_sentinel(self):
        with self.assertRaises(NetworkForbidden):
            aiohttp.ClientSession()

    def test_download_stream_never_reaches_network(self):
        with self.assertRaises(NetworkForbidden):
            asyncio.run(client_mod._download_stream("https://example.invalid/x", "/tmp/should-not-exist.bin"))

    def test_sdk_symbols_used_by_client_are_the_real_modules(self):
        # 确认我们 patch 的是真的 SDK 模块对象（而非测试自造对象）
        self.assertTrue(hasattr(sdk_user, "get_self_info"))
        self.assertFalse(
            hasattr(sdk_favorite_list, "get_video_toview_list"),
            "favorite_list 不应存在 get_video_toview_list（稍后再看在 user 模块）",
        )


# ═══ 2. Cookie 工具与构造 ══════════════════════════════════════════════════════

class TestCookieHelpers(ClientCase):
    def test_parse_and_serialize_roundtrip(self):
        raw = "SESSDATA=a=b; bili_jct=xyz; DedeUserID=1"
        cookies = parse_cookie_header(raw)
        self.assertEqual(cookies["SESSDATA"], "a=b")  # 值中的 "=" 保留
        self.assertIn("SESSDATA=a=b", cookie_header(cookies))

    def test_normalize_cookie_header(self):
        self.assertEqual(
            BiliClient.normalize_cookie_header("SESSDATA=a; bili_jct=b"),
            "SESSDATA=a; bili_jct=b",
        )
        with self.assertRaises(ValueError):
            BiliClient.normalize_cookie_header("bili_jct=b")

    def test_client_requires_sessdata(self):
        with self.assertRaises(ValueError):
            BiliClient({"bili_jct": JCT_DUMMY})

    def test_from_env_parses_dummy_bili_cookie(self):
        env = {"BILI_COOKIE": f"SESSDATA={SESSDATA_DUMMY}; bili_jct={JCT_DUMMY}; DedeUserID=1"}
        with patch.dict(os.environ, env, clear=False):
            client = BiliClient.from_env()
        self.assertEqual(client._auth().sessdata, SESSDATA_DUMMY)

    def test_from_env_without_cookie_raises_value_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                BiliClient.from_env()

    def test_extract_bvid(self):
        self.assertEqual(extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD/?p=1"), "BV1xx411c7mD")
        with self.assertRaises(InvalidBvidError):
            extract_bvid("not-a-bvid")

    def test_safe_filename_blocks_traversal(self):
        self.assertEqual(client_mod._safe_filename("../../etc/passwd"), "_.._etc_passwd")
        self.assertEqual(client_mod._safe_filename(""), "video")


# ═══ 3. 认证与 whoami / validate_cookie ═══════════════════════════════════════

class TestWhoamiAndValidate(ClientCase):
    def test_whoami_returns_normalized_user(self):
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)) as call:
            me = self.client().whoami()
        self.assertEqual(me["id"], "42")
        self.assertEqual(me["name"], "测试用户")
        self.assertEqual(set(me), {"id", "name", "username", "level", "coins", "sign", "vip"})
        # 传入的必须是该客户端的 Credential（占位 SESSDATA）
        self.assertEqual(call.call_args[0][0].sessdata, SESSDATA_DUMMY)

    def test_validate_cookie_uses_whoami(self):
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)):
            self.assertEqual(self.client().validate_cookie(), self.client().whoami())

    def test_validate_cookie_without_credentials_raises_authentication_error(self):
        with self.assertRaises(AuthenticationError):
            BiliClient().validate_cookie()
        with self.assertRaises(AuthenticationError):
            BiliClient().whoami()

    def test_whoami_propagates_sdk_auth_error(self):
        with patch.object(
            client_mod.user, "get_self_info",
            AsyncMock(side_effect=ResponseCodeException(-101, "账号未登录")),
        ):
            with self.assertRaises(AuthenticationError):
                self.client().validate_cookie()

    def test_from_env_validate_true_calls_whoami(self):
        env = {"BILI_COOKIE": f"SESSDATA={SESSDATA_DUMMY}; bili_jct={JCT_DUMMY}"}
        with patch.dict(os.environ, env, clear=False), \
                patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)) as call:
            client = BiliClient.from_env(validate=True)
        self.assertEqual(client._auth().sessdata, SESSDATA_DUMMY)
        self.assertTrue(call.await_count == 1)

    def test_public_method_inventory_is_bindable(self):
        required = {
            "whoami": (),
            "validate_cookie": (),
            "get_video": ("bvid",),
            "get_user": ("uid",),
            "get_user_videos": ("uid",),
            "search_users": ("keyword",),
            "search_videos": ("keyword",),
            "get_hot": (),
            "get_rank": (),
            "get_feed": (),
            "get_my_dynamics": (),
            "get_my_dynamics_page": (),
            "post_dynamic": ("text",),
            "delete_dynamic": ("dynamic_id",),
            "get_favorites": (),
            "get_following": (),
            "get_watch_later": (),
            "get_history": (),
            "like": ("bvid",),
            "coin": ("bvid",),
            "triple": ("bvid",),
            "unfollow": ("uid",),
            "download_video": ("bvid",),
            "download_audio": ("bvid",),
        }
        for name, args in required.items():
            with self.subTest(method=name):
                method = getattr(BiliClient, name, None)
                self.assertIsNotNone(method, f"公开方法 {name} 缺失")
                sig = inspect.signature(method)
                try:
                    sig.bind_partial(MagicMock(), *args)
                except TypeError as exc:  # pragma: no cover
                    self.fail(f"{name} 参数不可绑定: {exc}")


# ═══ 4. 视频详情 / 评论 / AI 总结 ══════════════════════════════════════════════

class TestVideo(ClientCase):
    def test_video_payload_shape(self):
        video_cls, _ = fake_video_cls()
        with patch.object(client_mod.video, "Video", video_cls):
            payload = self.client().get_video("BV1xx411c7mD")
        self.assertEqual(
            set(payload), {"video", "subtitle", "ai_summary", "comments", "related", "warnings"}
        )
        self.assertEqual(payload["video"]["bvid"], "BV1xx411c7mD")
        self.assertEqual(payload["video"]["title"], "示例视频")  # HTML 标签已剥离
        self.assertEqual(payload["video"]["duration"], "02:05")
        self.assertEqual(payload["subtitle"], {"available": False, "format": "timeline", "text": "", "items": []})
        self.assertEqual(payload["ai_summary"], "")
        self.assertEqual(payload["comments"], [])
        self.assertEqual(payload["warnings"], [])

    def test_comments_use_list_api_not_comment_object(self):
        video_cls, inst = fake_video_cls()
        replies = [{
            "rpid_str": "1", "like": 3, "rcount": 2,
            "member": {"mid": 9, "uname": "评论者"},
            "content": {"message": "你好"},
        }]
        comment_ctor = MagicMock(side_effect=AssertionError("不应构造 comment.Comment"))
        with patch.object(client_mod.video, "Video", video_cls), \
                patch.object(client_mod.comment, "get_comments", AsyncMock(return_value={"replies": replies})) as getcmt, \
                patch.object(client_mod.comment, "Comment", comment_ctor):
            payload = self.client().get_video("BV1xx411c7mD", comments=True)
        comment_ctor.assert_not_called()
        kwargs = getcmt.call_args.kwargs
        self.assertEqual(kwargs["oid"], VIDEO_INFO["aid"])
        self.assertEqual(kwargs["type_"], client_mod.comment.CommentResourceType.VIDEO)
        self.assertEqual(kwargs["page_index"], 1)
        self.assertEqual(payload["comments"][0]["message"], "你好")
        self.assertEqual(payload["comments"][0]["author"]["name"], "评论者")

    def test_comments_empty_replies_is_legit_empty_state(self):
        video_cls, _ = fake_video_cls()
        with patch.object(client_mod.video, "Video", video_cls), \
                patch.object(client_mod.comment, "get_comments", AsyncMock(return_value={"replies": None})):
            payload = self.client().get_video("BV1xx411c7mD", comments=True)
        self.assertEqual(payload["comments"], [])
        self.assertEqual(payload["warnings"], [])

    def test_comments_authentication_error_is_not_a_bare_typeerror(self):
        video_cls, _ = fake_video_cls()
        with patch.object(client_mod.video, "Video", video_cls), \
                patch.object(
                    client_mod.comment, "get_comments",
                    AsyncMock(side_effect=CredentialNoSessdataException()),
                ):
            with self.assertRaises(AuthenticationError):
                self.client().get_video("BV1xx411c7mD", comments=True)

    def test_comments_missing_aid_is_explicit_error(self):
        video_cls, inst = fake_video_cls(get_info={"bvid": "BV1xx411c7mD"})
        with patch.object(client_mod.video, "Video", video_cls):
            with self.assertRaises(BiliError) as ctx:
                self.client().get_video("BV1xx411c7mD", comments=True)
        self.assertNotIsInstance(ctx.exception, TypeError)
        self.assertIn("aid", str(ctx.exception))

    def test_ai_summary_present(self):
        video_cls, inst = fake_video_cls()
        with patch.object(client_mod.video, "Video", video_cls):
            payload = self.client().get_video("BV1xx411c7mD", ai_summary=True)
        self.assertEqual(payload["ai_summary"], "AI 总结")
        self.assertEqual(payload["warnings"], [])
        # 17.4.2 的 get_ai_conclusion 没有 credential 形参
        self.assertEqual(inst.get_ai_conclusion.call_args.kwargs, {"cid": 999})

    def test_ai_summary_unknown_code_minus_one_is_not_treated_as_absent(self):
        # SDK 的 _process_response 会在“响应未含 code 字段”或“旧式 OK != 1”时**自造**通用
        # 错误码 -1；它**不是**“该视频没有 AI 总结”的证据。必须作为未知服务错误上抛，
        # 而不是被折成良性空值 + 警告。
        video_cls, _ = fake_video_cls(ai_exc=ResponseCodeException(-1, "API 返回数据未含 code 字段"))
        with patch.object(client_mod.video, "Video", video_cls):
            with self.assertRaises(BiliError) as ctx:
                self.client().get_video("BV1xx411c7mD", ai_summary=True)
        self.assertNotIsInstance(
            ctx.exception, (AuthenticationError, RateLimitError, NotFoundError, NetworkError)
        )
        self.assertIn("-1", str(ctx.exception))          # 保留原始 code
        self.assertIn("获取 AI 总结", str(ctx.exception))
        self.assertNotIn("没有 AI 总结", str(ctx.exception))

    def test_ai_summary_empty_payload_is_observation_not_speculation(self):
        video_cls, _ = fake_video_cls(ai_result={"model_result": None})
        with patch.object(client_mod.video, "Video", video_cls):
            payload = self.client().get_video("BV1xx411c7mD", ai_summary=True)
        self.assertEqual(payload["ai_summary"], "")
        warning = payload["warnings"][0]
        self.assertEqual(warning["code"], "ai_summary_empty")
        # 只陈述“本次响应没有可用内容”，并显式声明**不**推断“该视频没有总结”
        self.assertIn("model_result.summary 为空", warning["message"])
        self.assertIn("不表示", warning["message"])
        self.assertEqual(len(payload["warnings"]), 1)

    def test_ai_summary_rate_limit_is_not_swallowed(self):
        video_cls, _ = fake_video_cls(ai_exc=ResponseCodeException(-412, "请求被拦截"))
        with patch.object(client_mod.video, "Video", video_cls):
            with self.assertRaises(RateLimitError):
                self.client().get_video("BV1xx411c7mD", ai_summary=True)

    def test_ai_summary_network_error_is_not_swallowed(self):
        video_cls, _ = fake_video_cls(ai_exc=NetworkException(500, "boom"))
        with patch.object(client_mod.video, "Video", video_cls):
            with self.assertRaises(NetworkError):
                self.client().get_video("BV1xx411c7mD", ai_summary=True)

    def test_ai_summary_skill_absent_signature_guard(self):
        # 回归护栏：不得再传 credential（该形参在 17.4.2 不存在）
        sig = inspect.signature(client_mod.video.Video.get_ai_conclusion)
        self.assertNotIn("credential", sig.parameters)

    def test_related_videos(self):
        video_cls, _ = fake_video_cls(get_related=[{"bvid": "BV1xx411c7mE", "title": "相关"}])
        with patch.object(client_mod.video, "Video", video_cls):
            payload = self.client().get_video("BV1xx411c7mD", related=True)
        self.assertEqual(payload["related"][0]["bvid"], "BV1xx411c7mE")

    def test_subtitle_absent_is_legit_empty_state(self):
        video_cls, _ = fake_video_cls(player_info={"subtitle": {"subtitles": []}})
        with patch.object(client_mod.video, "Video", video_cls):
            payload = self.client().get_video("BV1xx411c7mD", subtitle=True, subtitle_timeline=True)
        self.assertFalse(payload["subtitle"]["available"])
        self.assertEqual(payload["subtitle"]["items"], [])

    def test_invalid_bvid(self):
        with self.assertRaises(InvalidBvidError):
            self.client().get_video("nope")


# ═══ 5. 用户 / 搜索 / 热门 / 排行榜 ════════════════════════════════════════════

class TestUserSearchDiscover(ClientCase):
    def test_get_user(self):
        user_cls, _ = fake_user_cls()
        with patch.object(client_mod.user, "User", user_cls):
            payload = self.client().get_user(42)
        self.assertEqual(set(payload), {"user", "relation"})
        self.assertEqual(payload["user"]["id"], "42")
        self.assertEqual(payload["relation"], {"following": 11, "follower": 22})

    def test_get_user_videos(self):
        video_item = {"bvid": "BV1xx411c7mD", "title": "t", "duration": 65, "play": 9,
                      "owner": {"mid": 7, "name": "UP 主"}}
        user_cls, inst = fake_user_cls(videos={"list": {"vlist": [video_item]}})
        with patch.object(client_mod.user, "User", user_cls):
            items = self.client().get_user_videos(42, count=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["duration"], "01:05")
        self.assertEqual(inst.get_videos.call_args.kwargs, {"pn": 1})

    def test_search_videos_and_users(self):
        with patch.object(
            client_mod.search, "search_by_type",
            AsyncMock(return_value={"result": [{"bvid": "BV1xx411c7mD", "title": "t", "duration": "01:00"}]}),
        ) as call:
            items = self.client().search_videos("python", count=5)
        self.assertEqual(items[0]["bvid"], "BV1xx411c7mD")
        self.assertEqual(call.call_args.kwargs["search_type"], client_mod.search.SearchObjectType.VIDEO)

        with patch.object(
            client_mod.search, "search_by_type",
            AsyncMock(return_value={"result": [{"mid": 5, "uname": "u", "fans": 3}]}),
        ) as call:
            users = self.client().search_users("python")
        self.assertEqual(users[0]["name"], "u")
        self.assertEqual(call.call_args.kwargs["search_type"], client_mod.search.SearchObjectType.USER)

    def test_search_empty_result_is_legit_empty_state(self):
        with patch.object(client_mod.search, "search_by_type", AsyncMock(return_value={})):
            self.assertEqual(self.client().search_videos("none"), [])

    def test_get_hot(self):
        with patch.object(
            client_mod.hot, "get_hot_videos", AsyncMock(return_value={"list": [VIDEO_INFO]})
        ) as call:
            items = self.client().get_hot(page=2, count=5)
        self.assertEqual(call.call_args.kwargs, {"pn": 2, "ps": 5})
        self.assertEqual(items[0]["stats"]["view"], 10)

    def test_get_rank_truncation_and_day_is_noop_param(self):
        from bilibili_api.rank import RankType
        payload = {"list": [VIDEO_INFO, VIDEO_INFO, VIDEO_INFO]}
        with patch.object(client_mod.rank, "get_rank", AsyncMock(return_value=payload)) as call:
            items = self.client().get_rank(day=3, count=2)
        self.assertEqual(len(items), 2)
        # 不向 SDK 传 day：全站榜（RankType.All）会忽略它，传了只会制造“选对了榜单”的错觉
        self.assertEqual(call.call_args.kwargs, {"type_": RankType.All})
        # day 为已废弃的兼容形参：任意取值都不得报错、也不改变结果
        with patch.object(client_mod.rank, "get_rank", AsyncMock(return_value=payload)):
            self.assertEqual(len(self.client().get_rank(day=1)), 3)
            self.assertEqual(len(self.client().get_rank(day=30)), 3)

    def test_get_rank_request_params_ignore_day(self):
        """用**真实** ``rank.get_rank`` + 假 ``Api`` 捕获真实请求参数，证明 day 不生效。

        这不是 mock 语义下的假设：``rank.get_rank`` 是 SDK 本体，只有最外层的 ``Api``
        （真正发请求的类）被替换为记录参数、不回网络的替身。
        """
        captured: list[dict] = []

        class CapturingApi:
            def __init__(self, **api):
                captured.append({"api": api, "params": {}})

            def update_params(self, **kwargs):
                captured[-1]["params"] = kwargs
                return self

            @property
            async def result(self):
                return {"list": []}

        with patch.object(client_mod.rank, "Api", CapturingApi):
            self.client().get_rank(day=3)
            self.client().get_rank(day=7)
            self.client().get_rank(day=1)     # 已废弃形参：不再抛错
            self.client().get_rank(day=30)

        self.assertEqual(len(captured), 4)
        snapshots = [c["params"] for c in captured]
        # 全站榜走 ranking/v2 接口（RankType.All），请求里没有 day，也不含 rank_type 语义
        for c in captured:
            self.assertIn("ranking/v2", c["api"]["url"])
            self.assertNotIn("day", c["params"])
        self.assertEqual(snapshots[0], {"web_location": "333.934", "rid": 0})
        self.assertTrue(
            all(s == snapshots[0] for s in snapshots),
            f"day 取值不同却生成了不同请求参数: {snapshots}",
        )

    def test_rank_day_type_enum_guard(self):
        # SDK 事实核对：17.4.2 的 RankDayType 没有 ONE_DAY（旧实现在此崩），本技能已不使用它
        from bilibili_api.rank import RankDayType
        self.assertFalse(hasattr(RankDayType, "ONE_DAY"))
        self.assertTrue(hasattr(RankDayType, "WEEK"))

    def test_rank_error_propagates(self):
        with patch.object(
            client_mod.rank, "get_rank", AsyncMock(side_effect=NetworkException(500, "boom"))
        ):
            with self.assertRaises(NetworkError):
                self.client().get_rank()


# ═══ 6. 动态流（get_feed / get_my_dynamics） ══════════════════════════════════

class TestDynamicFeed(ClientCase):
    FEED_RESULT = {"items": [{"id_str": "1"}], "offset": "1234567890123456789", "has_more": True}

    def _patch_page_info(self, result=None):
        return patch.object(
            client_mod.dynamic, "get_dynamic_page_info",
            AsyncMock(return_value=self.FEED_RESULT if result is None else result),
        )

    def test_get_feed_uses_dynamic_page_info(self):
        for offset, expected in [
            (None, None), (0, None), ("", None), ("0", None),
            ("1234567890123456789", "1234567890123456789"),
            (1234567890123456789, 1234567890123456789),
        ]:
            with self.subTest(offset=offset):
                with self._patch_page_info() as call, patch.object(
                    client_mod.dynamic, "get_dynamic_page_UPs_info",
                    MagicMock(side_effect=AssertionError("get_dynamic_page_UPs_info 是 UP 主列表接口，不应被调用")),
                ):
                    payload = self.client().get_feed(offset=offset)
                self.assertEqual(call.call_args.kwargs["offset"], expected)
                self.assertEqual(payload, self.FEED_RESULT)

    def test_get_feed_passes_credential(self):
        with self._patch_page_info() as call:
            self.client().get_feed()
        self.assertEqual(call.call_args.kwargs["credential"].sessdata, SESSDATA_DUMMY)

    def test_get_feed_offset_type_is_validated(self):
        with self._patch_page_info():
            with self.assertRaises(TypeError):
                self.client().get_feed(offset=1.5)

    def test_get_feed_requires_login(self):
        with self.assertRaises(AuthenticationError):
            BiliClient().get_feed()

    def test_get_feed_error_propagates(self):
        with patch.object(
            client_mod.dynamic, "get_dynamic_page_info",
            AsyncMock(side_effect=ResponseCodeException(-352, "风控校验失败")),
        ):
            with self.assertRaises(BiliError):
                self.client().get_feed()

    # ── 旧版 get_my_dynamics（int 游标 + cards），运行契约与历史版本一致 ─────────

    OLD_CARD = {
        "desc": {"dynamic_id_str": "old-1", "timestamp": 1700000000},
        "card": {"item": {"content": "旧卡片正文"}},
    }

    def test_get_my_dynamics_uses_old_api_cards_and_int_offset(self):
        user_cls, inst = fake_user_cls(dynamics={"cards": [self.OLD_CARD], "next_offset": 4242})
        inst.get_dynamics_new = MagicMock(side_effect=AssertionError("新版接口不应被 get_my_dynamics 调用"))
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)), \
                patch.object(client_mod.user, "User", user_cls):
            items = self.client().get_my_dynamics(offset=7)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "old-1")
        self.assertEqual(items[0]["text"], "旧卡片正文")
        self.assertTrue(items[0]["published_at"])   # 旧格式：顶层 desc.timestamp
        # 旧 API：int 游标原样透传；返回契约仍是 list
        self.assertEqual(inst.get_dynamics.call_args.kwargs, {"offset": 7})
        inst.get_dynamics_new.assert_not_called()

    def test_get_my_dynamics_default_offset_is_int_zero(self):
        user_cls, inst = fake_user_cls(dynamics={"cards": []})
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)), \
                patch.object(client_mod.user, "User", user_cls):
            self.assertEqual(self.client().get_my_dynamics(), [])
        self.assertEqual(inst.get_dynamics.call_args.kwargs, {"offset": 0})

    def test_get_my_dynamics_error_propagates(self):
        user_cls, inst = fake_user_cls()
        inst.get_dynamics = AsyncMock(side_effect=ResponseCodeException(-412, "请求被拦截"))
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)), \
                patch.object(client_mod.user, "User", user_cls):
            with self.assertRaises(RateLimitError):
                self.client().get_my_dynamics()

    # ── 新版 get_my_dynamics_page（str 游标 + items），与旧 API 相互独立 ─────────

    NEW_ITEM = {
        "id_str": "dyn-1",
        "modules": {
            "module_author": {"name": "UP 主", "pub_time": "刚刚", "pub_ts": 1700000000},
            "module_dynamic": {"desc": {"text": "动态正文"}},
            "module_stat": {"comment": {"count": 1}, "like": {"count": 2}},
        },
    }

    def test_get_my_dynamics_page_uses_new_api_with_str_cursor(self):
        dynamics = {"items": [self.NEW_ITEM], "offset": "456", "has_more": False}
        user_cls, inst = fake_user_cls(dynamics_new=dynamics)
        inst.get_dynamics = MagicMock(side_effect=AssertionError("旧接口 get_dynamics 不应被调用"))
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)), \
                patch.object(client_mod.user, "User", user_cls):
            page = self.client().get_my_dynamics_page(offset="123")
        self.assertEqual(page["offset"], "456")
        self.assertFalse(page["has_more"])
        self.assertEqual(page["items"][0]["text"], "动态正文")
        self.assertEqual(page["items"][0]["stats"], {"comment": 1, "like": 2})
        self.assertTrue(page["items"][0]["published_at"])   # 新格式：module_author.pub_ts
        # uid 来自 get_self_info，offset 类型为 str
        self.assertEqual(user_cls.call_args.kwargs["uid"], 42)
        self.assertEqual(inst.get_dynamics_new.call_args.kwargs, {"offset": "123"})

    def test_get_my_dynamics_page_error_propagates(self):
        user_cls, inst = fake_user_cls()
        inst.get_dynamics_new = AsyncMock(side_effect=ResponseCodeException(-412, "请求被拦截"))
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)), \
                patch.object(client_mod.user, "User", user_cls):
            with self.assertRaises(RateLimitError):
                self.client().get_my_dynamics_page()

    def test_normalize_dynamic_item_supports_both_timestamp_formats(self):
        from scripts.payloads import normalize_dynamic_item
        expected = datetime.fromtimestamp(1700000000).isoformat()
        # 新版聚合物：时间戳在 modules.module_author.pub_ts（秒）
        new_item = normalize_dynamic_item(self.NEW_ITEM)
        self.assertEqual(new_item["id"], "dyn-1")
        self.assertEqual(new_item["published_at"], expected)
        # 旧版 space_history 卡片：时间戳在顶层 desc.timestamp（兼容分支保留）
        old_item = normalize_dynamic_item(self.OLD_CARD)
        self.assertEqual(old_item["id"], "old-1")
        self.assertEqual(old_item["published_at"], expected)
        # 两种格式都缺失时为空字符串（不猜测）
        self.assertEqual(normalize_dynamic_item({"id_str": "x", "modules": {}})["published_at"], "")

    def test_get_my_dynamics_missing_mid_is_explicit_error(self):
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value={"name": "x"})):
            with self.assertRaises(AuthenticationError):
                self.client().get_my_dynamics()
            with self.assertRaises(AuthenticationError):
                self.client().get_my_dynamics_page()


# ═══ 7. 收藏 / 关注 / 稍后再看 / 历史 ══════════════════════════════════════════

class TestFavoritesHistory(ClientCase):
    def test_get_favorites_folders(self):
        folders = {"list": [{"id": 7, "title": "默认收藏夹", "media_count": 3}]}
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)), \
                patch.object(client_mod.favorite_list, "get_video_favorite_list", AsyncMock(return_value=folders)) as call:
            result = self.client().get_favorites()
        self.assertEqual(result[0], {"id": 7, "title": "默认收藏夹", "media_count": 3})
        self.assertEqual(call.call_args.kwargs["uid"], 42)

    def test_get_favorites_folder_content(self):
        medias = {"medias": [{"bvid": "BV1xx411c7mD", "title": "t", "duration": 30, "upper": {"name": "u"}}]}
        with patch.object(
            client_mod.favorite_list, "get_video_favorite_list_content", AsyncMock(return_value=medias)
        ) as call:
            result = self.client().get_favorites(folder_id=7, page=2, count=1)
        self.assertEqual(result[0]["duration"], "00:30")
        self.assertEqual(call.call_args.kwargs["media_id"], 7)
        self.assertEqual(call.call_args.kwargs["page"], 2)

    def test_get_following(self):
        user_cls, inst = fake_user_cls(followings={"list": [{"mid": 5, "uname": "u", "sign": "s"}]})
        with patch.object(client_mod.user, "get_self_info", AsyncMock(return_value=USER_INFO)), \
                patch.object(client_mod.user, "User", user_cls):
            result = self.client().get_following(page=3)
        self.assertEqual(result[0]["name"], "u")
        self.assertEqual(inst.get_followings.call_args.kwargs, {"pn": 3})

    def test_get_watch_later_uses_user_module(self):
        payload = {"list": [{"bvid": "BV1xx411c7mD", "title": "稍后再看", "duration": 90,
                             "owner": {"name": "UP 主"}}]}
        with patch.object(client_mod.user, "get_toview_list", AsyncMock(return_value=payload)) as call:
            result = self.client().get_watch_later()
        self.assertEqual(call.call_args.kwargs["credential"].sessdata, SESSDATA_DUMMY)
        self.assertEqual(result[0]["title"], "稍后再看")
        self.assertEqual(result[0]["author"], "UP 主")
        self.assertEqual(result[0]["duration"], "01:30")

    def test_get_watch_later_error_propagates(self):
        with patch.object(
            client_mod.user, "get_toview_list", AsyncMock(side_effect=NetworkException(500, "boom"))
        ):
            with self.assertRaises(NetworkError):
                self.client().get_watch_later()

    def test_get_history_returns_normalized_items(self):
        payload = {"list": [{"title": "看过的视频",
                             "history": {"bvid": "BV1xx411c7mD", "view_at": 1700000000},
                             "owner": {"name": "UP 主"}}]}
        with patch.object(client_mod.user, "get_self_history", AsyncMock(return_value=payload)) as call:
            result = self.client().get_history()
        self.assertEqual(result[0]["bvid"], "BV1xx411c7mD")
        self.assertTrue(result[0]["viewed_at"])
        self.assertEqual(call.call_args.kwargs["credential"].sessdata, SESSDATA_DUMMY)

    def test_get_history_error_is_not_swallowed_into_empty_list(self):
        for exc, expected in [
            (ResponseCodeException(-412, "请求被拦截"), RateLimitError),
            (CredentialNoSessdataException(), AuthenticationError),
            (NetworkException(500, "boom"), NetworkError),
        ]:
            with self.subTest(exc=type(exc).__name__):
                with patch.object(client_mod.user, "get_self_history", AsyncMock(side_effect=exc)):
                    with self.assertRaises(expected):
                        self.client().get_history()

    def test_get_history_empty_list_is_legit_empty_state(self):
        with patch.object(client_mod.user, "get_self_history", AsyncMock(return_value={"list": None})):
            self.assertEqual(self.client().get_history(), [])


# ═══ 8. 写操作（仅认证护栏与替身调用，不触发真实写入） ══════════════════════════

class TestWriteOps(ClientCase):
    def test_like_coin_triple(self):
        video_cls, inst = fake_video_cls()
        with patch.object(client_mod.video, "Video", video_cls):
            self.assertEqual(
                self.client().like("BV1xx411c7mD"),
                {"success": True, "action": "like", "bvid": "BV1xx411c7mD"},
            )
            self.assertEqual(inst.like.call_args.kwargs, {"status": True})
            self.client().like("BV1xx411c7mD", undo=True)
            self.assertEqual(inst.like.call_args.kwargs, {"status": False})
            self.assertEqual(self.client().coin("BV1xx411c7mD", num=2)["action"], "coin")
            self.assertEqual(inst.pay_coin.call_args.kwargs, {"num": 2})
            self.assertEqual(self.client().triple("BV1xx411c7mD")["action"], "triple")
            inst.triple.assert_awaited_once()

    def test_unfollow(self):
        user_cls, inst = fake_user_cls()
        with patch.object(client_mod.user, "User", user_cls):
            result = self.client().unfollow(42)
        self.assertEqual(result, {"success": True, "action": "unfollow", "uid": 42})
        self.assertEqual(inst.modify_relation.call_args.kwargs,
                         {"relation": client_mod.user.RelationType.UNSUBSCRIBE})

    def test_write_ops_require_bili_jct(self):
        forbidden = MagicMock(side_effect=AssertionError("不应调用 SDK"))
        with patch.object(client_mod.video, "Video", forbidden), \
                patch.object(client_mod.user, "User", forbidden):
            for name, args in [("like", ("BV1xx411c7mD",)), ("coin", ("BV1xx411c7mD",)),
                               ("triple", ("BV1xx411c7mD",)), ("unfollow", (42,)),
                               ("post_dynamic", ("hi",)), ("delete_dynamic", (1,))]:
                with self.subTest(method=name):
                    with self.assertRaises(AuthenticationError):
                        getattr(self.read_only_client(), name)(*args)

    def test_post_dynamic_calls_send_dynamic_with_builder(self):
        with patch.object(client_mod.dynamic, "send_dynamic", AsyncMock(return_value={"code": 0})) as send:
            result = self.client().post_dynamic("你好")
        self.assertEqual(send.call_args.kwargs["credential"].bili_jct, JCT_DUMMY)
        self.assertEqual(result, {"code": 0})

    def test_post_dynamic_rejects_blank_text(self):
        with self.assertRaises(BiliError):
            self.client().post_dynamic("   ")

    def test_delete_dynamic(self):
        dynamic_cls = MagicMock()
        inst = MagicMock()
        inst.delete = AsyncMock(return_value={"code": 0})
        dynamic_cls.return_value = inst
        with patch.object(client_mod.dynamic, "Dynamic", dynamic_cls):
            result = self.client().delete_dynamic(123)
        self.assertEqual(result, {"code": 0})
        self.assertEqual(dynamic_cls.call_args.kwargs["dynamic_id"], 123)


# ═══ 9. 下载（全部替身，不写真实网络） ═════════════════════════════════════════

def fake_stream(url, dest):
    """替身下载：只在本地写出少量字节（异步，替代真实 HTTP 流式下载）。"""
    async def _impl():
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"fake")
        return 4
    return _impl()


class TestDownloads(ClientCase):
    def _patched(self, urls, info=None):
        """返回一组已启动的 patch 上下文（ExitStack），禁用下载相关网络与 ffmpeg。"""
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(client_mod, "_get_video_info",
                                        new=AsyncMock(return_value=VIDEO_INFO if info is None else info)))
        stack.enter_context(patch.object(client_mod, "_get_download_urls",
                                        new=AsyncMock(return_value=urls)))
        stack.enter_context(patch.object(client_mod, "_download_stream", new=fake_stream))
        merge = stack.enter_context(patch.object(client_mod, "_ffmpeg_merge", new=MagicMock(return_value=None)))
        return stack, merge

    def test_download_video_dash_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            urls = {"video_url": "https://v.example/video", "audio_url": "https://v.example/audio", "is_flv": False}
            stack, merge = self._patched(urls)
            with stack:
                out = self.client().download_video("BV1xx411c7mD", output_dir=tmp, filename="自定义")
            self.assertEqual(out, os.path.join(tmp, "自定义.mp4"))
            self.assertEqual(merge.call_args[0][2], out)

    def test_download_video_flv_direct(self):
        with tempfile.TemporaryDirectory() as tmp:
            urls = {"video_url": "https://v.example/flv", "audio_url": None, "is_flv": True}
            stack, merge = self._patched(urls, info=dict(VIDEO_INFO, title="示例视频"))
            with stack:
                out = self.client().download_video("BV1xx411c7mD", output_dir=tmp)
            self.assertEqual(out, os.path.join(tmp, "示例视频.mp4"))
            merge.assert_not_called()

    def test_download_video_title_is_traversal_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            urls = {"video_url": "https://v.example/flv", "audio_url": None, "is_flv": True}
            stack, _ = self._patched(urls, info=dict(VIDEO_INFO, title="../../etc/passwd"))
            with stack:
                out = self.client().download_video("BV1xx411c7mD", output_dir=tmp)
            self.assertEqual(os.path.dirname(out), tmp)
            self.assertEqual(os.path.basename(out), "_.._etc_passwd.mp4")

    def test_download_audio_dash(self):
        with tempfile.TemporaryDirectory() as tmp:
            urls = {"video_url": "https://v.example/video", "audio_url": "https://v.example/audio", "is_flv": False}
            stack, _ = self._patched(urls)
            with stack:
                out = self.client().download_audio("BV1xx411c7mD", output_dir=tmp, filename="音轨")
            self.assertEqual(out, os.path.join(tmp, "音轨.m4a"))
            self.assertTrue(Path(out).exists())

    def test_download_audio_without_audio_stream_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            urls = {"video_url": "https://v.example/video", "audio_url": None, "is_flv": False}
            stack, _ = self._patched(urls)
            with stack:
                with self.assertRaises(BiliError):
                    self.client().download_audio("BV1xx411c7mD", output_dir=tmp)


# ═══ 10. 异常映射 ══════════════════════════════════════════════════════════════

class TestErrorMapping(ClientCase):
    def test_mapping_table(self):
        cases = [
            (CredentialNoSessdataException(), AuthenticationError),
            (CredentialNoBiliJctException(), AuthenticationError),
            (ResponseCodeException(-101, "账号未登录"), AuthenticationError),
            (ResponseCodeException(-111, "csrf 校验失败"), AuthenticationError),
            (ResponseCodeException(-404, "啥都木有"), NotFoundError),
            (ResponseCodeException(62002, "稿件不可见"), NotFoundError),
            (ResponseCodeException(-412, "请求被拦截"), RateLimitError),
            (NetworkException(500, "boom"), NetworkError),
            (ResponseException("boom"), NetworkError),
            (aiohttp.ClientError("boom"), NetworkError),
            (asyncio.TimeoutError(), NetworkError),
            (ValueError("boom"), BiliError),
        ]
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                self.assertIsInstance(_map_error("动作", exc), expected)

    def test_unknown_code_keeps_code_in_message(self):
        mapped = _map_error("动作", ResponseCodeException(-999, "未知"))
        self.assertIsInstance(mapped, BiliError)
        self.assertIn("-999", str(mapped))

    def test_existing_bili_error_passes_through(self):
        original = AuthenticationError("keep me")
        self.assertIs(_map_error("动作", original), original)


# ═══ 11. SDK 签名合规（真实签名绑定，无需网络） ═════════════════════════════

class TestSdkSignatureCompliance(ClientCase):
    """对每个真实 SDK 入口做「参数可绑定」检查。

    这是审计建议的最小 CI 门禁：不联网、不用凭据，只验证 ``scripts/client.py`` 里使用的
    调用形态在锁定版本（17.4.2）的签名下确实成立，从而防止再次出现
    ``unexpected keyword argument`` / 符号缺失这一类“调用即崩”。
    """

    def _bind(self, func, *args, **kwargs):
        try:
            inspect.signature(func).bind(*args, **kwargs)
        except TypeError as exc:
            self.fail(f"{func} 参数不可绑定: {exc}")

    def test_user_module_signatures(self):
        cred = self.client()._auth()
        self._bind(sdk_user.get_self_info, credential=cred)
        self._bind(sdk_user.get_self_history, credential=cred)
        self._bind(sdk_user.get_toview_list, credential=cred)
        inst = object.__new__(sdk_user.User)
        self._bind(sdk_user.User.get_user_info, inst)
        self._bind(sdk_user.User.get_relation_info, inst)
        self._bind(sdk_user.User.get_videos, inst, pn=1)
        self._bind(sdk_user.User.get_followings, inst, pn=1)
        self._bind(sdk_user.User.get_dynamics_new, inst, offset="")   # 新版：str 游标（get_my_dynamics_page）
        self._bind(sdk_user.User.modify_relation, inst, relation=sdk_user.RelationType.UNSUBSCRIBE)
        self._bind(sdk_user.User.get_dynamics, inst, offset=0)        # 旧版：int 游标（get_my_dynamics）

    def test_video_module_signatures(self):
        cred = self.client()._auth()
        inst = object.__new__(client_mod.video.Video)
        self._bind(client_mod.video.Video.get_info, inst)
        self._bind(client_mod.video.Video.get_pages, inst)
        self._bind(client_mod.video.Video.get_player_info, inst, cid=1)
        self._bind(client_mod.video.Video.get_related, inst)
        self._bind(client_mod.video.Video.like, inst, status=True)
        self._bind(client_mod.video.Video.pay_coin, inst, num=1)
        self._bind(client_mod.video.Video.triple, inst)
        self._bind(client_mod.video.Video.get_download_url, inst, page_index=0)
        self._bind(client_mod.video.Video.get_ai_conclusion, inst, cid=1)
        # 该形参在 17.4.2 不存在，必须继续报不可绑定（回归护栏）
        with self.assertRaises(TypeError):
            inspect.signature(client_mod.video.Video.get_ai_conclusion).bind(inst, cid=1, credential=cred)
        self._bind(client_mod.Credential, sessdata="x", bili_jct="y", ac_time_value="",
                   buvid3="b", buvid4="", dedeuserid="1")

    def test_comment_module_signatures(self):
        cred = self.client()._auth()
        self._bind(client_mod.comment.get_comments, 1,
                   type_=client_mod.comment.CommentResourceType.VIDEO, page_index=1, credential=cred)
        self._bind(client_mod.comment.get_comments_lazy, 1,
                   type_=client_mod.comment.CommentResourceType.VIDEO, offset="", credential=cred)
        # Comment 只用于单条评论操作：构造需要 rpid，不能用来取列表
        with self.assertRaises(TypeError):
            inspect.signature(client_mod.comment.Comment.__init__).bind(
                object.__new__(client_mod.comment.Comment), oid=1,
                type_=client_mod.comment.CommentResourceType.VIDEO, credential=cred,
            )

    def test_dynamic_module_signatures(self):
        cred = self.client()._auth()
        self._bind(client_mod.dynamic.get_dynamic_page_info, credential=cred, offset=None)
        with self.assertRaises(TypeError):
            inspect.signature(client_mod.dynamic.get_dynamic_page_info).bind(credential=cred, offset=None, bogus=1)
        self._bind(client_mod.dynamic.get_dynamic_page_UPs_info, credential=cred)
        self._bind(client_mod.dynamic.send_dynamic, info=None, credential=cred)
        self._bind(client_mod.dynamic.Dynamic.__init__, object.__new__(client_mod.dynamic.Dynamic),
                   dynamic_id=1, credential=cred)

    def test_favorite_hot_rank_search_signatures(self):
        cred = self.client()._auth()
        self._bind(client_mod.favorite_list.get_video_favorite_list, uid=1, credential=cred)
        self._bind(client_mod.favorite_list.get_video_favorite_list_content,
                   media_id=1, page=1, credential=cred)
        self._bind(client_mod.hot.get_hot_videos, pn=1, ps=1)
        from bilibili_api.rank import RankDayType, RankType
        # SDK 签名接受 day；但客户端对全站榜（RankType.All）**不**传 day（见上方请求参数快照测试）
        self._bind(client_mod.rank.get_rank, type_=RankType.All, day=RankDayType.THREE_DAY)
        self._bind(client_mod.search.search_by_type, "kw",
                   search_type=client_mod.search.SearchObjectType.VIDEO, page=1)

    def test_download_detector_signatures(self):
        from bilibili_api.video import AudioQuality, VideoDownloadURLDataDetecter
        detector = VideoDownloadURLDataDetecter({"dash": {}})
        self.assertTrue(callable(detector.check_flv_mp4_stream))
        self._bind(VideoDownloadURLDataDetecter.detect_best_streams, detector,
                   audio_max_quality=AudioQuality._192K, no_dolby_audio=True, no_hires=True)

    def test_helper_calls_do_not_use_missing_symbols(self):
        # 稍后再看：必须走 user 模块（favorite_list 无该符号）
        self.assertTrue(hasattr(sdk_user, "get_toview_list"))
        self.assertFalse(hasattr(sdk_favorite_list, "get_video_toview_list"))
        # 动态流：带 offset 的必须是 get_dynamic_page_info
        params = inspect.signature(client_mod.dynamic.get_dynamic_page_info).parameters
        self.assertIn("offset", params)
        self.assertNotIn("offset", inspect.signature(client_mod.dynamic.get_dynamic_page_UPs_info).parameters)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
