import os,tempfile,time,unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from fastapi.testclient import TestClient
from app import create_app,password_hash
from feishu_integration import folder_token
BASE='https://192.168.100.10:8443'
H={'X-Hub-Request':'1','Origin':BASE}
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  with patch.dict(os.environ,{'HUB_ORIGIN':BASE}):self.app=create_app(self.tmp.name,worker=False)
  self.hub=self.app.state.hub;self.f=self.app.state.feishu
  with self.hub.db() as db:
   for uid in ('alice','bob'):db.execute('INSERT INTO users(id,username,password,role) VALUES(?,?,?,?)',(uid,uid,password_hash('test-password-123'),'admin' if uid=='alice' else 'member'))
   db.execute('INSERT INTO feishu_config VALUES(1,?)',(self.f.pack({'app_id':'cli_test','app_secret':'secret-test','origin':BASE}),))
  self.a=TestClient(self.app,base_url=BASE);self.b=TestClient(self.app,base_url=BASE)
  for c,n in ((self.a,'alice'),(self.b,'bob')):self.assertEqual(c.post('/api/login',headers=H,json={'username':n,'password':'test-password-123'}).status_code,200)
 def tearDown(self):self.a.close();self.b.close();self.tmp.cleanup()
 def auth(self,client,subject,mode='bind'):
  r=client.get('/api/feishu/start?mode='+mode,follow_redirects=False);self.assertEqual(r.status_code,302)
  state=parse_qs(urlsplit(r.headers['location']).query)['state'][0]
  with patch.object(self.f,'call',side_effect=[{'access_token':'secret-token','refresh_token':'secret-refresh','expires_in':7200},{'open_id':subject,'name':'Test'}]):
   result=client.get('/api/feishu/callback',params={'state':state,'code':'test'},follow_redirects=False)
  return result,state
 def test_callback_ignores_broken_proxy_environment(self):
  import httpx
  r=self.a.get('/api/feishu/start?mode=bind',follow_redirects=False)
  state=parse_qs(urlsplit(r.headers['location']).query)['state'][0]
  seen=[]
  def respond(request):
   seen.append(request.url.path)
   if request.url.path.endswith('/oauth/token'):return httpx.Response(200,json={'access_token':'test','expires_in':3600})
   return httpx.Response(200,json={'data':{'open_id':'ou_proxy_test','name':'Test'}})
  real_client=httpx.Client
  def client(**kwargs):
   self.assertIs(kwargs.get('trust_env'),False)
   return real_client(transport=httpx.MockTransport(respond),**kwargs)
  with patch.dict(os.environ,{'NO_PROXY':'[::1]'}),patch('feishu_integration.httpx.Client',side_effect=client):
   result=self.a.get('/api/feishu/callback',params={'state':state,'code':'test'},follow_redirects=False)
  self.assertEqual(result.status_code,303,result.text)
  self.assertEqual(len(seen),2)
 def test_callback_invalid_url_is_handled(self):
  import httpx
  r=self.a.get('/api/feishu/start?mode=bind',follow_redirects=False)
  state=parse_qs(urlsplit(r.headers['location']).query)['state'][0]
  with patch('feishu_integration.httpx.Client',side_effect=httpx.InvalidURL('sensitive internal detail')):
   result=self.a.get('/api/feishu/callback',params={'state':state,'code':'test'},follow_redirects=False)
  self.assertEqual(result.status_code,400)
  self.assertNotIn('sensitive internal detail',result.text)
 def test_bind_login_replay_and_conflict(self):
  r,state=self.auth(self.a,'ou_alice');self.assertEqual(r.status_code,303,r.text)
  self.assertEqual(self.a.get('/api/feishu/callback',params={'state':state,'code':'test'}).status_code,400)
  self.assertEqual(self.auth(self.b,'ou_alice')[0].status_code,400)
  self.assertEqual(self.auth(self.b,'ou_bob',mode='login')[0].status_code,400)
  self.a.post('/api/logout',headers=H)
  self.assertEqual(self.auth(self.a,'ou_alice',mode='login')[0].status_code,303)
  self.assertEqual(self.a.get('/api/me').json()['id'],'alice')
  with self.hub.db() as db:self.assertNotIn(b'secret-token',bytes(db.execute('SELECT secret FROM feishu_links').fetchone()[0]))
 def test_csrf_cookie_and_disabled_user(self):
  r=self.a.get('/api/feishu/start?mode=bind',follow_redirects=False);state=parse_qs(urlsplit(r.headers['location']).query)['state'][0]
  self.assertEqual(self.b.get('/api/feishu/callback',params={'state':state,'code':'test'}).status_code,400)
  with self.hub.db() as db:db.execute("UPDATE users SET enabled=0 WHERE id='alice'")
  self.assertEqual(self.a.get('/api/feishu/callback',params={'state':state,'code':'test'}).status_code,403)
 def test_folder_validation_and_personal_preferences(self):
  self.auth(self.a,'ou_a');self.auth(self.b,'ou_b')
  with patch.object(self.f,'list_folder',return_value=[]):
   self.assertEqual(self.a.post('/api/feishu/preferences',headers=H,json={'folder':'https://team.feishu.cn/drive/folder/AAA','enabled':True}).status_code,200)
  self.assertEqual(self.b.get('/api/feishu/status').json()['folder'],'')
  self.assertNotIn('secret',self.a.get('/api/feishu/status').text)
  for url in ['http://team.feishu.cn/drive/folder/a','https://evil.com/drive/folder/a','https://team.feishu.cn/docx/a']:
   with self.assertRaises(ValueError):folder_token(url)
 def job(self):
  with self.hub.db() as db:
   db.execute("INSERT INTO feishu_prefs VALUES('alice','ROOT',1)")
   db.execute("INSERT INTO edit_exports VALUES('exp','alice','p','{}','ready','',1,1,'key')")
   self.f.queue(db,'exp','alice',1762041600);self.f.queue(db,'exp','alice',1762041600)
  p=self.hub.directory/'edits'/'exp.mp4';p.write_bytes(b'abcdefgh')
 def test_upload_resume_and_isolation(self):
  self.job();parts=[]
  def call(path,token=None,method='GET',**kw):
   if path.endswith('create_folder'):return {'token':'DAY'}
   if path.endswith('upload_prepare'):return {'upload_id':'UP','block_size':4,'block_num':2}
   if path.endswith('upload_part'):
    parts.append(kw['data']['seq'])
    if parts==['0','1']:raise ValueError('interrupted')
    return {}
   if path.endswith('upload_finish'):return {'file_token':'FILE'}
   raise AssertionError(path)
  with patch.object(self.f,'token',return_value='t'),patch.object(self.f,'list_folder',return_value=[]),patch.object(self.f,'call',side_effect=call):
   self.f.tick();self.assertEqual(self.a.get('/api/feishu/uploads').json()[0]['state'],'attention')
   self.assertEqual(self.b.get('/api/feishu/uploads').json(),[])
   self.assertEqual(self.b.post('/api/feishu/uploads/exp/retry',headers=H).status_code,404)
   self.assertEqual(self.a.post('/api/feishu/uploads/exp/retry',headers=H).status_code,200)
   self.f.tick()
  self.assertEqual(parts,['0','1','1']);self.assertEqual(self.a.get('/api/feishu/uploads').json()[0]['state'],'ready')
 def test_named_upload_has_no_export_id_suffix(self):
  self.job();sent=[]
  with self.hub.db() as db:db.execute("UPDATE edit_exports SET body=? WHERE id='exp'",('{"export_name":"我的视频"}',))
  def call(path,token=None,method='GET',**kw):
   if path.endswith('create_folder'):return {'token':'DAY'}
   if path.endswith('upload_prepare'):
    sent.append(kw['json']['file_name']);return {'upload_id':'UP','block_size':8,'block_num':1}
   if path.endswith('upload_part'):return {}
   if path.endswith('upload_finish'):return {'file_token':'FILE'}
   raise AssertionError(path)
  with patch.object(self.f,'token',return_value='t'),patch.object(self.f,'list_folder',return_value=[]),patch.object(self.f,'call',side_effect=call):self.f.tick()
  self.assertEqual(sent,['我的视频.mp4'])
  self.assertEqual(self.a.get('/api/feishu/uploads').json()[0]['state'],'ready')
 def test_same_name_does_not_reconcile_unrelated_file(self):
  self.job()
  with self.hub.db() as db:db.execute("UPDATE edit_exports SET body=? WHERE id='exp'",('{"export_name":"我的视频"}',))
  with patch.object(self.f,'token',return_value='t'),patch.object(self.f,'list_folder',side_effect=[[{'type':'folder','name':'251102','token':'DAY'}],[{'type':'file','name':'我的视频.mp4','token':'OTHER'}]]),patch.object(self.f,'call') as remote:
   self.f.tick();remote.assert_not_called()
  result=self.a.get('/api/feishu/uploads').json()[0]
  self.assertEqual(result['state'],'attention');self.assertIn('同名文件',result['error']);self.assertFalse(result['file_token'])
 def test_legacy_name_requires_content_verification(self):
  self.job()
  with patch.object(self.f,'token',return_value='t'),patch.object(self.f,'list_folder',side_effect=[[{'type':'folder','name':'251102','token':'DAY'}],[{'type':'file','name':'成片_exp.mp4','token':'OLD'}]]),patch.object(self.f,'call',return_value={'token':'DAY'}) as remote:
   self.f.tick()
   remote.assert_not_called()
   result=self.a.get('/api/feishu/uploads').json()[0]
   self.assertEqual(result['state'],'attention');self.assertFalse(result['file_token'])
   self.assertIn('不能仅凭文件名',result['error'])
if __name__=='__main__':unittest.main()
