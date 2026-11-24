import asyncio,io,json,os,subprocess,sys,time,unittest,hashlib
from unittest.mock import patch,MagicMock
from fastapi import HTTPException
import test_hub as fixtures

class Tests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    def owner(self):return self.member.get('/api/me').json()['id']
    def voice_input(self):
        voice=self.hub.voice;voice.configure('admin',api_key='offline-only-fake-key',enabled=True)
        vid=voice.save_voice('admin',{'name':'Offline','reference_id':'fixture','language':'zh'})
        return voice,{'text':'original','voice_id':vid,'speed':1,'source':'manual'}
    def test_voice_request_signature_and_snapshot(self):
        voice,data=self.voice_input();uid=self.owner()
        first=voice.submit(uid,'round2-key',data)
        self.assertEqual(first['id'],voice.submit(uid,'round2-key',data)['id'])
        for k,v in [('text','changed'),('speed',1.2),('format','mp3'),('insert_at',1),('project_id','other'),('make_captions',False)]:
            with self.subTest(k=k),self.assertRaises(HTTPException) as caught:voice.submit(uid,'round2-key',{**data,k:v})
            self.assertEqual(caught.exception.status_code,409)
        with self.hub.db() as db:job=db.execute('SELECT * FROM voice_jobs WHERE id=?',(first['id'],)).fetchone()
        self.assertEqual(job['language'],'zh')
        import urllib.error
        request=[]
        def opened(req,**kw):request.append(json.loads(req.data));raise urllib.error.HTTPError('https://fixture',400,'bad',{},io.BytesIO(b'private secret do not echo'))
        with patch('voice_catalog.opener') as op:
            op.return_value.open.side_effect=opened
            with self.assertRaises(ValueError) as caught:voice._collect(job,'fake-key',job['text'])
        self.assertEqual(request[0]['language'],'zh');self.assertNotIn('private',str(caught.exception))
        with self.hub.db() as db:db.execute("UPDATE voice_jobs SET input_signature='' WHERE id=?",(first['id'],))
        with self.assertRaises(HTTPException):voice.submit(uid,'round2-key',data)
    def test_read_only_request_status_is_owner_scoped(self):
        voice,data=self.voice_input();first=voice.submit(self.owner(),'lookup-key',data)
        response=self.member.get('/api/voice/request-status?request_key=lookup-key')
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['job']['id'],first['id'])
        self.assertFalse(self.admin.get('/api/voice/request-status?request_key=lookup-key').json()['found'])
        self.assertFalse(self.member.get('/api/voice/request-status?request_key=not-found').json()['found'])
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM voice_jobs').fetchone()[0],1)

    def test_legacy_completed_parts_remain_unknown_after_migration(self):
        service,uid,eid,payload=self.prepare_upload()
        with self.hub.db() as db:db.execute("UPDATE feishu_uploads SET upload_id='old',block_num=1,next_part=1,state='attention',phase='' WHERE export_id=?",(eid,))
        from feishu_integration import Feishu
        Feishu(self.hub)
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT phase FROM feishu_uploads WHERE export_id=?',(eid,)).fetchone()[0],'finish_unknown')
        self.assertEqual(self.member.post('/api/feishu/uploads/'+eid+'/retry',json={},headers=fixtures.H).status_code,409)

    def test_stream_error_never_exposes_body(self):
        import fishaudio
        with self.assertRaises(fishaudio.StreamError) as caught:fishaudio.StreamCollector().feed_event({'error':'fake-secret-credential'})
        self.assertNotIn('fake-secret',str(caught.exception))
    def expire_link(self):
        service=self.hub.feishu;uid=self.owner()
        with self.hub.db() as db:
            db.execute('INSERT INTO feishu_config VALUES(1,?)',(service.pack({'app_id':'fake','app_secret':'fake'}),))
            db.execute('INSERT INTO feishu_links VALUES(?,?,?,?,?)',(uid,'fake-subject','fake',service.pack({'access_token':'old','refresh_token':'old-refresh'}),0))
        return service,uid
    def test_refresh_network_outside_write_lock_and_rotation_guard(self):
        service,uid=self.expire_link()
        def refresh(*a,**kw):
            with self.hub.db() as other:
                other.execute('PRAGMA busy_timeout=1');other.execute("UPDATE users SET username=username WHERE id=?",(uid,))
            with self.assertRaises(ValueError):service.token(uid)
            return {'access_token':'new','refresh_token':'rotated','expires_in':3600}
        with patch.object(service,'call',side_effect=refresh) as call:
            self.assertEqual(service.token(uid),'new');self.assertEqual(service.token(uid),'new');call.assert_called_once()
    def test_unknown_refresh_never_reuses_rotating_token(self):
        service,uid=self.expire_link()
        with patch.object(service,'call',side_effect=ValueError('network unknown')) as call:
            for _ in range(2):
                with self.assertRaises(ValueError):service.token(uid)
            call.assert_called_once()
    def prepare_upload(self):
        uid=self.owner();service=self.hub.feishu;eid='round2-export';now=time.time();payload=b'fixture-complete-file'
        (self.hub.directory/'edits'/(eid+'.mp4')).write_bytes(payload)
        with self.hub.db() as db:
            db.execute('INSERT INTO edit_exports(id,owner,project_id,body,state,created,updated,request_key) VALUES(?,?,?,?,?,?,?,?)',(eid,uid,'p',json.dumps({'export_name':'fixture'}),'ready',now,now,'round2-export-key'))
            db.execute('INSERT INTO feishu_uploads(export_id,owner,folder,day,state,created,updated) VALUES(?,?,?,?,?,?,?)',(eid,uid,'parent','261117','waiting',now,now))
        return service,uid,eid,payload
    def test_finish_unknown_blocks_repeat_and_allows_verified_association(self):
        service,uid,eid,payload=self.prepare_upload();calls=[]
        def call(path,*a,**kw):
            calls.append(path)
            if path.endswith('upload_prepare'):return {'upload_id':'old-upload','block_size':100,'block_num':1}
            if path.endswith('upload_part'):return {}
            if path.endswith('upload_finish'):raise ValueError('response lost')
            raise AssertionError(path)
        folders=[{'type':'folder','name':'261117','token':'day-folder'}]
        with patch.object(service,'token',return_value='fake'),patch.object(service,'list_folder',side_effect=lambda t,f:folders if f=='parent' else []),patch.object(service,'call',side_effect=call):service.tick()
        with self.hub.db() as db:job=dict(db.execute('SELECT * FROM feishu_uploads WHERE export_id=?',(eid,)).fetchone())
        self.assertEqual(job['phase'],'finish_unknown');self.assertEqual(job['state'],'attention')
        with patch.object(service,'call') as remote:
            with self.assertRaises(ValueError):service.upload(job)
            remote.assert_not_called()
        self.assertEqual(self.member.post('/api/feishu/uploads/'+eid+'/retry',json={},headers=fixtures.H).status_code,409)
        self.assertEqual(calls.count('drive/v1/files/upload_finish'),1)
        with patch.object(service,'verify_uploaded') as verify:
            denied=self.admin.post('/api/feishu/uploads/'+eid+'/associate',json={'file_token':'remote-file-token','confirm':True},headers=fixtures.H)
            self.assertEqual(denied.status_code,409);verify.assert_not_called()
            response=self.member.post('/api/feishu/uploads/'+eid+'/associate',json={'file_token':'remote-file-token','confirm':True},headers=fixtures.H)
            self.assertEqual(response.status_code,200,response.text);verify.assert_called_once()
    def test_remote_association_requires_exact_bytes(self):
        service,uid,eid,payload=self.prepare_upload()
        job={'owner':uid,'target_folder':'folder','remote_name':'fixture.mp4','local_size':len(payload),'local_sha256':hashlib.sha256(payload).hexdigest()}
        for raw,okay in [(payload,True),(b'wrong',False)]:
            response=MagicMock();response.status_code=200;response.iter_bytes.return_value=[raw]
            with patch.object(service,'token',return_value='fake'),patch.object(service,'list_folder',return_value=[{'token':'fid','type':'file','name':'fixture.mp4'}]),patch('feishu_integration.httpx.Client') as client:
                client.return_value.__enter__.return_value.stream.return_value.__enter__.return_value=response
                if okay:service.verify_uploaded(job,'fid')
                else:
                    with self.assertRaises(ValueError):service.verify_uploaded(job,'fid')

class CliTests(unittest.TestCase):
    def test_every_operation_has_timeout_and_no_mutation_retry(self):
        import libtv_gateway as g
        for args,budget in [(['account','list'],30),(['model','x'],60),(['project','create','x'],60),(['node','x','--run'],900),(['download'],180),(['upload'],180)]:
            with patch('libtv_gateway.shutil.which',return_value='fake.exe'),patch('libtv_gateway.profile_environment',return_value={}),patch('libtv_gateway.run_bounded',return_value=subprocess.CompletedProcess([],0,b'{}',b'')) as run:
                g.cli(args,'.');self.assertEqual(run.call_args.kwargs['timeout'],budget);run.assert_called_once()
        with patch('libtv_gateway.shutil.which',return_value='fake.exe'),patch('libtv_gateway.profile_environment',return_value={}),patch('libtv_gateway.run_bounded',side_effect=subprocess.TimeoutExpired('fake',900)) as run:
            with self.assertRaises(RuntimeError) as caught:g.cli(['node','x','--run'],'.')
            self.assertIn('未知',str(caught.exception));run.assert_called_once()
    def test_full_execution_capacity_rejects_without_queue(self):
        import libtv_gateway as g
        slots=[]
        try:
            for _ in range(g.MAX_WORKERS):self.assertTrue(g._EXECUTION_SLOTS.acquire(False));slots.append(1)
            with self.assertRaises(HTTPException) as caught:asyncio.run(g.execute_bounded(lambda:None))
            self.assertEqual(caught.exception.status_code,429)
        finally:
            for _ in slots:g._EXECUTION_SLOTS.release()
    def test_real_child_timeout(self):
        from bounded_process import run
        before=time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):run([sys.executable,'-c','import threading;threading.Event().wait(60)'],timeout=.2,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertLess(time.monotonic()-before,10)
