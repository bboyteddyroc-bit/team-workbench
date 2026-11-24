import unittest,tempfile,os
from pathlib import Path
from unittest.mock import patch
import libtv_isolation as iso
class Tests(unittest.TestCase):
 def test_profiles_and_fail_closed(self):
  with tempfile.TemporaryDirectory() as d,patch.object(iso,'ROOT',Path(d)/'profiles'):
   for name in ['legacy','alice','bob']:
    p=iso.profile_dir(name);p.mkdir(parents=True);(p/'credentials.json').write_text('{}')
   a=Path(d)/'a';a.mkdir();b=Path(d)/'b';b.mkdir()
   iso.bind(a,'alice');iso.bind(b,'bob')
   with patch.dict(os.environ,{'LIBTV_TOKEN':'global-secret','LIBTV_CONFIG_DIR':'global'}):
    ea=iso.environment(a);eb=iso.environment(b)
    self.assertNotEqual(ea['LIBTV_CONFIG_DIR'],eb['LIBTV_CONFIG_DIR'])
    self.assertNotIn('LIBTV_TOKEN',ea)
    self.assertEqual(os.environ['LIBTV_TOKEN'],'global-secret')
   with self.assertRaises(RuntimeError):iso.bind(a,'bob')
   (iso.profile_dir('alice')/'credentials.json').unlink()
   with self.assertRaises(RuntimeError):iso.environment(a)
   with self.assertRaises(ValueError):iso.profile_dir('../escape')
 def test_existing_binding_is_read_only(self):
  with tempfile.TemporaryDirectory() as d:
   iso.bind(d,'alice')
   with patch.object(Path,'open',side_effect=PermissionError('write forbidden')) as blocked:
    with patch.object(Path,'read_text',return_value='{"profile":"alice"}'):
     iso.bind(d,'alice')
     blocked.assert_not_called()
     with self.assertRaises(RuntimeError):iso.bind(d,'bob')

if __name__=='__main__':unittest.main()
