#!/usr/bin/env python3
"""Direct X photo export; stdout is a single JSON result.

Two photo channels:

* ``metadata`` - X's syndication ``tweet-result`` endpoint. No browser, no cookies, no
  login, and the photo count comes from the platform instead of DOM inference.
* ``browser``  - ``minis-browser-use`` DOM extraction. Still the only channel that sees
  posts behind a login, age gate or sensitive-content confirmation.

``--via auto`` (default) tries ``metadata`` first and drops to ``browser`` only for the
four documented unavailability cases. Both channels share the same download and merge
code, so the PNG geometry, white background and pixel limit never depend on the route.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

from PIL import Image

SYNDICATION_URL = 'https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=a'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
METADATA_TIMEOUT = 40
METADATA_ATTEMPTS = 2  # one request plus exactly one retry, for 429/5xx/timeout only
BROWSER_BINARY = 'minis-browser-use'
CURL_DOWNLOAD = ('curl', '--fail', '--silent', '--show-error', '--location',
                 '--retry', '2', '--max-time', '60')


class ExportError(RuntimeError):
    """Expected failure: rendered as error JSON with exit code 1."""

    def __init__(self, message, **context):
        super().__init__(message)
        self.context = context


class MetadataUnavailable(ExportError):
    """One of the four documented reasons to leave the metadata channel."""


class SchemaDrift(ExportError):
    """The endpoint answered with a tweet but its media fields no longer parse."""


class _TransportError(Exception):
    """curl could not complete the request (timeout, DNS, connection, TLS)."""


def browser(action, **kwargs):
    try:
        raw = subprocess.check_output(['minis-browser-use', '--json', json.dumps(dict(action=action, **kwargs)), '--compact'], text=True)
    except FileNotFoundError:
        raise ExportError('%s is not installed; use --via metadata on this host' % BROWSER_BINARY)
    envelope = json.loads(raw)
    data = envelope.get('data', {})
    if not envelope.get('ok', True) or not data.get('success', False):
        raise RuntimeError('browser action failed: ' + action)
    return data


def decode_result(data):
    # CLI appends human-readable tab_id after execute_js's JSON value.
    return json.JSONDecoder().raw_decode(data['text'].lstrip())[0]


def merge(paths, output):
    images = []
    try:
        for path in paths:
            with Image.open(path) as source:
                source.load()
                rgba = source.convert('RGBA')
                rgb = Image.new('RGB', rgba.size, 'white')
                rgb.paste(rgba, mask=rgba.getchannel('A'))
                images.append(rgb)
        if not images:
            raise ValueError('no photos to merge')
        width, height = sum(i.width for i in images), max(i.height for i in images)
        if width * height > 150_000_000:
            raise ValueError('output exceeds 150 million pixel memory safety limit; no resizing performed')
        canvas = Image.new('RGB', (width, height), 'white')
        x = 0
        for image in images:
            canvas.paste(image, (x, 0)); x += image.width
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.png', delete=False) as f:
            temporary = Path(f.name)
        try:
            canvas.save(temporary, format='PNG')
            with Image.open(temporary) as check:
                check.verify()
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        return {'width':width, 'height':height, 'source_sizes':[list(i.size) for i in images], 'bytes':output.stat().st_size}
    finally:
        for image in images:
            image.close()


def browser_available():
    return shutil.which(BROWSER_BINARY) is not None


def _http_get(url):
    """GET *url* with curl; return (status, body_text). No new dependencies."""
    with tempfile.TemporaryDirectory(prefix='xmeta-') as directory:
        body = Path(directory) / 'body'
        completed = subprocess.run(
            ['curl', '--silent', '--show-error', '--location', '--compressed',
             '--user-agent', USER_AGENT, '--header', 'Accept: application/json',
             '--max-time', str(METADATA_TIMEOUT),
             '--output', str(body), '--write-out', '%{http_code}', url],
            capture_output=True, text=True)
        if completed.returncode != 0:
            detail = (completed.stderr or '').strip() or 'curl exit %d' % completed.returncode
            raise _TransportError(detail)
        status = (completed.stdout or '').strip()
        if not status.isdigit() or status == '0':
            raise _TransportError('curl reported no HTTP status')
        text = body.read_text(encoding='utf-8', errors='replace') if body.exists() else ''
        return int(status), text


def _parse_payload(text):
    try:
        payload = json.loads(text)  # explicit utf-8 decoding happened in _http_get
    except json.JSONDecodeError:
        raise MetadataUnavailable('response body is not JSON')
    if not isinstance(payload, dict):
        raise MetadataUnavailable('response body is not a JSON object')
    if 'tombstone' in payload or 'Tombstone' in str(payload.get('__typename', '')):
        raise MetadataUnavailable('tweet tombstone (deleted, protected or restricted post)')
    return payload


def fetch_tweet_json(tweet_id):
    """Return the parsed syndication payload for *tweet_id*.

    Retries at most once and only for 429/5xx/timeout; 404, tombstone, missing media and
    non-JSON bodies raise MetadataUnavailable immediately. A recognisable tweet whose
    media fields stopped parsing raises SchemaDrift instead of pretending "0 photos".
    """
    url = SYNDICATION_URL.format(tweet_id=tweet_id)
    attempt = 0
    while True:
        attempt += 1
        try:
            status, text = _http_get(url)
        except _TransportError as exc:
            if attempt < METADATA_ATTEMPTS:
                time.sleep(1)
                continue
            raise MetadataUnavailable('metadata request failed %d times (%s)' % (attempt, exc))
        if status == 200:
            return _parse_payload(text)
        if status == 404:
            raise MetadataUnavailable('HTTP 404 (deleted, protected or members-only post)')
        if status == 429 or 500 <= status < 600:
            if attempt < METADATA_ATTEMPTS:
                time.sleep(1)
                continue
            raise MetadataUnavailable('HTTP %d after %d metadata attempts' % (status, attempt))
        raise ExportError('unexpected HTTP %d from the syndication endpoint' % status)


def metadata_media(payload):
    """Return (photo_urls, video_present) using top-level media only.

    ``quoted_tweet``/``reply`` sub-objects are deliberately never traversed.
    """
    photos = payload.get('photos')
    details = payload.get('mediaDetails')
    video = bool(payload.get('video'))
    if isinstance(photos, list) and photos:
        urls = []
        for entry in photos:
            if not isinstance(entry, dict) or not entry.get('url'):
                raise SchemaDrift('syndication photos[] entry has no url; endpoint shape changed')
            urls.append(entry['url'])
        return urls, video
    if isinstance(details, list) and details:
        urls = []
        for detail in details:
            if not isinstance(detail, dict):
                raise SchemaDrift('syndication mediaDetails[] entry is not an object; endpoint shape changed')
            kind = detail.get('type')
            if kind in ('video', 'animated_gif'):
                video = True
                continue
            if kind != 'photo':
                continue
            if (detail.get('ext_media_availability') or {}).get('status') != 'Available':
                continue
            media_url = detail.get('media_url_https')
            if not media_url:
                raise SchemaDrift('syndication mediaDetails[] photo has no media_url_https; endpoint shape changed')
            urls.append(media_url)
        return urls, video
    raise MetadataUnavailable('photos and mediaDetails both missing from the payload')


def _dedupe_key(url):
    """Identity of a photo: its media path. Never expanded_url, which the endpoint
    rewrites to ``.../photo/1`` for every image in the post."""
    parts = urllib.parse.urlsplit(url)
    return (parts.netloc, parts.path)


def original_url(url):
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k != 'name']
    query.append(('name', 'orig'))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def metadata_photos(tweet_id):
    """Return (photos, total_declared, video) through the metadata channel."""
    payload = fetch_tweet_json(tweet_id)
    urls, video = metadata_media(payload)
    photos, seen = [], set()
    for url in urls:
        key = _dedupe_key(url)
        if key in seen:
            continue
        seen.add(key)
        photos.append({'index': len(photos) + 1, 'url': original_url(url)})
    return photos, len(photos), video


def browser_photos(args, tweet_id):
    """Return (photos, video, contiguous, completeness_note) through the DOM channel."""
    tab = args.tab_id
    if tab is None:
        info = browser('new_tab', url='https://x.com/i/status/' + tweet_id)
        m = re.search(r'tab_id\s*:\s*(\d+)', info.get('text', ''))
        if not m:
            raise ExportError('cannot identify newly created tab; pass --tab-id from list_tabs')
        tab = int(m.group(1))
    else:
        browser('navigate', url=args.url, tab_id=tab)
    js = Path(__file__).with_name('extract.js').read_text(encoding='utf-8')
    result = None
    for attempt in range(3):
        result = decode_result(browser('execute_js', script=js + '\nreturn extractTweetPhotos(document, ' + json.dumps(tweet_id) + ');', tab_id=tab))
        photos = result.get('photos') or []
        if result.get('found') and photos and result.get('contiguous') and (args.expected_count is None or len(photos) == args.expected_count):
            break
        if attempt < 2:
            browser('wait_for_dom_stable', timeout=10, tab_id=tab)
    if not result or not result.get('found'):
        raise ExportError('target post not rendered; login/access restriction or changed markup')
    return (result.get('photos') or [], bool(result.get('video')),
            bool(result.get('contiguous')), result.get('completeness'))


def _metadata_result(tweet_id):
    photos, total, video = metadata_photos(tweet_id)
    return {'photos': photos, 'video': video, 'source': 'metadata', 'fallback_reason': None,
            'completeness': {'total_from_metadata': total, 'contiguous': True,
                             'declared_by': 'syndication photos/mediaDetails'}}


def _browser_result(args, tweet_id):
    photos, video, contiguous, note = browser_photos(args, tweet_id)
    if not contiguous:
        raise ExportError('incomplete visible photo sequence; inspect target carousel and retry, do not claim full export')
    return {'photos': photos, 'video': video, 'source': 'browser', 'fallback_reason': None,
            'completeness': {'total_from_metadata': None, 'contiguous': contiguous,
                             'note': note or 'DOM-visible only; trailing virtualized photos cannot be ruled out'}}


def _verify_both_result(args, tweet_id):
    """Run both channels, keep metadata authoritative, and report any disagreement."""
    if not browser_available():
        raise ExportError('--verify-both needs %s to cross-check the DOM' % BROWSER_BINARY)
    metadata = _metadata_result(tweet_id)
    dom = _browser_result(args, tweet_id)
    metadata['completeness']['browser_photo_count'] = len(dom['photos'])
    metadata['completeness']['mismatch'] = len(metadata['photos']) != len(dom['photos'])
    if metadata['completeness']['mismatch']:
        metadata['completeness']['note'] = 'metadata and DOM photo counts disagree; metadata is authoritative'
    return metadata


def collect_photos(args, tweet_id):
    """Return dict(photos, video, source, fallback_reason, completeness)."""
    if args.via == 'browser':
        return _browser_result(args, tweet_id)
    if args.via == 'metadata':
        return _metadata_result(tweet_id)
    if args.verify_both:
        return _verify_both_result(args, tweet_id)
    try:
        return _metadata_result(tweet_id)
    except MetadataUnavailable as exc:
        if not browser_available():
            raise ExportError('metadata channel unavailable (%s) and %s is not installed; nothing else to try'
                              % (exc, BROWSER_BINARY))
        result = _browser_result(args, tweet_id)
        result['fallback_reason'] = str(exc)
        return result


def resolve_output(args, tweet_id):
    name = 'x-%s-merged.png' % tweet_id
    if args.output:
        return Path(args.output).expanduser().resolve()
    configured = os.environ.get('MINIS_ATTACHMENTS_DIR')
    if configured:
        return (Path(configured).expanduser() / name).resolve()
    return (Path.cwd() / name).resolve()


def minis_url(target):
    """Return a minis:// URL only when *target* really lives under a minis mount."""
    roots = ['/var/minis']
    configured = os.environ.get('MINIS_ATTACHMENTS_DIR')
    if configured:
        roots.append(configured)
    for root in roots:
        try:
            relative = Path(target).relative_to(Path(root).expanduser().resolve())
        except (ValueError, OSError):
            continue
        return 'minis://' + urllib.parse.quote(str(relative), safe='/')
    return None


def download(url, path):
    try:
        subprocess.run([*CURL_DOWNLOAD, url, '--output', str(path)], check=True)
    except subprocess.CalledProcessError as exc:
        raise ExportError('photo download failed (curl exit %d)' % exc.returncode) from exc


def run(args):
    parsed = urllib.parse.urlparse(args.url)
    match = re.search(r'/status/(\d+)(?:/|$)', parsed.path)
    if parsed.hostname not in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com') or not match:
        return {'status': 'error', 'error': 'expected an X/Twitter /status/ID URL'}
    tweet_id = match.group(1)
    context = {'tweet_id': tweet_id}
    try:
        collected = collect_photos(args, tweet_id)
        context = {'tweet_id': tweet_id, 'source': collected['source'],
                   'fallback_reason': collected['fallback_reason']}
        photos = collected['photos']
        if not photos:
            raise ExportError('no photos visible; video present' if collected['video'] else 'no photos visible')
        if args.expected_count is not None and len(photos) != args.expected_count:
            raise ExportError('expected %d photos but found %d; refusing to report success'
                              % (args.expected_count, len(photos)))
        output = resolve_output(args, tweet_id)
        with tempfile.TemporaryDirectory(prefix='xmerge-') as directory:
            paths = []
            for photo in photos:
                path = Path(directory) / str(photo['index'])
                download(photo['url'], path)
                paths.append(path)
            validation = merge(paths, output)
        completeness = dict(collected['completeness'])
        completeness['expected_count'] = args.expected_count
        completeness['photo_count'] = len(paths)
        result = {'status': 'ok', 'tweet_id': tweet_id, 'source': collected['source'],
                  'fallback_reason': collected['fallback_reason'],
                  'photo_count': len(paths), 'output': str(output),
                  'completeness': completeness, 'expected_count': args.expected_count, **validation}
        link = minis_url(output)
        if link:
            result['minis_url'] = link
        return result
    except ExportError as exc:
        payload = {'status': 'error', 'error': str(exc)}
        payload.update(context)
        payload.update(exc.context)
        return payload


def build_parser():
    parser = argparse.ArgumentParser(description='Merge the photos of one X/Twitter post into a single horizontal PNG.')
    parser.add_argument('url')
    parser.add_argument('--output', help='target PNG path (default: --output > MINIS_ATTACHMENTS_DIR > ./x-<id>-merged.png)')
    parser.add_argument('--tab-id', type=int)
    parser.add_argument('--expected-count', type=int, choices=range(1, 5))
    parser.add_argument('--via', choices=('auto', 'metadata', 'browser'), default='auto',
                        help='photo channel: metadata first (default auto), browser only, or both for cross-checking')
    parser.add_argument('--verify-both', action='store_true',
                        help='run metadata and browser, report disagreements, keep metadata authoritative')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:  # noqa: BLE001 - the CLI contract is one JSON object
        result = {'status': 'error', 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('status') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
