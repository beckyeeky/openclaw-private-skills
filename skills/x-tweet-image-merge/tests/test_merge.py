import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from PIL import Image
spec=importlib.util.spec_from_file_location('merge_tweet',Path(__file__).parents[1]/'scripts/merge_tweet.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

# Shape taken from a live cdn.syndication.twimg.com/tweet-result response: every photo
# declares the same expandedUrl (.../photo/1), and a quoted tweet carries its own photo.
FIXTURE={
  '__typename':'Tweet',
  'id_str':'123',
  'text':'three photos',
  'photos':[
    {'url':'https://pbs.twimg.com/media/AAA111.jpg','width':991,'height':1920,
     'expandedUrl':'https://x.com/u/status/123/photo/1'},
    {'url':'https://pbs.twimg.com/media/BBB222.jpg','width':991,'height':1920,
     'expandedUrl':'https://x.com/u/status/123/photo/1'},
    {'url':'https://pbs.twimg.com/media/CCC333.jpg','width':991,'height':1920,
     'expandedUrl':'https://x.com/u/status/123/photo/1'},
  ],
  'mediaDetails':[
    {'type':'photo','media_url_https':'https://pbs.twimg.com/media/AAA111.jpg',
     'original_info':{'width':991,'height':1920},'ext_media_availability':{'status':'Available'}},
    {'type':'photo','media_url_https':'https://pbs.twimg.com/media/BBB222.jpg',
     'original_info':{'width':991,'height':1920},'ext_media_availability':{'status':'Available'}},
    {'type':'photo','media_url_https':'https://pbs.twimg.com/media/CCC333.jpg',
     'original_info':{'width':991,'height':1920},'ext_media_availability':{'status':'Available'}},
  ],
  'quoted_tweet':{'id_str':'999','photos':[{'url':'https://pbs.twimg.com/media/QUOTED.jpg'}]},
}

class MetadataTests(unittest.TestCase):
    def test_fixture_order_dedupe_and_quote_exclusion(self):
        with mock.patch.object(m,'fetch_tweet_json',lambda tweet_id:FIXTURE):
            photos,total,video=m.metadata_photos('123')
        self.assertEqual(len(photos),3)
        self.assertEqual(total,3)
        self.assertFalse(video)
        self.assertEqual([p['index'] for p in photos],[1,2,3])
        self.assertEqual([p['url'] for p in photos],[
            'https://pbs.twimg.com/media/AAA111.jpg?name=orig',
            'https://pbs.twimg.com/media/BBB222.jpg?name=orig',
            'https://pbs.twimg.com/media/CCC333.jpg?name=orig'])
        self.assertFalse(any('QUOTED' in p['url'] for p in photos))

    def test_dedupe_uses_media_path_not_expanded_url(self):
        duplicate=json.loads(json.dumps(FIXTURE))
        duplicate['photos']=duplicate['photos']+[{'url':'https://pbs.twimg.com/media/AAA111.jpg?name=large'}]
        with mock.patch.object(m,'fetch_tweet_json',lambda tweet_id:duplicate):
            photos,_,_=m.metadata_photos('123')
        self.assertEqual(len(photos),3)

    def test_media_details_fallback_filters_and_detects_video(self):
        payload={'mediaDetails':[
            {'type':'photo','media_url_https':'https://pbs.twimg.com/media/P1.jpg',
             'ext_media_availability':{'status':'Available'}},
            {'type':'photo','media_url_https':'https://pbs.twimg.com/media/GONE.jpg',
             'ext_media_availability':{'status':'Unavailable'}},
            {'type':'video','media_url_https':'https://pbs.twimg.com/media/V1.jpg',
             'ext_media_availability':{'status':'Available'}}]}
        urls,video=m.metadata_media(payload)
        self.assertEqual(urls,['https://pbs.twimg.com/media/P1.jpg'])
        self.assertTrue(video)
        with self.assertRaises(m.MetadataUnavailable):
            m.metadata_media({'id_str':'123','text':'text only'})

    def test_schema_drift_is_not_zero_photos(self):
        with self.assertRaises(m.SchemaDrift):
            m.metadata_media({'photos':[{'width':991}]})

    def test_tombstone_and_non_json(self):
        with self.assertRaises(m.MetadataUnavailable):
            m._parse_payload('{"__typename":"TweetTombstone","tombstone":{}}')
        with self.assertRaises(m.MetadataUnavailable):
            m._parse_payload('<html>not json</html>')

    def test_expected_count_mismatch_exits_1(self):
        buffer=io.StringIO()
        with mock.patch.object(m,'fetch_tweet_json',lambda tweet_id:FIXTURE), \
             contextlib.redirect_stdout(buffer):
            code=m.main(['https://x.com/u/status/123','--via','metadata','--expected-count','2'])
        result=json.loads(buffer.getvalue())
        self.assertEqual(code,1)
        self.assertEqual(result['status'],'error')
        self.assertIn('expected 2 photos but found 3',result['error'])

    def test_auto_without_browser_reports_metadata_reason(self):
        def unavailable(tweet_id):
            raise m.MetadataUnavailable('HTTP 404 (deleted, protected or members-only post)')
        with mock.patch.object(m,'fetch_tweet_json',unavailable), \
             mock.patch.object(m,'browser_available',lambda:False):
            result=m.run(m.build_parser().parse_args(['https://x.com/u/status/123']))
        self.assertEqual(result['status'],'error')
        self.assertEqual(result['source'],'metadata') if 'source' in result else None
        self.assertIn('not installed',result['error'])

    def test_via_browser_without_binary_is_explicit(self):
        args=m.build_parser().parse_args(['https://x.com/u/status/123','--via','browser'])
        with mock.patch.object(m,'browser_available',lambda:False):
            result=m.run(args)
        self.assertEqual(result['status'],'error')
        self.assertIn('not installed',result['error'])
        self.assertIn('--via metadata',result['error'])

    def test_auto_prefers_metadata_without_touching_browser(self):
        calls=[]
        def explode(*args,**kwargs):
            calls.append(args); raise AssertionError('browser must not be used when metadata works')
        with mock.patch.object(m,'fetch_tweet_json',lambda tweet_id:FIXTURE), \
             mock.patch.object(m,'download',lambda url,path:Image.new('RGB',(4,3),'red').save(path,format='PNG')), \
             mock.patch.object(m,'browser',explode), \
             tempfile.TemporaryDirectory() as directory:
            args=m.build_parser().parse_args(['https://x.com/u/status/123','--output',str(Path(directory)/'out.png')])
            result=m.run(args)
        self.assertEqual(calls,[])
        self.assertEqual(result['source'],'metadata')
        self.assertEqual(result['photo_count'],3)

class CliJsonTests(unittest.TestCase):
    def test_metadata_success_json_contract(self):
        with mock.patch.object(m,'fetch_tweet_json',lambda tweet_id:FIXTURE), \
             mock.patch.object(m,'download',lambda url,path:Image.new('RGB',(4,3),'red').save(path,format='PNG')), \
             tempfile.TemporaryDirectory() as directory:
            buffer=io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code=m.main(['https://x.com/u/status/123','--via','metadata','--output',str(Path(directory)/'out.png')])
            result=json.loads(buffer.getvalue())
        self.assertEqual(code,0)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['source'],'metadata')
        self.assertIsNone(result['fallback_reason'])
        self.assertEqual(result['photo_count'],3)
        self.assertEqual(result['completeness']['total_from_metadata'],3)
        self.assertTrue(Path(result['output']).is_absolute())
        self.assertNotIn('minis_url',result)

class MergeTests(unittest.TestCase):
    def test_sizes_order_white_and_single(self):
        with tempfile.TemporaryDirectory() as d:
            a,b,out=[Path(d)/n for n in ('a.png','b.png','out.png')]
            Image.new('RGB',(3,2),'red').save(a)
            Image.new('RGB',(2,4),'blue').save(b)
            result=m.merge([a,b],out)
            self.assertEqual((result['width'],result['height']),(5,4))
            with Image.open(out) as image:
                self.assertEqual(image.getpixel((0,0)),(255,0,0))
                self.assertEqual(image.getpixel((3,0)),(0,0,255))
                self.assertEqual(image.getpixel((0,3)),(255,255,255))
            self.assertEqual(m.merge([a],out)['source_sizes'],[[3,2]])
    def test_failures(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out.png'; bad=Path(d)/'bad';bad.write_text('not an image')
            with self.assertRaises(ValueError):m.merge([],out)
            with self.assertRaises(Exception):m.merge([bad],out)
            self.assertFalse(out.exists())
    def test_cli_result(self):
        self.assertEqual(m.decode_result({'text':'{"photos":[]}\n  tab_id: 1'}),{'photos':[]})
if __name__=='__main__':unittest.main()
