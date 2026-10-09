#!/usr/bin/env python3
"""Read-only redaction review; stdout is a JSON list without source excerpts.

Coordinates are 1-based in NFKC+casefold normalized text (not original bytes).
Types alias_unresolved_leak indicate unresolved aliases; all other findings
are candidates, NOT deletion instructions. Even exit 0 requires semantic review.
Exit codes: 0 no automatic hits, 1 review needed, 2 argument/input error.
"""
import argparse
import bisect
import json
from pathlib import Path
import re
import sys
import unicodedata


def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold()


# Detect capitalization before casefold; its positions are converted below.
CAPITAL = re.compile(r"(?<![A-Za-z])[A-Z][A-Za-z]+\b")
RULES = (
    ("email_candidate", r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+"),
    ("at_candidate", r"@"),
    ("phone_candidate", r"(?<!\w)(?:\+?\d[\d ()\-]{5,}\d)(?!\w)"),
    ("number_candidate", r"\d+"),
    ("cas_candidate", r"(?<!\d)\d{2,7}-\d{2}-\d(?!\d)"),
    ("identifier_keyword_candidate", r"\b(?:cas|po|lot|batch|contract|approval|wechat|weixin)\b|合同|批号|批准文号|注册证号|信用代码|微信"),
    ("url_candidate", r"(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>\"']+"),
    ("cjk_title_candidate", r"[\u3400-\u9fff]{1,8}(?:先生|女士|小姐|老师|博士|教授|经理|总监|主任|总|工)"),
    ("korean_title_candidate", r"[가-힣]{1,8}\s*(?:님|씨|대표|과장|부장|이사)"),
    ("company_suffix_candidate", r"(?:股份有限公司|有限责任公司|有限公司|公司|集团|株式会社|有限会社|주식회사|유한회사)"),
)
# Only exact neutral labels are exempted from the company-suffix heuristic.
# Alias matching always takes precedence and never uses these exemptions.
NEUTRAL = re.compile(r"(?<![\u3400-\u9fff])(?:甲公司|乙公司|该公司)(?![\u3400-\u9fff])")


def verify(text, aliases=()):
    if not isinstance(text, str) or not isinstance(aliases, (list, tuple)):
        raise ValueError("invalid input")
    if any(not isinstance(a, str) or not a.strip() for a in aliases):
        raise ValueError("invalid aliases")
    normalized = normalize(text)
    starts = [0] + [m.end() for m in re.finditer("\n", normalized)]
    findings = set()

    def add(kind, offset):
        row = bisect.bisect_right(starts, offset)
        findings.add((row, offset - starts[row - 1] + 1, kind))

    for alias in {normalize(a) for a in aliases}:
        start = 0
        while True:
            pos = normalized.find(alias, start)
            if pos < 0:
                break
            add("alias_unresolved_leak", pos)
            start = pos + 1
    neutral = [(m.start(), m.end()) for m in NEUTRAL.finditer(normalized)]
    for kind, pattern in RULES:
        for match in re.finditer(pattern, normalized):
            if kind == "company_suffix_candidate" and any(
                a <= match.start() and match.end() <= b for a, b in neutral
            ):
                continue
            if kind == "phone_candidate" and sum(c.isdecimal() for c in match[0]) < 7:
                continue
            add(kind, match.start())
    nfkc = unicodedata.normalize("NFKC", text)
    for match in CAPITAL.finditer(nfkc):
        add("capitalized_word_candidate", len(nfkc[:match.start()].casefold()))
    return [{"type": kind, "line": row, "column": col}
            for row, col, kind in sorted(findings)]


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid arguments")


def main(argv=None):
    parser = QuietParser(description=__doc__)
    parser.add_argument("output", metavar="OUTPUT")
    parser.add_argument("--aliases", metavar="PRIVATE_JSON")
    try:
        args = parser.parse_args(argv)
        text = Path(args.output).read_text(encoding="utf-8")
        aliases = []
        if args.aliases:
            aliases = json.loads(Path(args.aliases).read_text(encoding="utf-8"))
            if not isinstance(aliases, list):
                raise ValueError("invalid aliases")
        findings = verify(text, aliases)
    except (OSError, UnicodeError, ValueError, RecursionError):
        print(json.dumps([{"type": "input_error", "line": 0, "column": 0}]))
        return 2
    print(json.dumps(findings, ensure_ascii=True))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
