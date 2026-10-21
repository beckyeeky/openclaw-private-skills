#!/usr/bin/env python3
"""Tavily Search：从环境变量读取单个或多个 API key，并轮询及故障转移。"""

import argparse
import fcntl
import json
import os
from pathlib import Path

from tavily import TavilyClient

STATE_FILE = Path(os.environ.get("TAVILY_LB_STATE_FILE", "/tmp/tavily-search-key-index"))


def load_keys():
    """读取 key；兼容单 key、列表和编号环境变量，并去重。"""
    values = []
    if os.environ.get("TAVILY_API_KEYS"):
        values.extend(os.environ["TAVILY_API_KEYS"].replace("\n", ",").split(","))
    if os.environ.get("TAVILY_API_KEY"):
        values.append(os.environ["TAVILY_API_KEY"])
    for name in sorted(k for k in os.environ if k.startswith("TAVILY_API_KEY_")):
        values.append(os.environ[name])
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


def next_start(count):
    """以带文件锁的持久计数器分配本次调用的起始 key。"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            current = int(f.read().strip() or "0")
        except ValueError:
            current = 0
        f.seek(0)
        f.truncate()
        f.write(str((current + 1) % count))
        f.flush()
        return current % count


def search_with_failover(keys, query, max_results):
    start = next_start(len(keys))
    errors = []
    for offset in range(len(keys)):
        slot = (start + offset) % len(keys)
        try:
            return TavilyClient(api_key=keys[slot]).search(
                query=query, max_results=max_results
            )
        except Exception as exc:
            errors.append(f"key #{slot + 1}: {type(exc).__name__}: {exc}")
    raise SystemExit("All Tavily API keys failed:\n" + "\n".join(errors))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query", help="Search query")
    p.add_argument("--max", type=int, default=5, help="max results")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument(
        "--include-answer",
        action="store_true",
        help="在文本输出中显示 API 返回的 answer 字段（若存在）",
    )
    args = p.parse_args()

    keys = load_keys()
    if not keys:
        raise SystemExit(
            "No Tavily API key configured. Set TAVILY_API_KEYS, "
            "TAVILY_API_KEY, or TAVILY_API_KEY_1... in environments."
        )

    data = search_with_failover(keys, args.query, args.max)

    if args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if args.include_answer and data.get("answer"):
        print(f"answer: {data.get('answer')}\n")

    for item in data.get("results", []):
        print(f"- {item.get('title')}")
        print(f"  URL: {item.get('url')}")
        snippet = (item.get('content') or "").replace("\n", " ")
        print(f"  摘要: {snippet[:180]}")


if __name__ == "__main__":
    main()
