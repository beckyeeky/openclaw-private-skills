#!/usr/bin/env python3
"""Resolve the current WSJ article's origin id from browser-rendered public metadata only.

The single attribution source is the dedicated ``articleData`` object of the
page's embedded payload::

    __NEXT_DATA__ -> .props.pageProps.articleData
        .originId                          (id of this article)
        .articleTrackingMeta.articleId      (must equal .originId when both exist)
        .sourceUrl / .canonicalUrl          (canonical path of this article)

``probe_metadata.js`` reads exactly that path: only the ``#__NEXT_DATA__``
element, no recursion through the page tree, no whole-page regex, and no scan of
any other script tag. Its result is validated here before an id is printed:

* the dedicated ``articleData`` object must exist; an id is never inferred from
  another part of the page (related/recommended stories carry their own ids);
* ``sourceUrl`` / ``canonicalUrl`` must resolve to the requested article path;
* ``originId`` and ``articleTrackingMeta.articleId`` must agree when both exist.

Does not retrieve article bodies and never uses credentials: the browser step is
public and unauthenticated.
"""
import argparse,json,pathlib,re,subprocess,sys,urllib.parse
ID=re.compile(r'^(?:WP-WSJ-\d+|SB\d{10,})$')
PROBE=pathlib.Path(__file__).resolve().parent/'probe_metadata.js'

def validate(url):
 p=urllib.parse.urlsplit(url)
 if p.scheme!='https' or not (p.hostname=='wsj.com' or (p.hostname or '').endswith('.wsj.com')) or p.username or p.password:
  raise ValueError('Expected an HTTPS WSJ URL')
 return p

def article_path(url):
 return validate(url).path.rstrip('/') or '/'

def probe_script():
 try:return PROBE.read_text('utf-8')
 except OSError:raise RuntimeError('Browser metadata probe is missing from this skill: '+PROBE.name)

def select(data,url):
 """Force the attribution rules onto the probe result; never guess an id."""
 expected=article_path(url)
 if not isinstance(data,dict):raise ValueError('No readable article metadata; stop and report browser access state')
 if not data.get('ok'):
  raise ValueError('Page exposed no usable dedicated articleData metadata (%s); refusing to attribute an id'%str(data.get('code') or 'unknown'))
 if not data.get('hasArticleData'):
  raise ValueError('props.pageProps.articleData is absent; refusing to infer an id from any other page data')
 confirmed=[]
 for field in ('sourceUrl','canonicalUrl'):
  value=data.get(field)
  if not value:continue
  try:path=article_path(value)
  except ValueError:raise ValueError('articleData.%s is not an HTTPS WSJ URL; refusing to attribute an id'%field)
  if path!=expected:raise ValueError('articleData.%s does not match the requested article path; refusing to attribute an id'%field)
  confirmed.append(field)
 if not confirmed:raise ValueError('articleData exposed neither sourceUrl nor canonicalUrl; cannot confirm attribution')
 origin=data.get('originId');tracking=data.get('trackingArticleId')
 if origin and not ID.fullmatch(str(origin)):raise ValueError('articleData.originId is not a recognized origin id; refusing to use it')
 if tracking and not ID.fullmatch(str(tracking)):raise ValueError('articleData.articleTrackingMeta.articleId is not a recognized origin id; refusing to use it')
 if origin and tracking and origin!=tracking:raise ValueError('articleData.originId and articleTrackingMeta.articleId disagree; refusing to choose one')
 chosen=origin or tracking
 if not chosen:raise ValueError('articleData exposed no originId and no articleTrackingMeta.articleId; refusing to guess')
 return chosen

def cli(action,**kwargs):
 try:
  p=subprocess.run(['minis-browser-use','--json',json.dumps({'action':action,**kwargs})],capture_output=True,text=True,timeout=90)
 except FileNotFoundError:
  raise RuntimeError('Browser automation CLI is unavailable; no metadata could be read')
 except subprocess.TimeoutExpired:
  raise RuntimeError('Browser did not finish within the time budget')
 if p.returncode:raise RuntimeError('Browser command failed; inspect browser without exposing credentials')
 try:return json.loads(p.stdout)
 except ValueError:raise RuntimeError('Browser returned non-JSON output')

def unwrap(value):
 if isinstance(value,str):
  try:return unwrap(json.JSONDecoder().raw_decode(value.lstrip())[0])
  except ValueError:return None
 if isinstance(value,dict):
  if 'ok' in value and 'requestedUrl' in value:return value
  for v in value.values():
   found=unwrap(v)
   if found is not None:return found
 if isinstance(value,list):
  for v in value:
   found=unwrap(v)
   if found is not None:return found
 return None

def _main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('url');p.add_argument('--metadata-json',type=pathlib.Path,help='Offline fixture: the JSON object probe_metadata.js returns, i.e. only __NEXT_DATA__ -> props.pageProps.articleData fields (no browser)');args=p.parse_args();validate(args.url)
 direct=re.search(r'/webview/((?:WP-WSJ-\d+|SB\d{10,}))(?:/|$)',urllib.parse.urlsplit(args.url).path)
 if direct:print(direct.group(1));return
 if args.metadata_json:
  try:data=json.loads(args.metadata_json.read_text())
  except (OSError,ValueError):raise ValueError('Metadata fixture is not readable JSON')
 else:
  nav=cli('navigate',url=args.url)
  # Reuse the tab returned by navigation, if the CLI exposes its ID.
  opts={'script':probe_script()}
  if isinstance(nav,dict) and isinstance(nav.get('tab_id'),int):opts['tab_id']=nav['tab_id']
  data=unwrap(cli('execute_js',**opts))
  if data is None:raise ValueError('No readable article metadata; stop and report browser access state')
 origin=select(data,args.url)
 print(origin)
def main():
 try:_main()
 except (ValueError,RuntimeError,subprocess.TimeoutExpired) as e:print('Resolution failed: '+str(e),file=sys.stderr);sys.exit(1)

if __name__=='__main__':
 main()
