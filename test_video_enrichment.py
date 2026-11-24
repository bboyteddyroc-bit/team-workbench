import json
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import test_kalodata_integration as fixture
HEADERS = fixture.HEADERS
from kalodata_integration import QueryError


class Tests(unittest.TestCase):
    setUp = fixture.Tests.setUp
    tearDown = fixture.Tests.tearDown

    def prepare(self):
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'demo'}).json()['id']
        monitor=self.app.state.apify_monitor
        rid=monitor.queue(aid)
        published=time.time()-3*86400
        monitor.ingest({'id':rid,'account':aid},[{'id':'123456789','authorMeta':{'name':'demo','fans':500,'nickName':'Demo'},'createTime':published,'playCount':100,'diggCount':10}])
        self.aid=aid
        # 新规则：付费补数必须「全局开关打开」且「账号在勾选名单内」，测试走同一条合规路径。
        self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'enrichment':True,'confirmed':True})
        self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':True})
        return aid,self.app.state.video_enrichment

    def enable(self, **extra):
        body=dict(enabled=True,allow_paid=True,daily_limit=30);body.update(extra)
        return self.a.post('/api/intelligence/apify/accounts/'+self.aid+'/enrichment',headers=HEADERS,json=body)

    def test_disabled_by_default_and_owner_controls(self):
        aid,s=self.prepare()
        self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'enrichment':False})
        with patch.object(s.kalodata,'post') as p:s.tick();p.assert_not_called()
        self.assertEqual(self.b.post('/api/intelligence/apify/accounts/'+aid+'/enrichment',headers=HEADERS,json={'enabled':True,'allow_paid':True}).status_code,404)
        self.assertEqual(self.a.post('/api/intelligence/apify/accounts/'+aid+'/enrichment',headers=HEADERS,json={'enabled':True}).status_code,400)
        self.assertEqual(self.enable().status_code,200)
        self.assertEqual(self.b.get('/api/intelligence/apify/accounts/'+aid+'/videos').status_code,200)

    def test_global_switch_plans_selected_without_legacy_enable_and_pauses_on_deselect(self):
        aid,s=self.prepare()
        s.plan()
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT enabled FROM video_enrichment_config WHERE account=?',(aid,)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM video_enrichment_jobs WHERE account=? AND state='queued'",(aid,)).fetchone()[0],1)
        self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':False})
        with patch.object(s.kalodata,'post') as p:s.tick();p.assert_not_called()
        self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':True})
        with patch.object(s.kalodata,'post',return_value={'video_id':'123456789','revenue':0}) as p:
            s.tick();self.assertEqual(p.call_count,1)

    def test_enrich_existing_dedup_and_separate_sources(self):
        aid,s=self.prepare();self.enable()
        result={'video_id':'123456789','belonged_creator_handle':'demo','revenue':12,'sales_volumn':3,'views':80,'video_gpm':150,'revenue_trend':[1]*30}
        with patch.object(s.kalodata,'post',return_value=result) as p:
            self.assertTrue(s.tick());self.assertFalse(s.tick());self.assertEqual(p.call_count,1)
            self.assertEqual(p.call_args.args[0],'/video/detail')
        v=self.a.get('/api/intelligence/apify/accounts/'+aid+'/videos').json()[0]
        self.assertEqual(v['views'],100)
        self.assertEqual(v['kalodata']['data']['period_views'],80)
        self.assertEqual(v['kalodata']['data']['units'],3)
        self.assertEqual(len(v['kalodata']['data']['daily_gmv']),30)
        profile=self.a.get('/api/intelligence/apify/accounts').json()[0]['profile']
        self.assertEqual(profile['fans'],500)

    def test_uncertain_pauses_and_restart_never_repeats(self):
        aid,s=self.prepare();self.enable()
        with patch.object(s.kalodata,'post',side_effect=QueryError('网络异常；计费需核对')) as p:
            s.tick();s.tick();self.assertEqual(p.call_count,1)
        self.assertTrue(s.status(aid)['paused'])
        self.enable()
        with patch.object(s.kalodata,'post') as p:s.tick();p.assert_not_called()
        with self.hub.db() as db:
            db.execute("UPDATE video_enrichment_jobs SET state='running'")
        s.recover()
        with patch.object(s.kalodata,'post') as p:s.tick();p.assert_not_called()
        self.assertTrue(s.status(aid)['paused'])

    def test_daily_budget_and_young_video_wait(self):
        aid,s=self.prepare()
        with self.hub.db() as db:
            db.execute("INSERT INTO apify_snapshots(run,account,video,published,title,views,likes,comments,shares,collected) SELECT run,account,'222222222',published,title,views,likes,comments,shares,collected FROM apify_snapshots")
            db.execute("INSERT INTO apify_snapshots(run,account,video,published,title,views,likes,comments,shares,collected) SELECT run,account,'333333333',?,title,views,likes,comments,shares,collected FROM apify_snapshots LIMIT 1",(time.time(),))
        self.a.post('/api/intelligence/apify/accounts/'+aid+'/enrichment',headers=HEADERS,json={'enabled':True,'allow_paid':True,'daily_limit':1})
        def reply(path,data):return {'video_id':data['video_id'],'revenue':0}
        with patch.object(s.kalodata,'post',side_effect=reply) as p:
            s.tick();s.tick();self.assertEqual(p.call_count,1)
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM video_enrichment_jobs').fetchone()[0],2)
        self.assertEqual(s.status(aid)['calls_today'],1)

    def test_no_daily_cap_enriches_whole_batch(self):
        aid,s=self.prepare()
        with self.hub.db() as db:
            for i in range(30):
                db.execute('''INSERT INTO apify_snapshots
                  (run,account,video,published,title,views,likes,comments,shares,collected)
                  SELECT run,account,?,published,title,views,likes,comments,shares,collected
                  FROM apify_snapshots LIMIT 1''', ('9000000%02d' % i,))
        self.enable(daily_limit=0)
        def reply(path,data):return {'video_id':data['video_id'],'revenue':1}
        with patch.object(s.kalodata,'post',side_effect=reply) as p:
            s.tick()
            for _ in range(31):s.tick(now=time.time()+1)
            self.assertEqual(p.call_count,31)
        self.assertEqual(s.status(aid)['counts']['ready'],31)
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM video_enrichment_calls').fetchone()[0],31)

    def test_empty_success_retries_every_twelve_hours_then_gives_up(self):
        aid,s=self.prepare();self.enable()
        t=time.time()
        def jobs():
            with self.hub.db() as db:return [dict(r) for r in db.execute('SELECT state,next_at,error,attempts FROM video_enrichment_jobs')]
        with patch.object(s.kalodata,'post',return_value={}) as p:
            s.tick(now=t);self.assertEqual(p.call_count,1)
            self.assertEqual(jobs()[0]['state'],'waiting')
            self.assertGreaterEqual(jobs()[0]['next_at'],t+43200)
            # 满 12 小时之前不再扣费
            s.tick(now=t+43199);self.assertEqual(p.call_count,1)
            s.tick(now=t+43200);self.assertEqual(p.call_count,2)
            s.tick(now=t+43201);self.assertEqual(p.call_count,2)
            # 72 小时窗口内持续重查，到期仍无数据才停
            s.tick(now=t+2*86400);self.assertEqual(p.call_count,3)
            s.tick(now=t+72*3600);self.assertEqual(p.call_count,4)
            s.tick(now=t+200*3600);self.assertEqual(p.call_count,4)
        self.assertEqual(jobs()[0]['state'],'unavailable')
        self.assertEqual(s.status(aid)['counts']['unavailable'],1)
        # 同一次采集不会再排第二批（last_run 已记录）。
        s.plan(now=time.time()+86400)
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM video_enrichment_jobs').fetchone()[0],1)
        with self.hub.db() as db:
            db.execute('DELETE FROM video_enrichment_jobs')
            db.execute('UPDATE video_enrichment_config SET last_run=NULL')
        with patch.object(s.kalodata,'post',return_value={'video_id':'WRONG','revenue':99}):s.tick()
        self.assertTrue(s.status(aid)['paused'])

    def test_no_key_and_stop_switch(self):
        aid,s=self.prepare();self.enable()
        with patch.object(s.kalodata,'secret',return_value=''),patch.object(s.kalodata,'post') as p:s.tick();p.assert_not_called()
        self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'enrichment':False})
        with patch.object(s.kalodata,'post') as p:s.tick();p.assert_not_called()

    def test_transactional_claim_prevents_duplicate_charge(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        aid,s=self.prepare();self.enable()
        entered,release=Event(),Event()
        def reply(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return {'video_id':'123456789','revenue':0}
        with patch.object(s.kalodata,'post',side_effect=reply) as p,ThreadPoolExecutor(2) as pool:
            first=pool.submit(s.tick)
            self.assertTrue(entered.wait(5))
            try:self.assertFalse(s.tick())
            finally:release.set()
            self.assertTrue(first.result(timeout=5))
            self.assertEqual(p.call_count,1)

    def test_wire_contract_and_wave_follows_run(self):
        import httpx
        aid,s=self.prepare();self.enable()
        def reply(request):
            self.assertTrue(str(request.url).endswith('/video/detail'))
            self.assertTrue(request.headers.get('secret-key'))
            payload=json.loads(request.content)
            self.assertEqual(payload['video_id'],'123456789')
            self.assertEqual(payload['region'],'US')
            return httpx.Response(200,json={'success':True,'data':{'video_id':'123456789','revenue':0,'sales_volumn':None}})
        original=httpx.Client
        with patch('kalodata_integration.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(reply),**kw)):
            self.assertTrue(s.tick())
        self.assertEqual(s.video(aid,'123456789')['data']['gmv'],0)
        self.assertIsNone(s.video(aid,'123456789')['data']['units'])
        # 只有一批采集：再过一天也不会自己触发第二次补数。
        s.plan(now=time.time()+86400)
        with self.hub.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM video_enrichment_jobs WHERE state='queued'").fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM video_enrichment_jobs').fetchone()[0],1)
        self.assertIsNotNone(s.video(aid,'123456789')['data'])

    def test_enrichment_only_follows_latest_collection(self):
        aid,s=self.prepare();self.enable();m=self.app.state.apify_monitor
        def reply(path,data):return {'video_id':data['video_id'],'revenue':0}
        with patch.object(s.kalodata,'post',side_effect=reply) as p:
            s.tick()
            self.assertEqual(p.call_count,1)
            # 没有新采集：往后跑三天，一条也不会新增、一次也不会调用。
            for _ in range(3):
                with self.hub.db() as db:db.execute('UPDATE video_enrichment_jobs SET next_at=0')
                s.plan(now=time.time()+86400)
                s.tick()
            with self.hub.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM video_enrichment_jobs').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM video_enrichment_calls').fetchone()[0],1)
            self.assertEqual(p.call_count,1)
            # 失败的那次采集不算数：不得触发补数。
            with self.hub.db() as db:
                db.execute("INSERT INTO apify_runs(id,account,state,created,updated,error) VALUES('failed-run',?,'attention',?,?,'采集失败')",(aid,time.time(),time.time()))
            s.plan(now=time.time()+86400)
            with self.hub.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM video_enrichment_jobs').fetchone()[0],1)
            # 新一批采集：只补这一批的视频，并记录属于哪次采集。
            rid=m.queue(aid)
            m.ingest({'id':rid,'account':aid},[{'id':'987654321','authorMeta':{'name':'demo'},'createTime':time.time()-3*86400,'playCount':50}])
            s.tick()
            self.assertEqual(p.call_count,2)
            with self.hub.db() as db:
                row=db.execute("SELECT run FROM video_enrichment_jobs WHERE video='987654321'").fetchone()
                self.assertEqual(row['run'],rid)
                self.assertEqual(db.execute('SELECT last_run FROM video_enrichment_config').fetchone()[0],rid)
            # 同一批不会重复补。
            with self.hub.db() as db:db.execute('UPDATE video_enrichment_jobs SET next_at=0')
            s.tick();self.assertEqual(p.call_count,2)

    def test_apify_submit_to_enrichment_pipeline(self):
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        self.aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'demo'}).json()['id']
        self.enable();m=self.app.state.apify_monitor;s=self.app.state.video_enrichment
        self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'enrichment':True,'confirmed':True})
        self.a.post('/api/intelligence/apify/accounts/'+self.aid+'/selection',headers=HEADERS,json={'selected':True})
        m.queue(self.aid)
        with patch.object(m,'request',side_effect=[{'data':{'id':'mock-run'}},{'data':{'status':'SUCCEEDED','defaultDatasetId':'mock-dataset'}},[{'id':'123456789','authorMeta':{'name':'demo'},'createTime':time.time()-3*86400,'playCount':88}]]):
            m.tick();m.tick()
        with patch.object(s.kalodata,'post',return_value={'video_id':'123456789','revenue':23,'sales_volumn':2}):s.tick()
        v=self.a.get('/api/intelligence/apify/accounts/'+self.aid+'/videos').json()[0]
        self.assertEqual((v['views'],v['kalodata']['data']['gmv']),(88,23))

if __name__=='__main__':unittest.main()
