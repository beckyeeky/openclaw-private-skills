#!/usr/bin/env python3
"""Additional Tavily modes; reuse upstream key selection without renaming env vars."""
import argparse
import json
from search import load_keys, next_start, TavilyClient


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['search', 'extract', 'research', 'status'])
    p.add_argument('input')
    p.add_argument('--max', type=int, choices=range(1, 21), default=10)
    args = p.parse_args()
    keys = load_keys()
    if not keys:
        print(json.dumps({'error': {'type': 'missing_key'}}))
        return 3
    # Status requests must try the same account that owns the request ID.
    start = 0 if args.mode == 'status' else next_start(len(keys))
    for offset in range(len(keys)):
        client = TavilyClient(api_key=keys[(start + offset) % len(keys)])
        try:
            if args.mode == 'search':
                data = client.search(query=args.input, max_results=args.max,
                                     search_depth='advanced', include_answer=True, timeout=45)
            elif args.mode == 'extract':
                data = client.extract(urls=[args.input], extract_depth='advanced', format='markdown', timeout=45)
            elif args.mode == 'research':
                data = client.research(input=args.input, model='mini', citation_format='numbered', timeout=45)
            else:
                data = client.get_research(request_id=args.input)
            print(json.dumps(data, ensure_ascii=False))
            return 0
        except Exception as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            # Never print exception text: upstream errors may contain credentials.
            if args.mode == 'research' and status not in (401, 402, 429):
                print(json.dumps({'error': {'type': 'research_submission_uncertain', 'status': status}}))
                return 5
    print(json.dumps({'error': {'type': 'all_keys_failed'}}))
    return 5


if __name__ == '__main__':
    raise SystemExit(main())
