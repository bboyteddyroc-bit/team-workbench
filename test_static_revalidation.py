import unittest
from test_hub import HubTests

class StaticRevalidationTests(HubTests):
    def test_static_revalidates_private_api_does_not_cache(self):
        response=self.member.get('/static/app.js')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['cache-control'],'private, no-cache')
        etag=response.headers.get('etag');self.assertTrue(etag)
        cached=self.member.get('/static/app.js',headers={'If-None-Match':etag})
        self.assertEqual(cached.status_code,304);self.assertEqual(cached.content,b'')
        for path in ('/','/api/tasks?compact=true','/api/voice/config','/static/missing-test-file.js'):
            self.assertEqual(self.member.get(path).headers['cache-control'],'no-store',path)

if __name__=='__main__':unittest.main()
