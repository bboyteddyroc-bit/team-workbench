"""Management API regression tests; temporary assets only, no network calls."""
import json
import test_asset_classification as fixture
HEADERS=fixture.HEADERS
from fastapi.testclient import TestClient
import asset_classification as classification
import unittest

class MaterialManagerTests(unittest.TestCase):
    setUp=fixture.ClassificationTests.setUp
    tearDown=fixture.ClassificationTests.tearDown
    upload=fixture.ClassificationTests.upload
    configure=fixture.ClassificationTests.configure
    state=fixture.ClassificationTests.state
    label=fixture.ClassificationTests.label

    def test_rename_keeps_ai_state_and_category_only_save(self):
        aid=self.upload();before=self.state(aid)
        r=self.client.post('/api/workspace/materials/'+aid,json={'name':'产品正面.png'},headers=HEADERS)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(self.state(aid),before)
        self.assertEqual(self.client.post('/api/workspace/materials/'+aid,json={'category':'product'},headers=HEADERS).status_code,200)
        row=self.client.get('/api/workspace/materials').json()[0]
        self.assertEqual((row['name'],row['category'],row['classification_status']),('产品正面.png','product','manual'))

    def test_explicit_ai_replaces_manual_classification(self):
        aid=self.upload();self.configure();self.label(aid)
        r=self.client.post('/api/workspace/materials/'+aid+'/classify',json={},headers=HEADERS)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['status'],'queued')
        classification.tick(self.hub,lambda _: 'product')
        self.assertEqual(self.client.get('/api/workspace/materials').json()[0]['category'],'product')

    def test_download_and_delete(self):
        aid=self.upload();self.client.post('/api/workspace/materials/'+aid,json={'name':'中文产品图.png'},headers=HEADERS)
        r=self.client.get('/api/assets/'+aid+'?download=1');self.assertEqual(r.status_code,200)
        self.assertIn('attachment;',r.headers['content-disposition']);self.assertIn("filename*=utf-8''",r.headers['content-disposition'])
        self.assertNotIn('content-disposition',self.client.get('/api/assets/'+aid).headers)
        r=self.client.post('/api/workspace/materials/'+aid+'/delete',json={},headers=HEADERS);self.assertEqual(r.status_code,200,r.text)
        self.assertFalse((self.hub.assets/aid).exists());self.assertEqual(self.client.get('/api/assets/'+aid).status_code,404)
        self.assertEqual(self.client.get('/api/workspace/materials').json(),[])
        self.assertEqual(self.client.post('/api/workspace/materials/'+aid+'/delete',json={},headers=HEADERS).status_code,404)
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM asset_classification WHERE asset_id=?',(aid,)).fetchone()[0],0)

    def test_video_upload_appears_and_previews_inline(self):
        payload=b'\x00\x00\x00\x18ftypisom'+b'fixture-video'
        r=self.client.post('/api/assets',content=payload,headers={**HEADERS,'Content-Type':'video/mp4','X-File-Name':'footage.mp4'})
        self.assertEqual(r.status_code,200,r.text)
        aid=r.json()['id']
        row=next(a for a in self.client.get('/api/workspace/materials').json() if a['id']==aid)
        self.assertEqual((row['name'],row['mime']),('footage.mp4','video/mp4'))
        preview=self.client.get('/api/assets/'+aid)
        self.assertEqual(preview.content,payload)
        self.assertNotIn('content-disposition',preview.headers)
        self.assertIn('attachment;',self.client.get('/api/assets/'+aid+'?download=1').headers['content-disposition'])

    def test_owner_scope_and_csrf(self):
        aid=self.upload();other=TestClient(self.app,base_url='http://127.0.0.1:8765')
        user=self.client.post('/api/users',json={'username':'member','password':'test-password-123456'},headers=HEADERS)
        self.assertEqual(user.status_code,200,user.text)
        other.post('/api/login',json={'username':'member','password':'test-password-123456'},headers=HEADERS).raise_for_status()
        other.post('/api/password',json={'old':'test-password-123456','new':'test-password-123456-new'},headers=HEADERS).raise_for_status()
        for route in ('/api/assets/'+aid+'?download=1','/api/workspace/materials/'+aid+'/delete'):
            r=other.get(route) if route.startswith('/api/assets') else other.post(route,json={},headers=HEADERS)
            self.assertEqual(r.status_code,404)
        self.assertEqual(self.client.post('/api/workspace/materials/'+aid+'/delete',json={}).status_code,403)
        other.close()

    def test_invalid_rename(self):
        aid=self.upload()
        for data in ({},{'name':''},{'name':'../bad'},{'name':'bad\\name'},{'name':'x\ny'},{'category':'video'}):
            self.assertEqual(self.client.post('/api/workspace/materials/'+aid,json=data,headers=HEADERS).status_code,400)

    def test_draft_references_block_delete(self):
        aid=self.upload()
        with self.hub.db() as db:
            owner=db.execute('SELECT owner FROM assets WHERE id=?',(aid,)).fetchone()[0]
            db.execute('INSERT INTO compositions VALUES(?,?,?)',(owner,json.dumps([{'assets':[{'id':aid}]}]),1))
        r=self.client.post('/api/workspace/materials/'+aid+'/delete',json={},headers=HEADERS)
        self.assertEqual(r.status_code,409,r.text);self.assertTrue((self.hub.assets/aid).exists())

    def test_deleted_during_ai_response_does_not_resurrect(self):
        aid=self.upload();self.configure()
        def recognize(_):
            r=self.client.post('/api/workspace/materials/'+aid+'/delete',json={},headers=HEADERS)
            self.assertEqual(r.status_code,200,r.text);return 'scene'
        classification.tick(self.hub,recognize)
        self.assertEqual(self.client.get('/api/workspace/materials').json(),[])

if __name__=='__main__':unittest.main()
