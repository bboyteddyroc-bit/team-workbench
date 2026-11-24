import json,time,sqlite3,unittest
from unittest.mock import patch
import test_kalodata_integration as fixture
from video_cases import initialize
from kalodata_integration import QueryError
from video_case_recovery import defer,DELAYS
from video_case_fields import projection,ai_plan

class RecoveryTests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    base='/api/intelligence/cases'
    def job(self):
        cid=self.a.post(self.base,headers=fixture.HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789']}).json()['items'][0]['id']
        with patch('asr.configured_key',return_value='fake'):
            r=self.a.post(self.base+'/'+cid+'/process',headers=fixture.HEADERS,json={'kind':'analysis','confirm':True,'request_key':'recovery-test-key'})
        self.assertEqual(r.status_code,200,r.text)
        return cid,r.json()['id']
    def row(self,jid):
        with self.hub.db() as db:return dict(db.execute('SELECT * FROM video_case_jobs WHERE id=?',(jid,)).fetchone())
    def test_1054_wait_restart_due_then_success_no_early_replay(self):
        cid,jid=self.job();svc=self.app.state.video_cases
        error=QueryError('cached wait',code=1054,endpoint='/video/url')
        with patch('asr.configured_key',return_value='fake'),patch.object(svc.kalodata,'post',side_effect=error) as upstream,patch('video_case_analysis.request') as ai:
            svc.tick();r=self.row(jid);self.assertEqual(r['state'],'waiting');self.assertEqual(r['wait_count'],1)
            self.assertAlmostEqual(r['next_attempt']-r['updated'],60)
            svc.recover();svc.tick();self.assertEqual(self.row(jid)['state'],'waiting');self.assertEqual(upstream.call_count,1);ai.assert_not_called()
        # New request key must re-use waiting job, not create a second paid chain.
        with patch('asr.configured_key',return_value='fake'):
            repeat=self.a.post(self.base+'/'+cid+'/process',headers=fixture.HEADERS,json={'kind':'analysis','confirm':True,'request_key':'different-key'}).json()
        self.assertEqual(repeat['id'],jid)
        with self.hub.db() as db:db.execute('UPDATE video_case_jobs SET next_attempt=? WHERE id=?',(time.time()-1,jid))
        with patch.object(svc,'analysis') as analyze:svc.tick();svc.tick();self.assertEqual(analyze.call_count,1)
        self.assertEqual(self.row(jid)['state'],'ready');self.assertIsNone(self.row(jid)['next_attempt'])
    def test_bounds_deadline_and_migration_are_persistent(self):
        cid,jid=self.job();now=10000
        with self.hub.db() as db:
            for index,delay in enumerate(DELAYS):
                self.assertTrue(defer(db,jid,now));r=db.execute('SELECT * FROM video_case_jobs WHERE id=?',(jid,)).fetchone();self.assertEqual(r['next_attempt'],now+delay);now+=delay
            self.assertFalse(defer(db,jid,now));self.assertEqual(db.execute('SELECT state FROM video_case_jobs WHERE id=?',(jid,)).fetchone()[0],'attention')
        initialize(self.hub);self.assertEqual(self.row(jid)['wait_count'],6)
        with self.hub.db() as db:
            db.execute("UPDATE video_case_jobs SET state='waiting',next_attempt=?,wait_deadline=? WHERE id=?",(time.time()-1,time.time()-1,jid))
        with patch.object(self.app.state.video_cases,'analysis') as analyze:self.app.state.video_cases.tick();analyze.assert_not_called()
        self.assertEqual(self.row(jid)['state'],'attention')
    def test_1053_unknown_timeout_not_found_do_not_wait_or_replay(self):
        cid,jid=self.job();svc=self.app.state.video_cases
        for error in (QueryError('1053',code=1053,endpoint='/video/url'),QueryError('not found',endpoint='/video/detail'),QueryError('network outcome unknown'),TimeoutError()):
            with self.hub.db() as db:db.execute("UPDATE video_case_jobs SET state='queued' WHERE id=?",(jid,))
            with patch.object(svc,'analysis',side_effect=error) as analyze:svc.tick();svc.tick();svc.recover();svc.tick();self.assertEqual(analyze.call_count,1)
            self.assertEqual(self.row(jid)['state'],'attention')
    def test_wait_cancel_owner_only_and_no_submit_after_cancel(self):
        cid,jid=self.job()
        with self.hub.db() as db:defer(db,jid)
        path=self.base+'/'+cid+'/jobs/'+jid+'/cancel-wait'
        self.assertEqual(self.b.post(path,headers=fixture.HEADERS,json={}).status_code,404)
        self.assertEqual(self.a.post(path,json={}).status_code,403)
        self.assertEqual(self.a.post(path,headers=fixture.HEADERS,json={}).status_code,200)
        self.assertEqual(self.a.post(path,headers=fixture.HEADERS,json={}).status_code,200)
        with patch.object(self.app.state.video_cases,'analysis') as analyze:self.app.state.video_cases.tick();analyze.assert_not_called()
        self.assertEqual(self.row(jid)['state'],'cancelled')
    def test_unique_waiting_index_and_exclusive_claim(self):
        cid,jid=self.job();svc=self.app.state.video_cases
        with self.hub.db() as db:
            defer(db,jid)
            with self.assertRaises(sqlite3.IntegrityError):db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated) VALUES('dup',?,'alice','analysis','queued','dup-key',0,0)",(cid,))
            db.execute('UPDATE video_case_jobs SET next_attempt=? WHERE id=?',(time.time()-1,jid))
        calls=[]
        def nested(job,case):calls.append(job['id']);svc.tick()
        with patch.object(svc,'analysis',side_effect=nested):svc.tick()
        self.assertEqual(calls,[jid])
    def test_api_field_priority_and_ai_plan_respect_explicit_clear(self):
        cid,jid=self.job()
        source={'title':'old public','kalodata':{'title':'provider title','handle':'demo','period_views':0}}
        human={'summary':'','category':'human category'};ai={'fields':{'summary':'AI summary','product_category':'AI category','title':'fake','merchant_visible':'fake'}}
        with self.hub.db() as db:db.execute('UPDATE video_cases SET source=?,human=?,ai=? WHERE id=?',(json.dumps(source),json.dumps(human),json.dumps(ai),cid))
        row=self.a.get(self.base+'/'+cid).json();fields=row['fields']
        self.assertEqual(fields['title']['value'],'provider title');self.assertEqual(fields['title']['source'],'Kalodata')
        self.assertEqual(fields['summary']['value'],'');self.assertEqual(fields['category']['value'],'human category');self.assertEqual(fields['merchant_visible']['value'],'')
        facts,missing=ai_plan(row);self.assertNotIn('summary',missing);self.assertNotIn('product_category',missing);self.assertNotIn('merchant_visible',missing)
        self.assertEqual(row['metrics'][0]['value'],0)
        with self.hub.db() as db:
            db.execute('UPDATE video_cases SET human=? WHERE id=?',(json.dumps({'title':'','transcript':''}),cid))
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['fields']['title']['value'],'')

class ContractTests(unittest.TestCase):
    def test_skill_contract_extra_metrics_and_no_identity_guess(self):
        from video_case_kalodata import fetch,period
        from unittest.mock import Mock
        provider=Mock();provider.post.return_value={'video_id':'123456789','belonged_creator_handle':'demo','video_title':[{'text':'actual title'}],'views':'0','ads_roas':'1.5','ai_video':1}
        result=fetch(provider,{'video':'123456789','handle':'demo'},period())
        self.assertTrue(provider.post.call_args.args[1]['need_extra']);self.assertEqual(provider.post.call_count,1)
        self.assertEqual(result['title'],'actual title');self.assertEqual(result['extra_metrics']['ads_roas'],1.5)
        self.assertEqual(result['provider_flags']['ai_video'],1);self.assertNotIn('merchant_visible',result)
        self.assertEqual(result['period_views'],0);self.assertIsNone(result['likes'])
    def test_structured_code_is_sanitized_and_only_exact_media1054_waits(self):
        self.assertIsNone(QueryError('safe',code='secret https://bad.test').code)
        self.assertTrue(QueryError('safe',code=1054,endpoint='/video/url').waiting_media)
        self.assertFalse(QueryError('safe',code=1054,endpoint='/video/detail').waiting_media)
        self.assertFalse(QueryError('code 1054 in free text').waiting_media)

if __name__=='__main__':unittest.main()
