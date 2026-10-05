import importlib.util
import tempfile
import unittest
from pathlib import Path
from PIL import Image
spec=importlib.util.spec_from_file_location('merge_tweet',Path(__file__).parents[1]/'scripts/merge_tweet.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
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
