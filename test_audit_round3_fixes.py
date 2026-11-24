"""Offline contracts for third audit repairs. No production state or paid calls."""
import ast
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import test_hub as fixture
from task_signature import signature


class QueueTests(unittest.TestCase):
    setUp = fixture.HubTests.setUp
    tearDown = fixture.HubTests.tearDown
    login = fixture.HubTests.login
    account = fixture.HubTests.account
    enqueue = fixture.HubTests.enqueue

    def test_identical_and_changed_inputs(self):
        aid=self.account(self.admin)
        data={'request_key':'audit-third-request-0001','account_id':aid,'prompt':'hello'}
        first=self.member.post('/api/tasks',json=data,headers=fixture.H)
        self.assertEqual(first.status_code,200,first.text)
        equivalent={**data,'duration':5,'count':1,'model':'auto','mode':'omni','assets':[]}
        self.assertEqual(self.member.post('/api/tasks',json=equivalent,headers=fixture.H).json(),first.json())
        for change in [{'prompt':'different'},{'duration':6},{'count':2},{'project_id':'different'},{'account_id':'pool'}]:
            r=self.member.post('/api/tasks',json={**data,**change},headers=fixture.H)
            self.assertEqual(r.status_code,409,(change,r.text))
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)
        self.assertEqual(len(self.provider.created),0)

    def test_batch_signature_owner_and_legacy(self):
        aid=self.account(self.admin);key='audit-third-batch-0001'
        data={'request_key':key,'account_id':aid,'items':[{'prompt':'one'},{'prompt':'two','count':2}]}
        first=self.member.post('/api/tasks',json=data,headers=fixture.H)
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(len(first.json()['ids']),3)
        self.assertEqual(self.member.post('/api/tasks',json=data,headers=fixture.H).json(),first.json())
        changed={**data,'items':list(reversed(data['items']))}
        self.assertEqual(self.member.post('/api/tasks',json=changed,headers=fixture.H).status_code,409)
        self.assertEqual(self.admin.post('/api/tasks',json=data,headers=fixture.H).status_code,200)
        with self.hub.db() as db:db.execute('DELETE FROM task_requests')
        self.assertEqual(self.member.post('/api/tasks',json=data,headers=fixture.H).status_code,409)

    def test_signature_covers_assets_continuation_and_unknown(self):
        data={'request_key':'long-enough-request','prompt':'x','assets':[{'id':'a','token':'图片1'},{'id':'b'}], 'continuation':{'source_id':'c','append_timeline':False}}
        original=signature(data)
        for field,value in [('assets',list(reversed(data['assets']))),('continuation',{'source_id':'d','append_timeline':False}),('future_option',True)]:
            self.assertNotEqual(signature({**data,field:value}),original)
        self.assertEqual(signature({**data,'request_key':'other-key-long-enough'}),original)

    def test_concurrent_same_submission_once(self):
        aid=self.account(self.admin)
        data={'request_key':'third-concurrent-0001','account_id':aid,'prompt':'one'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:self.member.post('/api/tasks',json=data,headers=fixture.H),range(2)))
        self.assertTrue(all(r.status_code==200 for r in responses))
        self.assertEqual(responses[0].json(),responses[1].json())
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:self.hub.tick(),range(2)))
        self.assertEqual(len(self.provider.created),1)


class BindingTests(unittest.TestCase):
    def test_revoke_during_token_exchange_rejected(self):
        from test_feishu_integration import Tests, BASE, H
        from fastapi.testclient import TestClient
        f=Tests();f.setUp()
        try:
            r=f.b.get('/api/feishu/start?mode=bind',follow_redirects=False)
            state=parse_qs(urlsplit(r.headers['location']).query)['state'][0]
            entered=threading.Event();release=threading.Event()
            def call(path,*a,**kw):
                if path.endswith('/oauth/token'):
                    entered.set()
                    if not release.wait(10):raise RuntimeError('test deadline')
                    return {'access_token':'fake','refresh_token':'fake','expires_in':3600}
                return {'open_id':'offline-audit-subject','name':'offline'}
            with patch.object(f.f,'call',side_effect=call):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending=pool.submit(f.b.get,'/api/feishu/callback',params={'state':state,'code':'fake'},follow_redirects=False)
                    try:
                        self.assertTrue(entered.wait(10))
                        with TestClient(f.app,base_url=BASE) as other:
                            other.cookies.update(f.b.cookies)
                            self.assertEqual(other.post('/api/logout',headers=H).status_code,200)
                    finally:release.set()
                    response=pending.result(15)
            self.assertEqual(response.status_code,400,response.text)
            self.assertNotIn('hub_session=',response.headers.get('set-cookie',''))
            with f.hub.db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE user_id='bob'").fetchone()[0],0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM feishu_links WHERE owner='bob'").fetchone()[0],0)
        finally:f.tearDown()


class ContinuationAndArchive(unittest.TestCase):
    setUp = QueueTests.setUp
    tearDown = QueueTests.tearDown
    login = QueueTests.login
    account = QueueTests.account
    enqueue = QueueTests.enqueue

    def make_ready(self,body):
        uid=self.member.get('/api/me').json()['id'];aid=self.account(self.admin)
        jid=self.enqueue(self.member,aid,'third-multitrack-0001').json()['id'];now=time.time()
        with self.hub.db() as db:
            db.execute('INSERT INTO edit_projects VALUES(?,?,?,?,?,?)',('p',uid,'audit',json.dumps(body),1,now))
            db.execute("UPDATE tasks SET state='ready',config=? WHERE id=?",(json.dumps({'continuation':{'append_timeline':True}}),jid))
            db.execute('INSERT INTO project_tasks VALUES(?,?,?,?)',('p',jid,uid,now))
        return jid

    def test_append_multitrack_gap_speed_and_idempotency(self):
        from workspace import append_completed
        from editor import timeline_duration
        body={'schema_version':4,'clips':[{'task_id':'old','start':0,'end':10,'at':10,'track':'v','speed':2,'volume':1}],
              'captions':[{'start':0,'end':17,'text':'caption','track':'c'}], 'audio_clips':[], 'stickers':[],
              'tracks':[{'id':'v','muted':False},{'id':'c','muted':False}], 'main_track':'v', 'export_range':{'start':1,'end':3}}
        jid=self.make_ready(body)
        with patch('editor.probe',return_value=(4,[])):append_completed(self.hub,jid);append_completed(self.hub,jid)
        with self.hub.db() as db:
            row=db.execute("SELECT body,version FROM edit_projects WHERE id='p'").fetchone()
            saved=json.loads(row['body']);self.assertEqual(row['version'],2)
            self.assertEqual(db.execute('SELECT state FROM continuation_results').fetchone()[0],'applied')
        self.assertEqual(saved['clips'][-1]['at'],17)
        self.assertEqual(saved['clips'][-1]['track'],'v')
        self.assertEqual(timeline_duration(saved),21)
        self.assertEqual(saved['clips'][0],{**body['clips'][0],'audio_detached':False})
        self.assertEqual(saved['export_range'],body['export_range'])
        self.assertEqual(saved['captions'],body['captions'])

    def test_append_legacy_upgrades_and_limit(self):
        from workspace import append_completed
        jid=self.make_ready({'clips':[{'task_id':'old','start':0,'end':10,'speed':2,'volume':1}], 'captions':[],'audio_clips':[]})
        with patch('editor.probe',return_value=(4,[])):append_completed(self.hub,jid)
        with self.hub.db() as db:saved=json.loads(db.execute("SELECT body FROM edit_projects WHERE id='p'").fetchone()[0])
        self.assertEqual(saved['schema_version'],4)
        self.assertEqual([c['at'] for c in saved['clips']],[0,5])
        self.assertTrue(all(c['track']=='video-main' for c in saved['clips']))

    def test_legacy_filename_cannot_confirm_or_upload(self):
        hub=self.hub;uid=self.member.get('/api/me').json()['id'];now=time.time()
        with hub.db() as db:
            db.execute('INSERT INTO edit_exports(id,owner,project_id,body,state,created,updated,request_key) VALUES(?,?,?,?,?,?,?,?)',('exp',uid,'p',json.dumps({'export_name':'audit'}),'ready',now,now,'archive-key'))
            db.execute('INSERT INTO feishu_uploads(export_id,owner,folder,day,state,created,updated) VALUES(?,?,?,?,?,?,?)',('exp',uid,'root','261117','waiting',now,now))
        service=hub.feishu
        with patch.object(service,'token',return_value='fake'),patch.object(service,'list_folder',side_effect=[[{'type':'folder','name':'261117','token':'day'}],[{'type':'file','name':'audit_exp.mp4','token':'wrong'}]]),patch.object(service,'call') as remote:
            service.tick();remote.assert_not_called()
        with hub.db() as db:row=db.execute('SELECT state,file_token,phase FROM feishu_uploads').fetchone()
        self.assertEqual(row['state'],'attention');self.assertFalse(row['file_token']);self.assertNotEqual(row['phase'],'confirmed')


class WorkerTests(unittest.TestCase):
    def test_lease_retained_until_actual_exit(self):
        from worker_lifecycle import drain_workers
        entered=threading.Event();release=threading.Event();stop=threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'worker.lock';lease=path.open('a+b');lease.write(b'0');lease.flush();lease.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(lease.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            def run():entered.set();release.wait(10)
            thread=threading.Thread(target=run);thread.start();self.assertTrue(entered.wait(2))
            drain=None
            try:
                drain=drain_workers(stop,[thread],lease,timeout=.01)
                self.assertTrue(stop.is_set());self.assertTrue(thread.is_alive());self.assertFalse(lease.closed)
                with path.open('a+b') as other:
                    if os.name=='nt':
                        other.seek(0)
                        with self.assertRaises(OSError):msvcrt.locking(other.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        with self.assertRaises(OSError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:
                release.set();thread.join(3)
                if drain:drain.join(3)
            self.assertTrue(lease.closed)

    def test_startup_failure_drains_and_releases_lock(self):
        import app
        real_thread=threading.Thread
        with tempfile.TemporaryDirectory() as folder:
            application=app.create_app(folder,fixture.FakeProvider(),worker=True)
            def factory(*args,**kwargs):
                kwargs['target']=lambda *a,**k:None
                return real_thread(*args,**kwargs)
            async def run():
                with patch('app.threading.Thread',side_effect=factory),patch.object(application.state.editor,'recover',side_effect=RuntimeError('offline startup fault')):
                    with self.assertRaisesRegex(RuntimeError,'offline startup fault'):
                        async with application.router.lifespan_context(application):pass
            asyncio.run(run())
            self.assertTrue(application.state.hub.stop.is_set())
            with (Path(folder)/'worker.lock').open('a+b') as lock:
                if os.name=='nt':
                    import msvcrt
                    lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_lan_honors_worker_zero_without_socket(self):
        import argparse
        import app
        import uvicorn
        module=ast.parse((Path(__file__).parent/'lan.py').read_text(encoding='utf-8-sig'))
        main=next(n for n in module.body if isinstance(n,ast.If) and '__name__' in ast.unparse(n.test))
        with patch.dict(os.environ,{'HUB_WORKER':'0'}),patch.object(app,'create_app',return_value=object()) as create,patch.object(uvicorn,'run'),patch.object(Path,'exists',return_value=True),patch('sys.argv',['lan.py','--host','192.0.2.10']):
            exec(compile(ast.Module(body=main.body,type_ignores=[]),'lan-entry','exec'),{'argparse':argparse,'os':os,'ROOT':Path(__file__).parent})
            create.assert_called_once_with(worker=False)


if __name__=='__main__':unittest.main()
