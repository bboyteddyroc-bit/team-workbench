import os
import tempfile
import unittest
import httpx
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app, password_hash
from kalodata_integration import Kalodata, QueryError, identifier

BASE = 'http://127.0.0.1:8765'
HEADERS = {'X-Hub-Request': '1', 'Origin': BASE}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'HUB_ORIGIN': BASE, 'KALODATA_SECRET_KEY': 'test-secret-never-return'})
        self.env.start()
        self.app = create_app(self.tmp.name, worker=False)
        self.hub, self.service = self.app.state.hub, self.app.state.kalodata
        with self.hub.db() as db:
            for name in ('alice', 'bob'):
                db.execute('INSERT INTO users(id,username,password,role) VALUES(?,?,?,?)',
                           (name,name,password_hash('test-password-123'),'admin' if name == 'alice' else 'member'))
        self.a, self.b = TestClient(self.app, base_url=BASE), TestClient(self.app, base_url=BASE)
        for client, name in ((self.a, 'alice'),(self.b, 'bob')):
            self.assertEqual(client.post('/api/login',headers=HEADERS,json={'username':name,'password':'test-password-123'}).status_code,200)

    def tearDown(self):
        self.a.close(); self.b.close(); self.env.stop(); self.tmp.cleanup()

    def submit(self, client=None, **changes):
        data = dict(kind='creator',target='@demo',days=7,request_key='test-request-key-00001',allow_paid_api=True)
        data.update(changes)
        return (client or self.a).post('/api/intelligence/kalodata/jobs',headers=HEADERS,json=data)

    def test_idempotency_and_owner_isolation(self):
        first=self.submit();self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['id'],self.submit().json()['id'])
        self.assertEqual(first.json()['id'],self.submit(request_key='test-request-key-00002').json()['id'])
        self.assertEqual(self.submit(target='different').status_code,409)
        self.assertEqual(self.b.get('/api/intelligence/kalodata/jobs').json(),[])
        self.assertNotIn('test-secret',self.a.get('/api/intelligence/kalodata/status').text)
        self.assertEqual(TestClient(self.app,base_url=BASE).get('/api/intelligence/kalodata/jobs').status_code,401)
        self.assertEqual(self.a.post('/api/intelligence/kalodata/jobs',json={}).status_code,403)

    def test_real_mapping_missing_not_zero_and_no_raw(self):
        self.submit()
        with patch.object(self.service,'post',side_effect=[
            [{'creator_handle':'demo','creator_id':'12345'}],
            {'creator_id':'12345','creator_handle':'demo','revenue':123,'revenue_trend':[1]*7,'email':'private@example.test'}
        ]) as mock:
            self.service.tick(); self.assertEqual(mock.call_count,2)
        job=self.a.get('/api/intelligence/kalodata/jobs').json()[0]
        self.assertEqual(job['state'],'ready');self.assertIsNone(job['result']['units'])
        self.assertEqual(len(job['result']['daily_gmv']),7)
        self.assertNotIn('private@example',str(job))
        self.assertEqual(self.submit(request_key='test-request-key-00003').json()['id'],job['id'])

    def test_no_substitute_and_no_retry(self):
        self.submit()
        with patch.object(self.service,'post',return_value=[{'creator_handle':'demo_other','creator_id':'44444'}]) as mock:
            self.service.tick(); self.service.tick();self.assertEqual(mock.call_count,1)
        self.assertEqual(self.a.get('/api/intelligence/kalodata/jobs').json()[0]['state'],'attention')

    def test_recovery_does_not_repeat_paid_call(self):
        job=self.submit().json()
        with self.hub.db() as db:db.execute("UPDATE kalodata_jobs SET state='running' WHERE id=?",(job['id'],))
        self.service.recover()
        with patch.object(self.service,'fetch') as mock:
            self.service.tick();mock.assert_not_called()
        self.assertEqual(self.a.get('/api/intelligence/kalodata/jobs').json()[0]['state'],'attention')

    def test_validation_and_product(self):
        self.assertEqual(self.submit(allow_paid_api=False).status_code,400)
        self.assertEqual(self.submit(region='GB').status_code,400)
        self.assertEqual(self.submit(days=8).status_code,400)
        self.assertEqual(self.submit(target='https://evil.example/@demo').status_code,400)
        self.assertEqual(identifier('video','https://www.tiktok.com/@demo/video/123456789'),'123456789')
        response=self.submit(kind='product',target='123456789')
        self.assertEqual(response.status_code,200)
        with patch.object(self.service,'post',return_value={'product_id':'123456789','sales_volumn':'0','revenue_trend':[1,2]}) as mock:
            self.service.tick();self.assertEqual(mock.call_count,1)
        result=self.a.get('/api/intelligence/kalodata/jobs').json()[0]['result']
        self.assertEqual(result['units'],0);self.assertEqual(result['daily_gmv'],[])

    def test_missing_secret_and_safe_errors(self):
        with patch.dict(os.environ,{'KALODATA_SECRET_KEY':''}):
            self.assertEqual(self.submit().status_code,503)
        self.submit()
        with patch.object(self.service,'fetch',side_effect=RuntimeError('test-secret-never-return')):
            self.service.tick()
        response=self.a.get('/api/intelligence/kalodata/jobs')
        self.assertNotIn('test-secret',response.text)

    def test_insufficient_credits_is_actionable_without_retry(self):
        with patch('kalodata_integration.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value = httpx.Response(200,json={
                'success':False,'code':2016,'message':'Insufficient credit balance.'})
            with self.assertRaisesRegex(QueryError,'2016'):
                self.service.post('/creator/rank',{})
            self.assertEqual(client.return_value.__enter__.return_value.post.call_count,1)

    def test_http_200_not_found_is_business_failure_without_retry(self):
        with patch('kalodata_integration.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value=httpx.Response(200,json={'success':False,'data':None,'message':'video not found','code':None})
            with self.assertRaisesRegex(QueryError,'video not found') as error:self.service.post('/video/detail',{})
            self.assertIn('/video/detail',str(error.exception));self.assertIn('未提供',str(error.exception))
            self.assertEqual(client.return_value.__enter__.return_value.post.call_count,1)
    def test_unknown_failure_never_echoes_secrets_or_signed_urls(self):
        with patch('kalodata_integration.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value=httpx.Response(200,json={'success':False,'code':'E_TEST','message':'test-secret-never-return https://host/file?signature=private'})
            with self.assertRaises(QueryError) as error:self.service.post('/video/url',{})
            self.assertIn('E_TEST',str(error.exception));self.assertNotIn('test-secret',str(error.exception));self.assertNotIn('signature',str(error.exception))
    def test_media_queue_and_unavailable_codes_are_not_success(self):
        for code,reason in (('1054','已排队'),('1053','无法提供')):
            with patch('kalodata_integration.httpx.Client') as client:
                client.return_value.__enter__.return_value.post.return_value=httpx.Response(200,json={'success':False,'code':code})
                with self.assertRaisesRegex(QueryError,reason):self.service.post('/video/url',{})
                self.assertEqual(client.return_value.__enter__.return_value.post.call_count,1)
    def test_successful_media_data_is_returned_intact(self):
        data={'video_id':'123456789','video_url':'https://openapi-video.kalodata.com/v?sig=test'}
        with patch('kalodata_integration.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value=httpx.Response(200,json={'success':True,'data':data,'code':None})
            self.assertEqual(self.service.post('/video/url',{}),data)
    def test_config_admin_only_encrypted_and_no_paid_call(self):
        path='/api/intelligence/kalodata/config'
        payload={'secret_key':'replacement-secret-12345'}
        self.assertEqual(self.b.post(path,headers=HEADERS,json=payload).status_code,403)
        self.assertEqual(self.a.post(path,json=payload).status_code,403)
        with patch.object(self.service,'post') as upstream:
            response=self.a.post(path,headers=HEADERS,json=payload)
            self.assertEqual(response.status_code,200,response.text)
            upstream.assert_not_called()
        self.assertEqual(response.json()['source'],'saved')
        self.assertNotIn(payload['secret_key'],response.text)
        with self.hub.db() as db:
            stored=bytes(db.execute('SELECT secret FROM kalodata_config').fetchone()[0])
            audit=str([dict(r) for r in db.execute("SELECT * FROM audit WHERE action='kalodata_key_updated'")])
        self.assertNotIn(payload['secret_key'].encode(),stored)
        self.assertNotIn(payload['secret_key'],audit)
        self.assertEqual(self.hub.cipher.decrypt(stored).decode(),payload['secret_key'])
        self.assertEqual(Kalodata(self.hub).secret(),payload['secret_key'])
        self.assertNotIn('source',self.b.get('/api/intelligence/kalodata/status').json())

    def test_rotation_is_immediate_and_invalid_save_preserves_old_key(self):
        path='/api/intelligence/kalodata/config'
        for value in ['saved-key-one','saved-key-two']:
            self.assertEqual(self.a.post(path,headers=HEADERS,json={'secret_key':value}).status_code,200)
            with patch('kalodata_integration.httpx.Client') as client:
                client.return_value.__enter__.return_value.post.return_value=httpx.Response(200,json={'success':True,'data':{}})
                self.service.post('/video/detail',{})
                self.assertEqual(client.return_value.__enter__.return_value.post.call_args.kwargs['headers']['secret-key'],value)
        for value in ['',None,'short','bad key with spaces','invalid\nheader']:
            self.assertEqual(self.a.post(path,headers=HEADERS,json={'secret_key':value}).status_code,400)
        self.assertEqual(self.service.secret(),'saved-key-two')
        with self.hub.db() as db:db.execute("UPDATE kalodata_config SET secret=?",(b'broken',))
        self.assertFalse(self.a.get('/api/intelligence/kalodata/status').json()['configured'])
        with self.assertRaises(QueryError):self.service.secret()


if __name__=='__main__': unittest.main()
