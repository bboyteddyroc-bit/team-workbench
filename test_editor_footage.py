import shutil, unittest
from editor import run, probe
from test_editor import EditorTests
from test_hub import H

class FootageTests(unittest.TestCase):
    setUp=EditorTests.setUp
    tearDown=EditorTests.tearDown
    login=EditorTests.login
    account=EditorTests.account
    enqueue=EditorTests.enqueue
    sample=EditorTests.sample

    def upload(self,content,name='phone.mp4',client=None):
        return (client or self.member).post('/api/editor/footage',content=content,headers={**H,'Content-Type':'application/octet-stream','X-File-Name':name})

    def test_import_private_mix_save_and_export(self):
        ai=self.sample();content=(self.hub.media/(ai+'.mp4')).read_bytes()
        response=self.upload(content);self.assertEqual(response.status_code,200,response.text)
        fid=response.json()['id'];self.assertEqual(self.admin.get('/api/tasks/'+fid+'/video').status_code,404)
        self.assertEqual(self.member.get('/api/tasks/'+fid+'/video').content,content)
        library=self.member.get('/api/editor/library').json()['items'];self.assertEqual(next(x for x in library if x['id']==fid)['kind'],'footage')
        self.assertNotIn(fid,self.member.get('/api/assets').text)
        self.assertEqual(self.member.get('/api/editor/thumbnail/'+fid).status_code,200)
        data={'title':'实拍与AI混剪','body':{'ratio':'9:16','clips':[{'task_id':fid,'start':0,'end':0.5,'volume':1},{'task_id':ai,'start':0,'end':0.5,'volume':1}],'captions':[]}}
        saved=self.member.post('/api/editor/projects',json=data,headers=H);self.assertEqual(saved.status_code,200,saved.text);project=saved.json()
        self.assertEqual(len(project['body']['clips']),2);self.assertGreater(project['created'],0)
        listed=self.member.get('/api/editor/projects').json();self.assertEqual(listed[0]['created'],project['created'])
        job=self.member.post('/api/editor/projects/'+project['id']+'/export',json={'version':project['version'],'request_key':'footage-mixed-export-001'},headers=H)
        self.assertEqual(job.status_code,200,job.text);eid=job.json()['id'];self.app.state.editor.tick()
        item=next(x for x in self.member.get('/api/editor/exports').json() if x['id']==eid);self.assertEqual(item['state'],'ready',item)
        duration,streams=probe(self.app.state.editor.root/(eid+'.mp4'));self.assertGreater(duration,.9);self.assertTrue(any(x['codec_type']=='video' for x in streams))

    def test_reject_invalid_and_cleanup(self):
        response=self.upload(b'not a video');self.assertEqual(response.status_code,400,response.text)
        # Date buckets can remain; no uploaded file or staging file may remain.
        self.assertFalse(any(p.is_file() for p in self.app.state.editor.footage.rglob('*')))
        self.assertEqual(self.upload(b'anything','bad.exe').status_code,400)
        self.assertEqual(self.member.post('/api/editor/footage',content=b'x',headers={'X-File-Name':'a.mp4'}).status_code,403)
