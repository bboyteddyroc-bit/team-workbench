import io,json,unittest
from pathlib import Path
from unittest.mock import patch
import test_hub as fixtures

class LibTVTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    def post(self,c,path,data):return c.post('/api/libtv'+path,json=data,headers=fixtures.H)
    def test_shared_generation_private_results(self):
        calls=[]
        def fake(args,cwd):
            calls.append(args)
            if args[0]=='account':return {'accounts':[{'accountId':42,'isActive':True}]}
            if args[0]=='model':return {'schema':{'modelKey':args[1],'modelName':'StarVideo 2.0'}}
            if args[0]=='project':return {'projectMeta':{'uuid':'a'*32}}
            if args[0]=='node' and len(args)>1 and args[1]=='成片' and '--run' not in args:return {'data':{'url':['https://example.test/video.mp4']}}
            if args[0]=='download':(Path(args[-1])/'result.mp4').write_bytes(b'video')
            return {'ok':True}
        with patch('libtv_gateway.cli',side_effect=fake),patch('editor.probe',return_value=(5,[{'codec_type':'video'}])):
            self.assertEqual(self.post(self.member,'/connect',{}).status_code,403)
            self.assertEqual(self.post(self.admin,'/connect',{}).status_code,200)
            payload={'prompt':'hello','duration':5,'request_key':'libtv-test-request-001'}
            result=self.post(self.member,'/jobs',payload)
            self.assertEqual(result.status_code,200,result.text)
            data=result.json();jid=data['id'];asset=data['asset_id']
            self.assertEqual(self.post(self.member,'/jobs',payload).json()['id'],jid)
            self.assertEqual(sum('--run' in a for a in calls),1)
            create=next(a for a in calls if a[:2]==['node','create'])
            self.assertNotIn('--run',create)
            self.assertIn('model=Seedance 2.0 VIP',create)
            run=next(a for a in calls if '--run' in a)
            self.assertEqual(run,['node','成片','-p','a'*32,'--run'])
            self.assertEqual(self.admin.get('/api/libtv/jobs').json(),[])
            self.assertEqual(self.admin.get('/api/assets/'+asset).status_code,404)
            self.assertEqual(self.admin.get('/api/tasks/'+jid+'/video').status_code,404)
            self.assertEqual(self.member.get('/api/tasks/'+jid+'/video').status_code,200)
            self.assertIn(jid,[i['id'] for i in self.member.get('/api/editor/library').json()['items']])
            self.assertEqual(self.post(self.admin,'/jobs/'+jid+'/recover',{}).status_code,404)
            self.assertEqual(self.post(self.member,'/jobs',{**payload,'prompt':'changed'}).status_code,409)
            self.assertEqual(self.post(self.member,'/jobs',{**payload,'request_key':'libtv-other-request','assets':[{'id':'not-owned'}]}).status_code,404)
    def test_failure_never_retries(self):
        with self.hub.db() as db:db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        with patch('libtv_gateway.cli',side_effect=RuntimeError('offline')) as mock:
            payload={'prompt':'test','request_key':'libtv-failure-request'}
            self.assertEqual(self.post(self.member,'/jobs',payload).status_code,502)
            self.assertEqual(self.post(self.member,'/jobs',payload).json()['state'],'attention')
            self.assertEqual(mock.call_count,1)

    def test_model_resolution_validation(self):
        with self.hub.db() as db:db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        for model in ('star-video2','star-video2-fast','star-video2-mini'):
            with patch('libtv_gateway.cli',side_effect=RuntimeError('offline')) as mock:
                data={'prompt':'test','request_key':'request-'+model+'-720p','model':model,'resolution':'720p'}
                self.assertEqual(self.post(self.member,'/jobs',data).status_code,502)
                self.assertEqual(mock.call_count,1)
        with patch('libtv_gateway.cli') as mock:
            for model in ('star-video2-fast','star-video2-mini','star-video2.5'):
                self.assertEqual(self.post(self.member,'/jobs',{'prompt':'test','request_key':'invalid-model-test','model':model,'resolution':'1080p'}).status_code,400)
            mock.assert_not_called()

    def test_magi_30_second_draft_and_generation(self):
        with self.hub.db() as db:
            db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        payload={'prompt':'A short product demo','duration':30,'model':'magi-2','request_key':'magi-30-second-draft'}
        draft={**payload,'model':'auto','libtv_model':'magi-2','libtv_resolution':'1080p'}
        saved=self.member.post('/api/compositions',json={'items':[draft]},headers=fixtures.H)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(self.member.get('/api/compositions').json()['items'][0]['duration'],30)
        calls=[]
        def fake(args,cwd):
            calls.append(args)
            if args[0]=='account':return {'accounts':[{'accountId':42,'isActive':True}]}
            if args[0]=='model':return {'schema':{'modelKey':'magi-2'}}
            if args[0]=='project':return {'projectMeta':{'uuid':'b'*32}}
            if args[:2]==['node','成片'] and '--run' not in args:return {'data':{'url':['https://example.test/magi.mp4']}}
            if args[0]=='download':(Path(args[-1])/'magi.mp4').write_bytes(b'video')
            return {'ok':True}
        with patch('libtv_gateway.cli',side_effect=fake),patch('editor.probe',return_value=(30,[{'codec_type':'video'}])):
            for invalid in ({'resolution':'720p'},{'duration':31},{'mode':'frames'}):
                self.assertEqual(self.post(self.member,'/jobs',{**payload,**invalid}).status_code,400)
            self.assertFalse(calls)
            result=self.post(self.member,'/jobs',payload)
            self.assertEqual(result.status_code,200,result.text)
        create=next(args for args in calls if args[:2]==['node','create'])
        for expected in ('model=MAGI-2','duration=30','resolution=1080p','modeType=text2video'):
            self.assertIn(expected,create)
        self.assertEqual(sum('--run' in args for args in calls),1)

    def test_shared_account_generates_in_parallel(self):
        """中台的意义就是大家同时出片：别人正在生成时，任何人不该被拦住。"""
        with self.hub.db() as db:
            db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
            db.execute("INSERT INTO libtv_jobs(id,owner,request_key,payload,state,created,updated) VALUES(?,?,?,?,?,?,?)",
                       ('busy-job-0001','colleague','busy-request-1','{}','running',1,1))
        with patch('libtv_gateway.cli',side_effect=RuntimeError('offline')):
            result=self.post(self.member,'/jobs',{'prompt':'parallel','request_key':'parallel-request-1'})
        self.assertEqual(result.status_code,502,result.text)
        self.assertNotIn('正在生成，请等待',result.text)

    def test_operator_cap_queues_only_when_configured(self):
        """并发上限只由管理员显式设置（LIBTV_MAX_CONCURRENT），默认不限。"""
        with self.hub.db() as db:
            db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
            db.execute("INSERT INTO libtv_jobs(id,owner,request_key,payload,state,created,updated) VALUES(?,?,?,?,?,?,?)",
                       ('busy-job-0002','colleague','busy-request-2','{}','running',1,1))
        with patch('libtv_gateway.CONCURRENCY_CAP',1),patch('libtv_gateway.cli') as mock:
            result=self.post(self.member,'/jobs',{'prompt':'capped','request_key':'cap-request-0001'})
            self.assertEqual(result.status_code,429,result.text)
            self.assertIn('并发上限 1',result.text)
            mock.assert_not_called()

    def test_generation_runs_off_the_shared_api_pool(self):
        """30 条以上同时出片：生成占 LibTV 自己的线程池，数据库开 WAL，别把普通接口拖死。"""
        import concurrent.futures, libtv_gateway
        self.assertIsInstance(libtv_gateway.GENERATIONS,concurrent.futures.ThreadPoolExecutor)
        self.assertGreaterEqual(libtv_gateway.MAX_WORKERS,32)
        with self.hub.db() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0].lower(),'wal')
