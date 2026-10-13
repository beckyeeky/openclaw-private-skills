#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线静态语法校验（Loon 插件 / Rewrite V2 / Script V2）。

重要边界
--------
这不是 Loon 解析器，也不模拟 Loon 的加载校验。它只按本技能文档化的官方规则
（来源：https://nsloon.app/docs/Rewrite/rewrite_v2 、/docs/Script/script_v2 、/docs/Plugin/）
对文本做**启发式**匹配，用来拦住最常见的、会导致整条 Rewrite 被拒的写法。

- 通过校验 != Loon 一定接受；失败必是可疑写法，需人工对照官方文档。
- 命名参数检查是启发式的（只看 `标签=` 且前面是 `(` 或 `,` 的形式），
  个别含 `=` 的字符串/正则可能误报，请人工复核。
- 真正的有效性只能在目标 TestFlight build 真机加载并看日志确认。

只报「错误」还是「非致命提示」
------------------------------
官方文档数据：

- 插件元数据表把 `#!name/#!desc/.../#!loon_version/#!date/#!tag/#!type` 平铺列出，
  **没有标注任何必填字段**（`#!type` 省略默认 normal、`#!system` 省略表示全部支持）。
  因此缺 `#!date` / `#!loon_version` 仅作 **本仓发布规范建议**（advisory），不是 Loon 语法错误。
- MitM 段落名官方**两种大小写并存**：`/docs/Plugin/` 完整示例写作 `[Mitm]`，
  `/docs/MitM/` 写作 `[MitM]`；官方未声明大小写敏感，也不声明 `[MITM]` 非法。
  静态检查因此**不把任何大小写判为非法**（只给非致命提示）。
- Script V2 的 `with` 是**可选的**（官方原文：「没有字段时省略整个 `with`。」），
  省略 `with` 不报错；`then` 后允许多个空白（官方说明「新版语法不会按空格拆分整行」）。

非致命提示的 code 见 ADVISORY_CODES，**不计入退出码**。

用法
----
    python3 scripts/check-templates.py            # 校验 templates/*.plugin
    python3 scripts/check-templates.py --self-test  # 跑内置正/反例
    python3 scripts/check-templates.py FILE...    # 校验指定文件
退出码：0 无错误（允许有非致命提示）；1 有错误；2 用法错误。
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.normpath(os.path.join(HERE, "..", "templates"))

REJECT_ALLOWED = {"reject", "reject_img", "reject_dict", "reject_array", "reject_video"}
REJECT_BANNED = {
    "reject-img": "reject_img",
    "reject-dict": "reject_dict",
    "reject-array": "reject_array",
    "reject-video": "reject_video",
    "reject-200": "reject",
}
MOCK_MAGIC_BODY = {"empty", "image", "json-object", "json-array", "video"}
NAMED_PARAM_KW = (
    "name|value|pattern|replacement|location|path|filter|file|type|data|base64|status|body"
)
NAMED_PARAM_RE = re.compile(r"[\(,]\s*(" + NAMED_PARAM_KW + r")\s*=")
WITH_ALLOWED = {
    "enable",
    "tag",
    "img_url",
    "timeout",
    "debug",
    "requires_body",
    "binary_body_mode",
}
NON_HTTP_TRIGGERS = ("cron ", "network-changed ", "generic ")
# 非致命提示：官方未规定为必填 / 未声明非法，只作发布规范提醒，不计入退出码。
ADVISORY_CODES = {"meta-optional", "mitm-case"}
# 官方文档中实际出现的两种 MitM 段落名写法（/docs/Plugin/ 用 [Mitm]，/docs/MitM/ 用 [MitM]）。
MITM_SECTIONS_DOCUMENTED = {"[Mitm]", "[MitM]"}
# 本仓元数据规范建议（官方未标必填；缺失只提示，不判错）。
ADVISORY_METADATA = ("#!loon_version", "#!date")


def issues_for_rewrite_line(line):
    """对一条 Rewrite 行返回 [(code, message), ...]。"""
    out = []
    m = re.match(r"^([A-Za-z][\w-]*)\s+if\s", line)
    if not m:
        return out
    phase = m.group(1)
    if phase not in ("request", "response"):
        out.append(
            (
                "phase",
                "阶段关键字必须是 request / response（http-request/http-response 未正式发布）",
            )
        )
        return out

    idx = line.find(" then ")
    actions = line[idx + 6 :] if idx >= 0 else ""

    # 命名参数
    nm = NAMED_PARAM_RE.search(actions)
    if nm:
        out.append(
            (
                "named-param",
                "Action 只允许位置参数，发现 `%s=`" % nm.group(1),
            )
        )

    # header.delete
    if re.search(r"\.header\.delete\s*\(", actions):
        out.append(("header-del", "官方方法名是 header.del(...)，不是 header.delete(...)"))

    # reject 系列
    for tok in re.findall(r"\breject(?:[-_][A-Za-z0-9]+)?\b", actions):
        if tok in REJECT_BANNED:
            out.append(("reject-name", "%s 不是 V2 方法，应为 %s(...)" % (tok, REJECT_BANNED[tok])))
        elif tok not in REJECT_ALLOWED:
            out.append(("reject-name", "未知 reject 方法 %s" % tok))
    for bodyval in re.findall(r"reject\s*\([^)]*?body\s*=\s*\"([^\"]*)\"", actions):
        if bodyval in MOCK_MAGIC_BODY:
            out.append(
                (
                    "reject-body",
                    'reject(..., body="%s") 是旧稿的魔法字符串，应改用 reject/reject_img/reject_dict/reject_array/reject_video'
                    % bodyval,
                )
            )

    # mock 阶段与组合限制
    if "body.mock" in actions:
        if phase == "request" and "response.body.mock" in actions:
            out.append(("mock-phase", "response.body.mock 写在 response 阶段（Loon 会在请求发出前提前生成响应）"))
        if phase == "response" and "request.body.mock" in actions:
            out.append(("mock-phase", "request.body.mock 写在 request 阶段"))
        if phase == "response" and "response.body.mock" in actions:
            if len(re.findall(r"response\.body\.mock(?:_file)?\s*\(", actions)) > 1:
                out.append(("mock-count", "一条 Rewrite 只能包含一个 response.body.mock(_file)"))
            cond = line[len(phase) + 4 : idx]
            if "${response.status}" in cond or "${response.header" in cond:
                out.append(("mock-cond", "含响应 Mock 的 Rewrite 不能在 if 中引用响应变量"))
            others = [
                a
                for a in re.findall(r"\b[\w.]+(?=\s*\()", actions)
                if not a.startswith("response.header.") and not a.startswith("response.body.mock")
            ]
            if others:
                out.append(
                    ("mock-combo", "含响应 Mock 时除 Mock 外只能搭配 response.header.*，发现 %s" % ",".join(sorted(set(others))))
                )
    return out


def issues_for_script_line(line):
    out = []
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return out

    if "script-path=" in stripped or "binary-body-mode=" in stripped:
        out.append(("script-old", "旧 Script 语法（script-path=/binary-body-mode=）仅用于维护 ≤982 配置"))
    if re.match(r"^http-(request|response)\s", stripped):
        out.append(("script-old", "旧 Script 触发关键字 http-request/http-response 仅用于维护 ≤982 配置"))
    if "argument=[{" in stripped or "enable={" in stripped:
        out.append(("script-arg", "argument=[{x}] / enable={x} 不是官方形式；新版用 script(\"x.js\", {${a}}) 与 with enable=${a}"))

    if "script(" in stripped:
        # `then` 后允许多个空白（官方：新版语法不会按空格拆分整行）。
        if not re.search(r"\bthen\s+script\(", stripped):
            out.append(("script-syntax", "新版 Script 语法应为 `<trigger> then script(...) [with ...]`"))
        # `with` 是可选的（官方原文：「没有字段时省略整个 `with`。」），省略不视为问题。
        wm = re.search(r"\bwith\s+(.*)$", stripped)
        if wm:
            for field in re.findall(r"(?:^|,)\s*([A-Za-z_]\w*)\s*=", wm.group(1)):
                if field not in WITH_ALLOWED:
                    out.append(("script-with", "with 未知字段 `%s`（字段名区分大小写且只允许小写 snake_case）" % field))
            if any(stripped.startswith(t) for t in NON_HTTP_TRIGGERS):
                if "requires_body" in wm.group(1) or "binary_body_mode" in wm.group(1):
                    out.append(("script-with", "cron/network-changed/generic 没有 Body，不能设置 requires_body/binary_body_mode"))
    return out


def fatal_issues(found):
    """过滤掉非致命提示，只留计入退出码的问题。"""
    return [x for x in found if x[1] not in ADVISORY_CODES]


def check_text(text, name):
    """返回 [(lineno, code, message), ...]；code 属于 ADVISORY_CODES 者为非致命提示。"""
    out = []
    lines = text.splitlines()
    # 逐行解析 `#!` 头，避免朴素子串匹配（desc/注释里出现 `#!date` 字样不算声明）。
    headers = set()
    for raw in lines:
        hm = re.match(r"^#!\s*([A-Za-z_]\w*)\s*=", raw.strip())
        if hm:
            headers.add("#!" + hm.group(1))
    if name.endswith(".plugin"):
        missing = [k for k in ADVISORY_METADATA if k not in headers]
        if missing:
            out.append(
                (
                    0,
                    "meta-optional",
                    "%s: 未声明 %s —— 官方元数据表未标注任何必填字段，缺失不是 Loon 语法错误；"
                    "此条仅为本仓**发布规范建议**（团队约定，非官方要求）"
                    % (name, "、".join(missing)),
                )
            )
    section = ""
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]"):
            section = s
            # MitM 段落名大小写：官方 [Mitm] / [MitM] 并存，任何大小写都不判非法。
            if s.lower() == "[mitm]" and s not in MITM_SECTIONS_DOCUMENTED:
                out.append(
                    (
                        i,
                        "mitm-case",
                        "官方文档 `[Mitm]`（/docs/Plugin/ 示例）与 `[MitM]`（/docs/MitM/）并存，未声明大小写敏感，"
                        "`%s` 不判为非法（真机兼容性本仓未验证，勿据此声称兼容）" % s,
                    )
                )
            continue
        if s.startswith("#!"):
            continue
        if section == "[Rewrite]":
            for code, msg in issues_for_rewrite_line(s):
                out.append((i, code, msg))
        elif section == "[Script]":
            for code, msg in issues_for_script_line(s):
                out.append((i, code, msg))
    return out


# ---------------------------------------------------------------- self-test

GOOD_REWRITE = [
    'request if ${url} ~= /^https:\\/\\/api\\.example\\.com/ then request.header.set("X-Loon", "true")',
    'request if ${url} ~= /\\/ads/ then reject_img(200)',
    'request if ${url} ~= /\\/blocked/ then reject(451, "Unavailable")',
    'request if ${url} ~= /\\/x/ then request.header.set("X", "1") | request.header.del("Cookie")',
    'response if ${url} ~= /\\/x/ then response.header.set("X", "1") | response.body.mock("json", `{"a":1}`, 200)',
    'response if ${url} ~= /^https:\\/\\/old\\.example\\.com(\\/.*)$/ as m then url.replace("https://new.example.com${m.1}")',
    'response if ${url} ~= /^http:\\/\\/example\\.com/ then redirect(302, "https://api.example.com")',
    'request if ${url} ~= /api/ then request.header.del("Cookie")',
    'response if ${url} ~= /api/ then response.json.jq_file("f.jq")',
    'request if ${url} ~= /api/ then request.body.replace(/price=(\\d+)/, "amount=$1")',
]
BAD_REWRITE = [
    ('http-request if ${url} ~= /x/ then reject(200)', "phase"),
    ('http-response if ${url} ~= /x/ then response.header.set("X","1")', "phase"),
    ('request if ${url} ~= /x/ then redirect(status=302, location="https://a.com")', "named-param"),
    ('request if ${url} ~= /x/ then request.header.delete("Cookie")', "header-del"),
    ('request if ${url} ~= /x/ then reject_img(200)', None),
    ('request if ${url} ~= /x/ then reject-img(200)', "reject-name"),
    ('request if ${url} ~= /x/ then reject(status=200, body="empty")', "named-param"),
    ('request if ${url} ~= /x/ then reject(200, body="empty")', "reject-body"),
    ('request if ${url} ~= /x/ then response.body.mock("json", `{}`, 200)', "mock-phase"),
    ('response if ${url} ~= /x/ then request.body.mock("json", `{}`)', "mock-phase"),
    (
        'response if ${url} ~= /x/ then response.body.mock("json", `{}`, 200) | response.body.mock("json", `{}`, 200)',
        "mock-count",
    ),
    (
        'response if ${response.status} == 200 && ${url} ~= /x/ then response.body.mock("json", `{}`, 200)',
        "mock-cond",
    ),
    (
        'response if ${url} ~= /x/ then response.body.mock("json", `{}`, 200) | request.header.del("A")',
        "mock-combo",
    ),
]
GOOD_SCRIPT = [
    'request if ${url} ~= /\\/api\\//i && ${request.method} == "POST" then script("r.js", {${mode}}) with tag="R", timeout=20, requires_body=true',
    'generic then script("tool.js", "manual") with tag="Tool", img_url="tool.system", timeout=30',
    'cron ${cron} then script("cron.js", {${region}}) with enable=${enabled}, tag="C", timeout=300',
    # 官方 /docs/Script/script_v2「Response URL Guard」原文示例：`with` 可省略。
    'response if ${url} ~= /\\/api\\// && ${response.status} == 200 then script("success.js")',
    # `then` 后允许多个空白。
    'request if ${url} ~= /\\/x/  then   script("r.js") with timeout=20',
    # 其他触发类型省略 `with` 同样合法。
    'cron "0 8 * * *" then script("cron.js", {${region}})',
]
BAD_SCRIPT = [
    ('http-request ^https:\\/\\/x script-path=r.js,argument="a=1"', "script-old"),
    ('request if ${url} ~= /x/ then script("r.js") with unknown_field=1', "script-with"),
    ('request if ${url} ~= /x/ then script("r.js", {${mode}}) with requires_body=true', None),
    ('cron "0 8 * * *" then script("c.js") with requires_body=true', "script-with"),
    ('generic then script("t.js", "x") with enable={enabled}', "script-arg"),
]
# check_text 级正例：元数据可省、MitM 段落名大小写不判非法（最多是非致命提示）。
GOOD_PLUGIN_TEXT = [
    (
        "minimal-no-date.plugin",
        "#!name = Minimal\n#!desc = no optional metadata\n\n[Rewrite]\n"
        "request if ${url} ~= /\\/x/ then reject_img(200)\n\n[MITM]\nhostname = a.example.com\n",
        ("meta-optional", "mitm-case"),  # 只允许非致命提示
    ),
    (
        "official-mitm-case.plugin",
        "#!name = OfficialCase\n#!loon_version = 3.5.1(978)\n#!date = 2026-10-13\n\n[Rewrite]\n"
        "request if ${url} ~= /\\/x/ then reject_img(200)\n\n[Mitm]\nhostname = a.example.com\n",
        (),  # 官方 Plugin 示例写法：无任何提示
    ),
    (
        "official-mitm-upper.plugin",
        "#!name = OfficialUpper\n#!loon_version = 3.5.1(978)\n#!date = 2026-10-13\n\n[Rewrite]\n"
        "request if ${url} ~= /\\/x/ then reject_img(200)\n\n[MitM]\nhostname = a.example.com\n",
        (),  # 官方 MitM 页写法：无任何提示
    ),
]


def self_test():
    fails = 0
    checks = [(l, None, "rewrite-good") for l in GOOD_REWRITE]
    checks += [(l, c, "rewrite-bad") for l, c in BAD_REWRITE]
    for line, expected, label in checks:
        got = [c for c, _ in issues_for_rewrite_line(line)]
        if expected is None:
            if got:
                print("FAIL [%s] 误报 %s: %s" % (label, got, line))
                fails += 1
        elif expected not in got:
            print("FAIL [%s] 期望 %s 实得 %s: %s" % (label, expected, got, line))
            fails += 1
    checks = [(l, None, "script-good") for l in GOOD_SCRIPT]
    checks += [(l, c, "script-bad") for l, c in BAD_SCRIPT]
    for line, expected, label in checks:
        got = [c for c, _ in issues_for_script_line(line)]
        if expected is None:
            if got:
                print("FAIL [%s] 误报 %s: %s" % (label, got, line))
                fails += 1
        elif expected not in got:
            print("FAIL [%s] 期望 %s 实得 %s: %s" % (label, expected, got, line))
            fails += 1

    # 回归：check_text 级——可选元数据缺失 / MitM 大小写不得计入错误（只允许指定提示）。
    plugin_cases = 0
    for name, text, allowed_advisory in GOOD_PLUGIN_TEXT:
        found = check_text(text, name)
        plugin_cases += 1
        fatal = fatal_issues(found)
        if fatal:
            print("FAIL [plugin-good] %s 误判为错误 %s" % (name, [c for _, c, _ in fatal]))
            fails += 1
        got_adv = tuple(sorted(c for _, c, _ in found if c in ADVISORY_CODES))
        if got_adv != tuple(sorted(allowed_advisory)):
            print("FAIL [plugin-good] %s 提示不符 期望 %s 实得 %s" % (name, allowed_advisory, got_adv))
            fails += 1

    total_cases = (
        len(GOOD_REWRITE) + len(BAD_REWRITE) + len(GOOD_SCRIPT) + len(BAD_SCRIPT) + plugin_cases
    )
    if fails:
        print("self-test: %d 例失败" % fails)
        return 1
    print("self-test: 全部 %d 例通过（正例不误报、反例被拦截、非致命提示不计错）" % total_cases)
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    targets = [a for a in argv[1:] if not a.startswith("-")]
    if not targets:
        if not os.path.isdir(TEMPLATES_DIR):
            print("找不到模板目录: %s" % TEMPLATES_DIR)
            return 2
        targets = sorted(
            os.path.join(TEMPLATES_DIR, f)
            for f in os.listdir(TEMPLATES_DIR)
            if f.endswith(".plugin")
        )
    total = 0
    for path in targets:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        found = check_text(text, os.path.basename(path))
        fatal = fatal_issues(found)
        for lineno, code, msg in found:
            if code in ADVISORY_CODES:
                print("%s:%s: [advisory:%s] %s" % (path, lineno or "-", code, msg))
            else:
                print("%s:%s: [%s] %s" % (path, lineno or "-", code, msg))
        total += len(fatal)
        if fatal:
            continue
        if found:
            print(
                "%s: OK（无错误；另有 %d 条非致命提示，静态检查通过，仍需真机确认）"
                % (path, len(found))
            )
        else:
            print("%s: OK（静态检查通过，仍需真机确认）" % path)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
