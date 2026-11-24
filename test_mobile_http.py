import io,zipfile,unittest
from fastapi.testclient import TestClient
from test_mobile_transfer import MobileTests
from mobile_http import create_phone_app,mobile_origin
from unittest.mock import patch

class MobileHTTPTests(MobileTests):
 def setUp(self):
  super().setUp()
  self.origin='http://192.168.100.10:8000'
  self.phone_app=create_phone_app(self.client.app,origin=self.origin,networks=['192.168.100.0/23'])
  self.phone=TestClient(self.phone_app,base_url=self.origin,client=('192.168.100.42',54321))
  self.h={'X-Hub-Request':'1','Origin':self.origin}
 def tearDown(self):
  self.phone.close();self.client.close();super().tearDown()
 def test_phone_only_routes_and_guards(self):
  c=self.phone
  self.assertEqual(c.get('/health').json()['service'],'hub-mobile-transfer')
  for path in ['/api/login','/api/me','/api/editor/library','/api/mobile/transfers','/api/mobile/received','/static/app.js','/static/index.html','/docs','/openapi.json']:
   self.assertEqual(c.get(path).status_code,404,path)
  self.assertEqual(c.post('/api/mobile/transfers',json={},headers=self.h).status_code,404)
  self.assertEqual(c.get('/mobile/',headers={'Host':'evil.example'}).status_code,400)
  self.assertEqual(c.get('/mobile/',headers={'Origin':'https://evil.example'}).status_code,403)
  self.assertEqual(c.post('/api/mobile/upload',content=b'1').status_code,403)
  self.assertEqual(c.get('/api/mobile/session').status_code,410)
  self.assertEqual(c.get('/static/mobile-receiver.js').status_code,200)
  r=c.get('/mobile/');self.assertEqual(r.status_code,200)
  self.assertIn('不加密',r.text);self.assertEqual(r.headers['cache-control'],'no-store')
  self.assertEqual(r.headers['referrer-policy'],'no-referrer')
 def test_subnet_restriction(self):
  for address in ['8.8.8.8','192.168.102.8','10.0.0.8']:
   with TestClient(self.phone_app,base_url=self.origin,client=(address,1234)) as c:
    self.assertEqual(c.get('/health',headers={'X-Forwarded-For':'192.168.100.42'}).status_code,403,address)
  with TestClient(self.phone_app,base_url=self.origin,client=('192.168.101.8',1234)) as c:
   self.assertEqual(c.get('/health').status_code,200)
 def test_token_cross_listener_and_same_link_selection(self):
  d=self.client.post('/api/mobile/transfers',json={'exports':['one','two']}).json()
  self.assertTrue(d['url'].startswith('http://192.168.100.10:8000/mobile/#'))
  token=d['url'].split('#')[1];h={**self.h,'X-Transfer-Token':token}
  self.assertEqual(self.phone.get('/api/mobile/session',headers=h).status_code,200)
  self.assertEqual(self.phone.post('/api/mobile/upload',content=b'video',headers=h).json(),{'owner':'a','size':5})
  self.assertEqual(self.phone.get('/api/mobile/file/other',params={'token':token}).status_code,404)
  response=self.phone.get('/api/mobile/zip-download',params={'token':token,'ids':'one,two'})
  self.assertEqual(response.status_code,200)
  with zipfile.ZipFile(io.BytesIO(response.content)) as archive:self.assertEqual(len(archive.namelist()),2)
  self.client.post('/api/mobile/transfers/'+d['id']+'/selection',json={'exports':['one']})
  self.assertEqual(len(self.phone.get('/api/mobile/session',headers=h).json()['files']),1)
  self.client.post('/api/mobile/transfers/'+d['id']+'/revoke')
  self.assertEqual(self.phone.get('/api/mobile/session',headers=h).status_code,410)
 def test_body_limits(self):
  self.assertEqual(self.phone.post('/api/mobile/zip',content=b'a'*(2*1024*1024+1),headers=self.h).status_code,413)
 def test_config_rejects_public_http(self):
  with patch.dict('os.environ',{'HUB_MOBILE_ORIGIN':'http://8.8.8.8:8000'}):
   with self.assertRaises(ValueError):mobile_origin()

if __name__=='__main__':unittest.main()
