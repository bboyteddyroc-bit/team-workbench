import unittest,tempfile,sqlite3,json
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from mobile_transfer import attach
class MobileTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  class Connection(sqlite3.Connection):
   def __exit__(self,*args):
    try:return super().__exit__(*args)
    finally:self.close()
  def db():
   c=sqlite3.connect(self.root/'db',factory=Connection);c.row_factory=sqlite3.Row;return c
  self.db=db
  with db() as c:
   c.executescript('CREATE TABLE users(id TEXT,enabled INTEGER);INSERT INTO users VALUES("a",1);INSERT INTO users VALUES("b",1);CREATE TABLE edit_exports(id TEXT,owner TEXT,state TEXT,body TEXT);')
   for i,o in [('one','a'),('two','a'),('other','b')]:
    c.execute('INSERT INTO edit_exports VALUES(?,?,?,?)',(i,o,'ready',json.dumps({'export_name':'成品'})));(self.root/(i+'.mp4')).write_bytes(b'video')
  app=FastAPI();app.state.editor=SimpleNamespace(root=self.root)
  def user(r):return {'id':r.headers.get('who','a')}
  async def body(r):return await r.json()
  async def upload(r,u):return {'owner':u['id'],'size':len(await r.body())}
  attach(app,SimpleNamespace(db=db),user,body,'https://example.test',upload);self.client=TestClient(app)
 def tearDown(self):self.tmp.cleanup()
 def test_scope_upload_download_zip_revoke(self):
  c=self.client;d=c.post('/api/mobile/transfers',json={'exports':['one','two']}).json();token=d['url'].split('#')[1];h={'X-Transfer-Token':token}
  self.assertEqual(len(c.get('/api/mobile/session',headers=h).json()['files']),2)
  self.assertEqual(c.get('/api/mobile/session').status_code,410)
  self.assertEqual(c.post('/api/mobile/upload',headers=h,content=b'123').json(),{'owner':'a','size':3})
  self.assertEqual(c.get('/api/mobile/file/other',params={'token':token}).status_code,404)
  self.assertEqual(c.post('/api/mobile/zip',headers=h,json={'ids':['other']}).status_code,400)
  self.assertEqual(c.post('/api/mobile/zip',headers=h,json={'ids':['one','two']}).content[:2],b'PK')
  self.assertEqual(c.get(d['qr']).status_code,200)
  self.assertEqual(c.get(d['qr'],headers={'who':'b'}).status_code,404)
  c.post('/api/mobile/transfers/'+d['id']+'/revoke',headers={'who':'b'})
  self.assertEqual(c.get('/api/mobile/session',headers=h).status_code,200)
  c.post('/api/mobile/transfers/'+d['id']+'/revoke')
  self.assertEqual(c.get('/api/mobile/session',headers=h).status_code,410)
 def test_foreign_and_expiry(self):
  self.assertEqual(self.client.post('/api/mobile/transfers',json={'exports':['other']}).status_code,404)
  d=self.client.post('/api/mobile/transfers',json={'exports':[]}).json()
  with self.db() as c:c.execute('UPDATE mobile_transfers SET expires=0')
  self.assertEqual(self.client.get('/api/mobile/session',headers={'X-Transfer-Token':d['url'].split('#')[1]}).status_code,410)
 def test_update_selection_preserves_token_and_expiry(self):
  c=self.client;d=c.post('/api/mobile/transfers',json={'exports':[]}).json();token=d['url'].split('#')[1];h={'X-Transfer-Token':token}
  path='/api/mobile/transfers/'+d['id']+'/selection'
  self.assertEqual(c.post(path,headers={'who':'b'},json={'exports':['one']}).status_code,410)
  self.assertEqual(c.post(path,json={'exports':['other']}).status_code,404)
  r=c.post(path,json={'exports':['one','two']});self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['expires'],d['expires'])
  self.assertEqual([f['id'] for f in c.get('/api/mobile/session',headers=h).json()['files']],['one','two'])
  self.assertEqual(c.get(d['qr']).status_code,200)
  c.post('/api/mobile/transfers/'+d['id']+'/revoke')
  self.assertEqual(c.post(path,json={'exports':[]}).status_code,410)
if __name__=='__main__':unittest.main()
