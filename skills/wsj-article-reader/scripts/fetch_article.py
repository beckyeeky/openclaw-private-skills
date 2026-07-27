#!/usr/bin/env python3
"""Fetch one user-authorized WSJ ArticleContent request conservatively.

Secrets: reads WSJ_DJ_AUTHORIZATION only from the process environment. It never
writes or prints the value. The GraphQL template is non-secret JSON stored in a
user runtime directory, never under the installed skill or Git repository.
"""
import argparse, datetime as dt, json, os, random, sys, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(os.environ.get('WSJ_READER_HOME', '~/.openclaw/wsj-article-reader')).expanduser()
TEMPLATE = ROOT / 'template.json'
STATE = ROOT / 'state.json'
ARTICLES = ROOT / 'articles'
HOUR_LIMIT, DAY_LIMIT, MIN_GAP = 6, 20, 15 * 60


def die(message, code=1):
    print(message, file=sys.stderr)
    raise SystemExit(code)


def now(): return dt.datetime.now(dt.timezone.utc)
def iso(t=None): return (t or now()).replace(microsecond=0).isoformat()
def load_json(path, default):
    try: return json.loads(path.read_text('utf-8'))
    except FileNotFoundError: return default
    except Exception: die(f'Invalid local runtime file: {path.name}')
def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
def parse_time(v):
    return dt.datetime.fromisoformat(v.replace('Z', '+00:00'))


def validate_template(t):
    required = {'endpoint', 'operation_name', 'query', 'headers'}
    if not isinstance(t, dict) or not required <= t.keys():
        die('Template is incomplete; refresh your own non-secret ArticleContent template.')
    if t['endpoint'] != 'https://shared-data.dowjones.io/gateway/graphql':
        die('Template endpoint is not the permitted WSJ GraphQL endpoint.')
    if t['operation_name'] != 'ArticleContent':
        die('Template is not an ArticleContent template.')
    if not isinstance(t['query'], dict) or not isinstance(t['headers'], dict):
        die('Template query/headers must be objects.')
    forbidden = ('authorization', 'cookie', 'token', 'secret', 'password')
    found = [k for k in t['headers'] if any(x in k.lower() for x in forbidden)]
    if found: die('Template contains a credential-like header; remove it before use.')


def allowed(state, override_wait):
    attempts = state.get('attempts', [])
    cutoff_h, cutoff_d = now()-dt.timedelta(hours=1), now()-dt.timedelta(days=1)
    recent_h = [x for x in attempts if parse_time(x['at']) >= cutoff_h]
    recent_d = [x for x in attempts if parse_time(x['at']) >= cutoff_d]
    if len(recent_h) >= HOUR_LIMIT: die('Local hourly limit reached (6 requests/hour).')
    if len(recent_d) >= DAY_LIMIT: die('Local daily limit reached (20 requests/day).')
    if attempts and not override_wait:
        elapsed = (now() - parse_time(attempts[-1]['at'])).total_seconds()
        if elapsed < MIN_GAP:
            die(f'Local cooldown active; wait {int(MIN_GAP-elapsed)} seconds or use --allow-once.')


def record(state, article_id, status):
    # No title, URL, headers, token, query values, or response text.
    state.setdefault('attempts', []).append({'at': iso(), 'id': article_id[-12:], 'status': status})
    state['attempts'] = state['attempts'][-100:]
    save_json(STATE, state)


def text(node):
    if not isinstance(node, dict): return ''
    if isinstance(node.get('flattened'), dict): return node['flattened'].get('text', '')
    if isinstance(node.get('textAndDecorations'), dict): return text(node['textAndDecorations'])
    return node.get('text', '')


def markdown(article):
    title = text(article.get('articleHeadline', {})) or 'WSJ article'
    standfirst = text(article.get('standFirst', {}))
    body = [text(x) for x in article.get('articleBody', [])]
    body = [x for x in body if x]
    lines = [f'# {title}', '', '- Source: Wall Street Journal',
             f'- URL: {article.get("sourceUrl", "")}',
             f'- Section: {article.get("sectionName", "")}',
             f'- Published: {article.get("publishedDateTimeUtc", "")}',
             f'- Retrieved: {iso()}', '']
    if standfirst: lines += [f'> {standfirst}', '']
    return '\n'.join(lines + ['---', ''] + body) + '\n', title


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--origin-id', required=True, help='WSJ origin ID obtained from the supplied article URL')
    ap.add_argument('--allow-once', action='store_true', help='Explicitly bypass only the 15-minute local cooldown once')
    args = ap.parse_args()
    if not os.environ.get('WSJ_DJ_AUTHORIZATION'): die('WSJ_DJ_AUTHORIZATION is not set.')
    template = load_json(TEMPLATE, None)
    if template is None: die(f'Missing non-secret template: {TEMPLATE}')
    validate_template(template)
    state = load_json(STATE, {'attempts': []}); allowed(state, args.allow_once)
    # Intentional small non-deterministic pacing; no retry/polling/burst.
    time.sleep(random.uniform(2, 6))
    query = {}
    for key, value in template['query'].items():
        # Persisted-query fields were JSON strings in the original URL.
        query[key] = json.dumps(value, separators=(',', ':')) if isinstance(value, (dict, list)) else str(value)
    variables = json.loads(query.get('variables', '{}'))
    variables.update({'id': args.origin_id, 'idType': 'originid', 'filterByScope': 'MOBILE'})
    query['variables'] = json.dumps(variables, separators=(',', ':'))
    query['operationName'] = template['operation_name']
    url = template['endpoint'] + '?' + urlencode(query)
    headers = dict(template['headers'])
    headers['Authorization'] = os.environ['WSJ_DJ_AUTHORIZATION']
    # Requested policy: English locale. Keep client version/UA coherent with the template.
    headers['Accept-Language'] = 'en-US,en;q=0.9'
    try:
        with urlopen(Request(url, headers=headers, method='GET'), timeout=30) as r:
            status, raw = r.status, r.read()
    except HTTPError as e:
        record(state, args.origin_id, e.code); die(f'WSJ returned HTTP {e.code}; stopped without retry.')
    except URLError as e:
        record(state, args.origin_id, 0); die('Network failure; stopped without retry.')
    record(state, args.origin_id, status)
    if status != 200: die(f'Unexpected HTTP {status}; stopped.')
    try: article = json.loads(raw)['data']['articleContent']
    except Exception: die('Unexpected response schema; no export written.')
    if not article: die('No entitled article content returned; stopped.')
    md, title = markdown(article)
    ARTICLES.mkdir(parents=True, exist_ok=True)
    safe = ''.join(c if c.isalnum() else '-' for c in args.origin_id).strip('-')[-64:]
    out = ARTICLES / f'{safe}.md'; out.write_text(md, 'utf-8')
    print(f'Fetched one authorized article: {title}')
    print(f'Saved: {out}')

if __name__ == '__main__': main()
