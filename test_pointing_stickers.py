import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from sticker_model import STYLE_FILES,sticker_path,validate_stickers
from multitrack import normalize,render
from editor import probe
class PointingTests(unittest.TestCase):
 def test_all_assets_export(self):
  styles=[s for s in STYLE_FILES if s.startswith('pointing-')];self.assertEqual(len(styles),16)
  for s in styles:
   p=sticker_path(s)
   with Image.open(p) as im:self.assertGreater(im.n_frames,1)
   with Image.open(p.with_suffix('.png')) as im:self.assertEqual(im.size,(1920,960))
  data=dict(ratio='1:1',clips=[],captions=[],audio_clips=[],audio=None,stickers=validate_stickers([dict(style=s,start=i*.25,end=(i+1)*.25,width=.7,track='pointing') for i,s in enumerate(styles)]))
  normalize(data,data)
  with tempfile.TemporaryDirectory() as tmp:
   render(SimpleNamespace(root=Path(tmp)),'pointing',data,'test',False)
   duration,streams=probe(Path(tmp)/'pointing.mp4');self.assertAlmostEqual(duration,4,delta=.15);self.assertTrue(any(s['codec_type']=='video' for s in streams))
if __name__=='__main__':unittest.main()
