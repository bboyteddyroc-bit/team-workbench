import tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from sticker_model import STYLE_FILES,validate_stickers,sticker_path
from multitrack import normalize,render
from editor import probe
class EmojiTests(unittest.TestCase):
 def test_assets_and_export(self):
  styles=[s for s in STYLE_FILES if s.startswith('emoji-')];self.assertEqual(len(styles),28)
  for s in styles:
   path=sticker_path(s)
   with Image.open(path) as im:self.assertGreater(im.n_frames,1)
   with Image.open(path.with_suffix('.png')) as im:self.assertEqual(im.size,(1920,768))
  stickers=validate_stickers([dict(style=s,start=i*.25,end=(i+1)*.25,width=.7,track='emoji') for i,s in enumerate(styles)])
  data=dict(ratio='1:1',clips=[],captions=[],audio_clips=[],audio=None,stickers=stickers);normalize(data,data)
  with tempfile.TemporaryDirectory() as tmp:
   render(SimpleNamespace(root=Path(tmp)),'emoji',data,'test',False)
   duration,streams=probe(Path(tmp)/'emoji.mp4');self.assertAlmostEqual(duration,7,delta=.15)
   self.assertTrue(any(s['codec_type']=='video' and s.get('r_frame_rate')=='30/1' for s in streams))
   self.assertTrue(any(s['codec_type']=='video' for s in streams))
if __name__=='__main__':unittest.main()
