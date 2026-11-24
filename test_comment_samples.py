"""Offline full-app coverage. Vendor traffic goes only to httpx.MockTransport."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from comment_samples import PREFIX, enqueue
from comment_research import SIGNALS
from test_own_goods import BASE, HEADERS, fixture
from video_consent import POLICY

VID='123456789'
CASE_VID='234567891'
KEY='fixture-scrape-key'


class CommentSampleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,{'HUB_ORIGIN':BASE});env.start();self.addCleanup(env.stop)
        self.app=fixture(temp.name);self.hub=self.app.state.hub;self.svc=self.app.state.comment_samples
        self.admin=TestClient(self.app,base_url=BASE);self.member=TestClient(self.app,base_url=BASE)
        for c,u in [(self.admin,'fixture_admin'),(self.member,'fixture_a')]:
            self.addCleanup(c.close)
            self.assertEqual(c.post('/api/login',headers=HEADERS,json={'username':u,'password':'isolated-fixture-password'}).status_code,200)

    def config(self,action,code=200,who=None,**d):
        r=(who or self.admin).post(PREFIX+'/config',headers=HEADERS,json={'action':action,**d});self.assertEqual(r.status_code,code,r.text)
        self.assertNotIn(KEY,r.text);return r.json()

    def fake(self,handler):
        c=httpx.Client(transport=httpx.MockTransport(handler));self.addCleanup(c.close);return c

    def enable(self,**caps):
        self.config('save',key=KEY,**caps)
        return self.config('enable',confirm_paid=True)

    def add(self,vid,automatic=True):
        d={'urls':[f'https://www.tiktok.com/@fixture/video/{vid}'],'auto_process':automatic}
        if automatic:d.update(confirm_automation=True,share_with_team=True,native_video_consent=True,native_video_policy=POLICY)
        r=self.member.post('/api/intelligence/cases',headers=HEADERS,json=d);self.assertEqual(r.status_code,200,r.text)
        return r.json()['items'][0]['id']

    def test_single_request_does_not_resume_the_queue(self):
        self.enable();self.add(CASE_VID);self.config('disable')
        requests=[]
        def page(request):
            requests.append(str(request.url))
            return httpx.Response(200,json={'success':True,'comments':[],'cursor':22,'has_more':1})
        client=self.fake(page)
        self.assertTrue(self.svc.collect_one(client,only_video=CASE_VID))
        self.assertFalse(self.svc.collect_one(client,only_video=CASE_VID))
        self.assertFalse(self.svc.collect_one(client))
        self.assertEqual(len(requests),1)
        with self.hub.db() as db:
            self.assertEqual(dict(db.execute('SELECT video,state FROM comment_sample_jobs')),{VID:'queued',CASE_VID:'empty'})

    def test_inert_key_access_and_durable_backfill(self):
        self.assertFalse(self.svc.collect_one(None))
        self.assertEqual(self.admin.post(PREFIX+'/config',json={'action':'save','key':KEY}).status_code,403)
        self.config('save',code=403,who=self.member,key=KEY)
        self.config('save',code=400,key=KEY,daily=1)
        self.assertFalse(self.config('save',key=KEY)['collect'])
        self.assertFalse(self.svc.collect_one(None))
        self.config('enable',code=400)
        self.assertEqual(self.config('enable',confirm_paid=True)['queued_now'],1)
        self.assertEqual(self.config('enable',confirm_paid=True)['queued_now'],0)
        self.add(CASE_VID);self.add(CASE_VID)
        self.add('444444444',False)
        with self.hub.db() as db:
            self.assertEqual(dict(db.execute('SELECT video,origin FROM comment_sample_jobs')),{VID:'backfill',CASE_VID:'case','444444444':'case'})
            self.assertNotIn(KEY.encode(),db.execute('SELECT secret FROM comment_sample_config').fetchone()[0])
            self.assertEqual(db.execute('SELECT count(*) FROM video_case_jobs WHERE kind=\'metadata\'').fetchone()[0],1)
        r=self.svc.claim('collect');self.assertEqual(r[0]['video'],VID)

    def test_fetch_pages_replies_reuse_and_ai_counts(self):
        self.enable(pages=2,replies=1,daily=3)
        self.add(CASE_VID)
        with self.hub.db() as db:
            db.execute('INSERT INTO a6_settings VALUES(1,?,1)',(self.hub.cipher.encrypt(b'fixture-a6-key'),))
        self.config('enable_ai',code=400)
        self.config('enable_ai',confirm_ai=True)
        def item(id,text,replies=0):return {'aweme_id':VID,'cid':id,'text':text,'reply_comment_total':replies,'create_time':1700000000,'user':{'unique_id':'do-not-send-account'}}
        a=item('101010','尺寸太小',3);b=item('202020','Fits well');r=item('303030','想要更宽')
        seen=[]
        def vendor(req):
            if req.url.host=='api.scrapecreators.com':
                self.assertEqual(req.headers['x-api-key'],KEY);self.assertIn(VID,req.url.params['url']);seen.append(req.url.path)
                if req.url.path.endswith('/replies'):
                    self.assertEqual(req.url.params['comment_id'],'101010');items=[r];more=0;cursor=55
                elif 'cursor' in req.url.params:
                    self.assertEqual(req.url.params['cursor'],'20');items=[a,b];more=0;cursor=None
                else:items=[a];more=1;cursor=20
                return httpx.Response(200,json={'success':True,'comments':items,'has_more':more,'cursor':cursor,'credits_charged':1})
            self.assertEqual(req.url.host,'api.a6api.vip');self.assertNotIn('do-not-send-account',req.content.decode());self.assertNotIn('101010',req.content.decode())
            seen.append('AI')
            marks={k:[] for k in SIGNALS}|{'pain':[{'label':'尺寸太小','ids':[1,1]}],'looking':[{'label':'找更宽的款','ids':[3]}]}
            out={'topics':[{'label':'希望尺寸更宽','for':[1,1,3],'against':[2]}],'signals':marks}
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(out)}}]})
        client=self.fake(vendor)
        self.assertTrue(self.svc.collect_one(client));self.assertFalse(self.svc.collect_one(client));self.assertTrue(self.svc.ai_one(client))
        d=self.member.get(PREFIX+'/'+VID).json();self.assertEqual((d['comments'],d['replies']),(2,1))
        self.assertEqual(d['topics'][0]['support'],{'comments':1,'replies':1,'ids':['101010','303030']})
        self.assertEqual(d['topics'][0]['counter']['comments'],1)
        self.assertEqual(d['research']['pain']['comments'],{'hits':1,'total':2,'pct':50.0})
        self.assertEqual(d['research']['looking']['replies'],{'hits':1,'total':1,'pct':100.0})
        self.assertEqual(d['research']['pain']['groups'][0]['ids'],['101010'])
        self.assertEqual(self.member.get(PREFIX+'/config').json()['usage'],{'requests':3,'ai_calls':1,'reported_credits':3,'unreported':0})
        self.assertEqual(len(seen),4)
        self.assertEqual(self.member.get(PREFIX+'/'+CASE_VID).json()['state'],'queued')

    def test_unknown_no_resubmit_and_empty_not_zero(self):
        self.enable(pages=1,replies=0,daily=3);self.add(CASE_VID)
        sent=[]
        def broken(req):sent.append(req.url.path);raise httpx.ReadTimeout('do not disclose',request=req)
        self.assertTrue(self.svc.collect_one(self.fake(broken)))
        self.assertFalse(self.svc.collect_one(None));self.assertEqual(len(sent),1)
        self.assertEqual(self.member.get(PREFIX+'/'+VID).json()['state'],'attention')
        self.assertEqual(self.svc.status(True)['usage']['unreported'],1)
        self.config('enable',confirm_paid=True)
        self.assertTrue(self.svc.collect_one(self.fake(lambda req:httpx.Response(200,json={'success':True,'comments':[],'end_of_pagination':True,'credits_charged':0}))))
        out=self.member.get(PREFIX+'/'+CASE_VID).json();self.assertEqual(out['state'],'empty');self.assertIn('不代表',out['stop_reason'])
        self.assertFalse(self.svc.collect_one(None));self.assertEqual(self.member.get(PREFIX+'/'+VID).json()['requests'],1)

    def test_monitoring_stays_apify_only_and_library_membership_gates_legacy_jobs(self):
        self.enable()
        svc=self.app.state.apify_monitor;aid='sample-account'
        with self.hub.db() as db:
            db.execute('INSERT INTO apify_accounts(id,owner,handle) VALUES(?,?,?)',(aid,'fixture_a','fixture'))
            db.execute('INSERT INTO auto_collection_config VALUES(?,?,?,?)',('fixture_a',1,0,1))
            db.execute('INSERT INTO auto_collection_selection VALUES(?,?,?,?)',('fixture_a',aid,1,1))
            db.executemany("INSERT INTO apify_runs(id,account,state,created,updated) VALUES(?,?,'ready',1,1)",[(x,aid) for x in ['manual','auto']])
        raw=[{'id':CASE_VID,'authorMeta':{'name':'fixture'},'createTime':1,'playCount':100}]
        for run,auto in [('manual',False),('auto',True)]:svc.ingest({'id':run,'account':aid,'automatic':auto},raw)
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM apify_snapshots WHERE video=?',(CASE_VID,)).fetchone()[0],2)
            self.assertFalse(db.execute('SELECT 1 FROM comment_sample_jobs WHERE video=?',(CASE_VID,)).fetchone())
            self.assertFalse(enqueue(db,CASE_VID,'fixture','case'))
            db.execute("INSERT INTO comment_sample_jobs(video,url,origin,state,created,updated) VALUES(?,?,'monitor','queued',1,1)",(CASE_VID,f'https://www.tiktok.com/@fixture/video/{CASE_VID}'))
        self.assertEqual(self.svc.claim('collect')[0]['video'],VID)
        self.assertIsNone(self.svc.claim('collect'))
        with self.hub.db() as db:
            db.execute("UPDATE comment_sample_jobs SET state='ready' WHERE video=?",(CASE_VID,))
            db.execute('INSERT INTO a6_settings VALUES(1,?,1)',(self.hub.cipher.encrypt(b'fixture-a6-key'),))
        self.config('enable_ai',confirm_ai=True)
        self.assertIsNone(self.svc.claim('ai'))
        self.assertEqual(self.member.get(PREFIX+'/'+CASE_VID).status_code,404)
        self.assertEqual(self.member.get(PREFIX).json()['total'],1)
        self.add(CASE_VID)
        self.assertEqual(self.member.get(PREFIX+'/'+CASE_VID).json()['origin'],'monitor')
        self.assertIsNone(self.svc.claim('collect'))  # existing samples never recollected just because it was added
        self.assertEqual(self.svc.claim('ai')[0]['video'],CASE_VID)
        with self.hub.db() as db:db.execute('UPDATE video_cases SET removed_at=1 WHERE video=?',(CASE_VID,))
        self.assertEqual(self.member.get(PREFIX+'/'+CASE_VID).status_code,404)

    def test_ai_invalid_ids_do_not_publish(self):
        self.enable(pages=1,replies=0)
        self.svc.collect_one(self.fake(lambda req:httpx.Response(200,json={'success':True,'comments':[{'cid':'101010','text':'有味道'}]})))
        with self.hub.db() as db:db.execute('INSERT INTO a6_settings VALUES(1,?,1)',(self.hub.cipher.encrypt(b'fixture-a6-key'),))
        self.config('enable_ai',confirm_ai=True)
        data={'topics':[{'label':'假引用','for':[999],'against':[]}]}
        self.assertTrue(self.svc.ai_one(self.fake(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]}))))
        out=self.member.get(PREFIX+'/'+VID).json();self.assertEqual((out['ai_state'],out['topics']),('attention',[]))
        self.assertIsNone(out['research'])

    def test_supplement_is_admin_only_idempotent_and_preserves_old_topics(self):
        endpoint=PREFIX+'/'+VID+'/research';old=[{'label':'保留旧主题','support':['101010'],'counter':[]}]
        with self.hub.db() as db:
            db.execute('INSERT INTO a6_settings VALUES(1,?,1)',(self.hub.cipher.encrypt(b'fixture-a6-key'),))
            db.execute("INSERT INTO comment_sample_jobs(video,url,origin,state,ai_state,created,updated,topics) VALUES(?,?,'case','ready','ready',1,1,?)",
                       (VID,f'https://www.tiktok.com/@fixture/video/{VID}',json.dumps(old)))
            db.execute('INSERT INTO comment_sample_text VALUES(?,?,?, ?,1,1,0)',(VID,'101010','','哪里可以买到'))
        self.assertIsNone(self.member.get(PREFIX+'/'+VID).json()['research'])
        self.assertFalse(self.svc.ai_one(None))
        self.assertEqual(self.member.post(endpoint,headers=HEADERS,json={'confirm_ai':True}).status_code,403)
        self.assertEqual(self.admin.post(endpoint,headers=HEADERS,json={'confirm_ai':True}).status_code,409)
        self.config('enable_ai',confirm_ai=True)
        self.assertEqual(self.admin.post(endpoint,headers=HEADERS,json={}).status_code,400)
        self.assertTrue(self.admin.post(endpoint,headers=HEADERS,json={'confirm_ai':True}).json()['queued_now'])
        self.assertFalse(self.admin.post(endpoint,headers=HEADERS,json={'confirm_ai':True}).json()['queued_now'])
        calls=[]
        def timeout(req):
            calls.append(req.url.host)
            only_text=json.loads(json.loads(req.content)['messages'][-1]['content'])
            self.assertEqual(only_text,[{'n':1,'role':'评论','text':'哪里可以买到'}])
            raise httpx.ReadTimeout('unknown charge',request=req)
        self.assertTrue(self.svc.ai_one(self.fake(timeout)))
        saved=self.admin.post(endpoint,headers=HEADERS,json={'confirm_ai':True}).json()
        self.assertEqual(saved,{'state':'attention','queued_now':False})
        self.assertEqual(self.member.get(PREFIX+'/'+VID).json()['topics'][0]['label'],'保留旧主题')
        self.assertFalse(self.svc.status(True)['ai_error']);self.assertEqual(calls,['api.a6api.vip'])
        self.assertFalse(self.svc.ai_one(None));self.assertEqual(self.svc.status(True)['usage']['ai_calls'],1)

    def test_missing_multiaxis_keeps_valid_topics_without_retry(self):
        self.enable(pages=1,replies=0)
        self.svc.collect_one(self.fake(lambda _:httpx.Response(200,json={'success':True,'comments':[{'cid':'101010','text':'有味道'}]})))
        with self.hub.db() as db:db.execute('INSERT INTO a6_settings VALUES(1,?,1)',(self.hub.cipher.encrypt(b'fixture-a6-key'),))
        self.config('enable_ai',confirm_ai=True)
        data={'topics':[{'label':'有气味','for':[1],'against':[]}],
              'signals':{k:[] for k in SIGNALS}|{'pain':[{'label':'有气味','ids':[1]}],'reaction':[{'label':'泛反应','ids':[1]}]}}
        self.assertTrue(self.svc.ai_one(self.fake(lambda _:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]}))))
        out=self.member.get(PREFIX+'/'+VID).json()
        self.assertEqual(out['ai_state'],'ready');self.assertEqual(out['topics'][0]['label'],'有气味');self.assertIsNone(out['research'])
        self.assertFalse(self.svc.ai_one(None))
