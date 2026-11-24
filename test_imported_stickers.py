import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from sticker_model import STYLE_FILES, validate_stickers
from multitrack import normalize, render
from editor import probe

class ImportedStickerTests(unittest.TestCase):
    def test_all_imported_styles_export(self):
        stickers=[dict(style=s,start=i*.5,end=(i+1)*.5,width=.7,track='sticker-main') for i,s in enumerate(STYLE_FILES) if s.startswith('tk-')]
        # Use local sequential timing independent of the built-in style indexes.
        for i,s in enumerate(stickers):s.update(start=i*.5,end=(i+1)*.5)
        data=dict(ratio='1:1',clips=[],captions=[],audio_clips=[],audio=None,stickers=validate_stickers(stickers))
        normalize(data,data)
        with tempfile.TemporaryDirectory() as tmp:
            render(SimpleNamespace(root=Path(tmp)),'imported-stickers',data,'test',False)
            duration,streams=probe(Path(tmp)/'imported-stickers.mp4')
            self.assertAlmostEqual(duration,3,delta=.15)
            self.assertTrue(any(s['codec_type']=='video' for s in streams))

if __name__=='__main__':unittest.main()
