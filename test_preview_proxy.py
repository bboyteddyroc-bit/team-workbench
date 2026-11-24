import hashlib
import os
import shutil
import unittest
from unittest.mock import patch

from editor import run, _probe_uncached
from test_editor_footage import FootageTests
from test_hub import H


@unittest.skipUnless(os.name == 'nt' and shutil.which('ffmpeg'), 'Windows/FFmpeg required')
class PreviewProxyTests(unittest.TestCase):
    setUp = FootageTests.setUp
    tearDown = FootageTests.tearDown
    login = FootageTests.login
    account = FootageTests.account
    enqueue = FootageTests.enqueue
    sample = FootageTests.sample
    upload = FootageTests.upload

    def test_recover_crashed_worker_before_export_claim(self):
        import subprocess
        import sys
        from editor_proxy_claims import enqueue, claim_next, claim_export
        e = self.app.state.editor
        key = 'a'*64
        with self.hub.db() as db:
            enqueue(db,key)
            _, token = claim_next(db)
        code = ('import os,sys; from editor_proxy_winjob import OwnedJob; '
                'j=OwnedJob([sys.executable,"-c","import time; time.sleep(30)"],sys.argv[1]); '
                'os._exit(42)')
        owner = subprocess.run([sys.executable,'-B','-c',code,token],timeout=10)
        self.assertEqual(owner.returncode,42)
        with self.hub.db() as db:
            owner_id=db.execute("SELECT id FROM users WHERE username='member'").fetchone()[0]
            db.execute("INSERT INTO edit_exports(id,owner,project_id,body,state,created,updated,request_key) VALUES ('e',?,'p','{}','queued',0,0,'r')",(owner_id,))
        with self.hub.db() as db:self.assertIsNone(claim_export(db))
        self.assertTrue(e.proxies.recover())
        with self.hub.db() as db:
            self.assertEqual(claim_export(db)['id'],'e')
            self.assertEqual(db.execute('SELECT state FROM preview_proxy_jobs WHERE cache_key=?',(key,)).fetchone()[0],'failed')

    def test_authorized_proxy_and_original_mixed_export(self):
        e = self.app.state.editor
        e.proxies.enabled = True
        light = self.sample()
        source = self.hub.directory/'synthetic.mp4'
        run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc2=size=3840x2160:rate=60:duration=0.5','-c:v','libx264','-preset','ultrafast','-threads','2','-pix_fmt','yuv420p',str(source)])
        upload = self.upload(source.read_bytes())
        self.assertEqual(upload.status_code,200,upload.text)
        task = upload.json()['id']
        base = '/api/editor/preview-proxy/'
        status = lambda id: self.member.post(base+id,headers=H).json()
        self.assertEqual(self.admin.post(base+task,headers=H).status_code,404)
        self.assertEqual(status(light)['state'],'pending')
        e.proxies.tick()
        self.assertEqual(status(light)['state'],'original')
        self.assertEqual(status(task)['state'],'pending')
        e.proxies.tick()
        ready = status(task)
        self.assertEqual(ready['state'],'ready',ready)
        url = base+task+'/'+ready['version']
        self.assertEqual(self.admin.get(url).status_code,404)
        self.assertEqual(self.member.get(url,headers={'Range':'bytes=0-31'}).status_code,206)
        proxy = e.proxies.root/(ready['version']+'.mp4')
        _, streams = _probe_uncached(proxy)
        v = streams[0]
        self.assertEqual((v['width'],v['height'],v['avg_frame_rate']),(1280,720,'30/1'))
        original = self.member.get('/api/tasks/'+task+'/video').content
        self.assertEqual(hashlib.sha256(original).digest(),hashlib.sha256(source.read_bytes()).digest())
        data={'title':'Proxy regression','body':{'ratio':'16:9','clips':[{'task_id':x,'start':0,'end':0.4,'volume':0} for x in (light,task)]}}
        saved=self.member.post('/api/editor/projects',json=data,headers=H)
        self.assertEqual(saved.status_code,200,saved.text)
        project=saved.json()
        job=self.member.post('/api/editor/projects/'+project['id']+'/export',json={'version':project['version'],'request_key':'proxy-isolation-regression'},headers=H)
        self.assertEqual(job.status_code,200,job.text)
        # Export must work even if the cached preview is deliberately unreadable.
        proxy.write_bytes(b'not a video')
        from editor_proxy_claims import enqueue
        with self.hub.db() as db:enqueue(db,'b'*64)
        with patch.object(e.proxies,'probe',side_effect=AssertionError('proxy work started before queued export')) as probe:
            e.proxies.tick()
        probe.assert_not_called()
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT state FROM preview_proxy_jobs WHERE cache_key=?',('b'*64,)).fetchone()[0],'queued')
        with patch.object(e.proxies,'file',side_effect=AssertionError('export touched preview')):
            e.tick()
        _, streams = _probe_uncached(e.root/(job.json()['id']+'.mp4'))
        v=streams[0]
        self.assertEqual((v['width'],v['height'],v['avg_frame_rate']),(1920,1080,'30/1'))
        with self.hub.db() as db:
            row=db.execute('SELECT created,id FROM edit_footage WHERE id=?',(task,)).fetchone()
        e.footage_path(row).write_bytes(b'changed source')
        self.assertEqual(self.member.get(url).status_code,404)
