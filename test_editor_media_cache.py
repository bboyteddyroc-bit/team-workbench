import tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import editor_media_cache as cache
class CacheTests(unittest.TestCase):
 def test_persistent_cache_invalidates_on_replace(self):
  with tempfile.TemporaryDirectory() as d,patch.object(cache,'ROOT',Path(d)/'cache'):
   p=Path(d)/'video';p.write_bytes(b'first');loader=Mock(return_value=(3,[{'codec_type':'video'}]))
   self.assertEqual(cache.metadata(p,loader)[0],3)
   self.assertEqual(cache.metadata(p,loader)[0],3);self.assertEqual(loader.call_count,1)
   p.write_bytes(b'replaced');cache.metadata(p,loader);self.assertEqual(loader.call_count,2)
   p.unlink()
   with self.assertRaises(FileNotFoundError):cache.metadata(p,loader)
if __name__=='__main__':unittest.main()
