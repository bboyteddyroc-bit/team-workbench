import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import test_hub as fixtures
from storage_report import scan

class StorageReportTests(unittest.TestCase):
 setUp=fixtures.HubTests.setUp
 tearDown=fixtures.HubTests.tearDown
 login=fixtures.HubTests.login
 def test_permissions_and_counts(self):
  (self.hub.media/'sample.mp4').write_bytes(b'abc')
  self.assertEqual(self.member.get('/api/admin/storage-report').status_code,403)
  r=self.admin.get('/api/admin/storage-report');self.assertEqual(r.status_code,200,r.text)
  media=next(c for c in r.json()['categories'] if c['key']=='media')
  self.assertEqual(media['files'],1);self.assertEqual(media['bytes'],3)
  self.member.post('/api/logout',headers=fixtures.H)
  self.assertEqual(self.member.get('/api/admin/storage-report').status_code,401)
 def test_scan_limit_and_read_failure(self):
  import time
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'x').write_bytes(b'xyz')
   r=scan(p,time.monotonic()+5,limit=0);self.assertTrue(r['truncated']);self.assertEqual(r['bytes'],0)
   with patch('storage_report.os.scandir',side_effect=PermissionError('blocked')):
    self.assertEqual(scan(p,time.monotonic()+5)['errors'],1)
