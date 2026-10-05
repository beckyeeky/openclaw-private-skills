#!/usr/bin/env python3
"""Direct X photo export; stdout is a single JSON result."""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse, quote
from PIL import Image


def browser(action, **kwargs):
    raw = subprocess.check_output(['minis-browser-use', '--json', json.dumps(dict(action=action, **kwargs)), '--compact'], text=True)
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


def run(args):
    parsed = urlparse(args.url)
    match = re.search(r'/status/(\d+)(?:/|$)', parsed.path)
    if parsed.hostname not in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com') or not match:
        raise ValueError('expected an X/Twitter /status/ID URL')
    tweet_id = match[1]
    tab = args.tab_id
    if tab is None:
        info = browser('new_tab', url='https://x.com/i/status/' + tweet_id)
        m = re.search(r'tab_id\s*:\s*(\d+)', info.get('text',''))
        if not m:
            raise RuntimeError('cannot identify newly created tab; pass --tab-id from list_tabs')
        tab = int(m[1])
    else:
        browser('navigate', url=args.url, tab_id=tab)
    js = Path(__file__).with_name('extract.js').read_text()
    result = None
    for attempt in range(3):
        result = decode_result(browser('execute_js', script=js+'\nreturn extractTweetPhotos(document, '+json.dumps(tweet_id)+');', tab_id=tab))
        photos = result['photos']
        if result['found'] and photos and result['contiguous'] and (args.expected_count is None or len(photos) == args.expected_count):
            break
        if attempt < 2:
            browser('wait_for_dom_stable', timeout=10, tab_id=tab)
    if not result['found']:
        raise RuntimeError('target post not rendered; login/access restriction or changed markup')
    if not result['photos']:
        raise RuntimeError('no photos visible' + ('; video present (video-only or quoted video; no frames exported)' if result['video'] else ''))
    if not result['contiguous'] or (args.expected_count is not None and len(result['photos']) != args.expected_count):
        raise RuntimeError('incomplete visible photo sequence; inspect target carousel and retry, do not claim full export')
    output = Path(args.output or '/var/minis/attachments/x-'+tweet_id+'-merged.png').resolve()
    with tempfile.TemporaryDirectory(prefix='xmerge-') as directory:
        paths = []
        for photo in result['photos']:
            path = Path(directory) / str(photo['index'])
            subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location', '--retry', '2', '--max-time', '60', photo['url'], '-o', str(path)], check=True)
            paths.append(path)
        validation = merge(paths, output)
    return dict(status='ok', tweet_id=tweet_id, photo_count=len(paths), output=str(output), minis_url='minis://'+quote(str(output).removeprefix('/var/minis/'), safe='/'), completeness=result['completeness'], expected_count=args.expected_count, **validation)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('--output')
    parser.add_argument('--tab-id', type=int)
    parser.add_argument('--expected-count', type=int, choices=range(1,5))
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status':'error', 'error':str(exc)}, ensure_ascii=False))
        sys.exit(1)
