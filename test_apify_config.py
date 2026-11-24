from test_kalodata_integration import Tests as Fixture
from apify_config import ApifyConfig
import unittest

class Tests(unittest.TestCase):
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    def test_config_permissions_rotation_and_encryption(self):
        path='/api/intelligence/apify/config'
        headers={'X-Hub-Request':'1','Origin':'http://127.0.0.1:8765'}
        self.assertEqual(self.b.post(path,headers=headers,json={'secret_key':'test-token-one'}).status_code,403)
        self.assertEqual(self.a.post(path,json={'secret_key':'test-token-one'}).status_code,403)
        for token in ('test-token-one','test-token-two'):
            response=self.a.post(path,headers=headers,json={'secret_key':token})
            self.assertEqual(response.status_code,200)
            self.assertNotIn(token,response.text)
            self.assertEqual(ApifyConfig(self.hub).secret(),token)
            with self.hub.db() as db:
                encrypted=bytes(db.execute('SELECT secret FROM apify_config').fetchone()[0])
            self.assertNotIn(token.encode(),encrypted)
        self.assertEqual(self.a.post(path,headers=headers,json={'secret_key':''}).status_code,400)
        self.assertEqual(ApifyConfig(self.hub).secret(),'test-token-two')
        self.assertNotIn('source',self.b.get('/api/intelligence/apify/status').json())
