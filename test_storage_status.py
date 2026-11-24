import unittest
from unittest.mock import patch
from collections import namedtuple
import test_hub as fixtures

class StorageStatusTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    def test_auth_levels_and_error(self):
        self.assertEqual(self.member.get('/api/storage-status').status_code,200)
        self.member.post('/api/logout',headers=fixtures.H)
        self.assertEqual(self.member.get('/api/storage-status').status_code,401)
        du=namedtuple('usage','total used free')
        for free,expected in [(25,'normal'),(19,'warning'),(4,'critical'),(20,'normal'),(5,'warning')]:
            with patch('app.shutil.disk_usage',return_value=du(100*1024**3,0,free*1024**3)) as m:
                r=self.admin.get('/api/storage-status')
                self.assertEqual(r.status_code,200);self.assertEqual(r.json()['level'],expected)
                self.assertEqual(m.call_args.args[0],self.hub.media.resolve())
        with patch('app.shutil.disk_usage',side_effect=OSError('not available')):
            self.assertEqual(self.admin.get('/api/storage-status').status_code,503)
