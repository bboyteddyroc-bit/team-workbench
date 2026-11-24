import json
import unittest
from unittest.mock import patch
from test_kalodata_integration import Tests as Fixture,HEADERS
from video_cases import normalize

class VideoCaseTests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    base='/api/intelligence/cases'
    def add(self,client=None,video='123456789',reason=''):
        r=(client or self.a).post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/'+video+'?share=1'],'reason':reason})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()['items'][0]['id']
    def test_normalization_and_input_restrictions(self):
        self.assertEqual(normalize('https://www.tiktok.com/@DEMO/video/123456789?x=y')['key'],'tiktok:123456789')
        for url in ('https://127.0.0.1/x','file:///x','https://evil.example/v','https://www.tiktok.com/@demo','https://vt.tiktok.com/abc'):
            with self.assertRaises(ValueError):normalize(url)
        self.assertEqual(self.a.post(self.base,headers=HEADERS,json={'urls':['https://evil.test']}).status_code,400)
        self.assertEqual(self.a.post(self.base,json={'urls':[]}).status_code,403)
    def test_dedup_personal_team_and_member_owned_ideas(self):
        cid=self.add(reason='值得借鉴')
        self.assertEqual(self.b.get(self.base+'?scope=mine').json()['total'],0)
        self.assertEqual(self.b.get(self.base+'?scope=team').json()['total'],1)
        self.assertEqual(self.add(self.b),cid)
        row=self.b.get(self.base+'/'+cid).json();self.assertEqual(len(row['collectors']),2)
        i=row['ideas'][0]
        self.assertFalse(i['is_owner'])
        self.assertEqual(self.b.post(self.base+'/'+cid+'/ideas',headers=HEADERS,json={'id':i['id'],'revision':i['revision'],'fields':{'reason':'overwrite'}}).status_code,404)
        edited=self.a.post(self.base+'/'+cid+'/ideas',headers=HEADERS,json={'id':i['id'],'revision':i['revision'],'fields':{'reason':'新想法','hypothesis':'只改开头'}})
        self.assertEqual(edited.status_code,200)
        self.assertEqual(self.a.post(self.base+'/'+cid+'/ideas',headers=HEADERS,json={'id':i['id'],'revision':i['revision'],'fields':{'reason':'lost'}}).status_code,409)
        self.b.post(self.base+'/'+cid+'/collect',headers=HEADERS,json={'saved':False})
        self.assertEqual(self.b.get(self.base+'/'+cid).status_code,200)
    def test_creator_can_remove_team_case_and_cancel_unsent_jobs(self):
        cid=self.add();self.add(self.b);path=self.base+'/'+cid
        self.assertTrue(self.a.get(path).json()['can_remove'])
        self.assertFalse(self.b.get(path).json()['can_remove'])
        self.assertEqual(self.b.post(path+'/remove',headers=HEADERS,json={'confirm':True}).status_code,403)
        with self.app.state.hub.db() as db:
            owner=db.execute('SELECT created_by FROM video_cases WHERE id=?',(cid,)).fetchone()[0]
            db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES('remove-job',?,?,'analysis','queued','remove-job',1,1,'{}')",(cid,owner))
        self.assertEqual(self.a.post(path+'/remove',headers=HEADERS,json={'confirm':True}).status_code,200)
        self.assertEqual(self.b.get(path).status_code,404)
        self.assertEqual(self.b.get(self.base).json()['total'],0)
        self.assertEqual(self.b.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789']}).status_code,409)
        with self.app.state.hub.db() as db:
            self.assertEqual(db.execute("SELECT state FROM video_case_jobs WHERE id='remove-job'").fetchone()[0],'cancelled')
            self.assertIsNotNone(db.execute('SELECT removed_at FROM video_cases WHERE id=?',(cid,)).fetchone()[0])
    def test_manual_ai_separation_and_revision(self):
        cid=self.add();path=self.base+'/'+cid
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'revision':1,'fields':{'summary':'人工结论','tags':['手工']}}).status_code,200)
        self.assertEqual(self.b.post(path,headers=HEADERS,json={'revision':1,'fields':{'summary':'覆盖'}}).status_code,409)
        with self.app.state.hub.db() as db:
            db.execute('UPDATE video_cases SET ai=? WHERE id=?',(json.dumps({'fields':{'summary':'AI推断'}}),cid))
        row=self.a.get(path).json();self.assertEqual(row['human']['summary'],'人工结论');self.assertEqual(row['ai']['fields']['summary'],'AI推断')
    def test_reuse_snapshot_and_library_without_charges(self):
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'demo'}).json()['id']
        self.app.state.apify_monitor.ingest({'id':'fake-run','account':aid},[{'id':'123456789','authorMeta':{'name':'demo'},'text':'Real description','playCount':100,'createTime':1700000000}])
        with patch.object(self.app.state.apify_monitor,'request',side_effect=AssertionError('No request on add')):
            cid=self.add();row=self.b.get(self.base+'/'+cid).json()
            self.assertEqual(row['source']['title'],'Real description');self.assertEqual(row['source']['views'],100)
            v=self.a.post(self.base+'/'+cid+'/library',headers=HEADERS,json={}).json()
            v2=self.b.post(self.base+'/'+cid+'/library',headers=HEADERS,json={}).json()
        self.assertEqual(v['id'],v2['id']);self.assertTrue(v2['existing'])
        lib=self.a.get('/api/intelligence/scripts').json()[0]
        self.assertIsNone(lib['transcript_original']);self.assertIn('非数据达标',lib['reasons'][0]);self.assertEqual(lib['auto_enrichment_excluded'],1)
    def test_metadata_consent_idempotence_exact_video_and_recovery(self):
        cid=self.add();service=self.app.state.video_cases;path=self.base+'/'+cid+'/process'
        payload={'kind':'metadata','request_key':'metadata-key-123','confirm':True}
        self.assertEqual(self.a.post(path,headers=HEADERS,json={**payload,'confirm':False}).status_code,400)
        with patch.object(service.monitor.config,'available',return_value=True):
            r=self.a.post(path,headers=HEADERS,json=payload).json();r2=self.a.post(path,headers=HEADERS,json=payload).json()
        self.assertEqual(r['id'],r2['id'])
        with patch.object(service.monitor,'request',return_value={'data':{'id':'Remote12345','defaultDatasetId':'Dataset12345'}}) as call:
            service.tick();service.recover()
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.kwargs['json']['postURLs'],['https://www.tiktok.com/@demo/video/123456789'])
            self.assertNotIn('profiles',call.call_args.kwargs['json'])
            self.assertFalse(call.call_args.kwargs['json']['aiVideoSummary'])
        with patch.object(service.monitor,'request',side_effect=[{'data':{'status':'SUCCEEDED','defaultDatasetId':'Dataset12345'}},[{'id':'123456789','text':'from upstream','playCount':55}]]) as call:
            service.tick();self.assertTrue(all(c.args[0]=='GET' for c in call.call_args_list))
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['source']['views'],55);self.assertEqual(row['jobs'][0]['state'],'ready')
    def test_case_apify_pool_binding_pin_and_exhaustion_no_retry(self):
        import httpx
        cid=self.add();service=self.app.state.video_cases;pool=self.app.state.apify_pool
        pool.add('expired','fixture-apify-old');pool.add('active','fixture-apify-new')
        with self.app.state.hub.db() as db:db.execute("UPDATE apify_keys SET state='exhausted' WHERE name='expired'")
        jid=self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json={'kind':'metadata','confirm':True,'request_key':'case-pool-check'}).json()['id']
        seen=[]
        def mock_request(client,method,url,**kw):
            seen.append((method,kw['headers']['Authorization']))
            if method=='POST':return httpx.Response(200,json={'data':{'id':'Remote12345','defaultDatasetId':'Dataset12345'}},request=httpx.Request(method,url))
            if '/actor-runs/' in url:return httpx.Response(200,json={'data':{'status':'SUCCEEDED','defaultDatasetId':'Dataset12345'}},request=httpx.Request(method,url))
            return httpx.Response(200,json=[{'id':'123456789','playCount':11}],request=httpx.Request(method,url))
        with patch('apify_monitor.httpx.Client.request',new=mock_request):
            service.tick();service.tick();service.tick()
        self.assertEqual(len(seen),3);self.assertTrue(all(token=='Bearer fixture-apify-new' for _,token in seen))
        with self.app.state.hub.db() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM apify_key_bindings WHERE run=?',('case:'+jid,)).fetchone())
        self.assertEqual(self.a.get(self.base+'/'+cid).json()['source']['views'],11)
    def test_pool_402_marks_account_without_rotation_or_retry(self):
        import httpx
        cid=self.add();service=self.app.state.video_cases;pool=self.app.state.apify_pool
        pool.add('first','fixture-apify-first');pool.add('second','fixture-apify-second')
        jid=self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json={'kind':'metadata','confirm':True,'request_key':'case-pool-402'}).json()['id']
        def fail(client,method,url,**kw):return httpx.Response(402,request=httpx.Request(method,url))
        with patch('apify_monitor.httpx.Client.request',new=fail) as unused:
            service.tick();service.tick()
        with self.app.state.hub.db() as db:
            bound=db.execute('SELECT k.state,k.name FROM apify_keys k JOIN apify_key_bindings b ON k.id=b.key_id WHERE b.run=?',('case:'+jid,)).fetchone()
            self.assertEqual(bound['state'],'exhausted')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM apify_key_bindings WHERE run=?',('case:'+jid,)).fetchone()[0],1)
        self.assertEqual(self.a.get(self.base+'/'+cid).json()['jobs'][0]['state'],'attention')
        self.assertNotEqual(pool.token('case:another',True),pool.token('case:'+jid))
    def test_uncertain_processing_never_retries_automatically(self):
        cid=self.add();service=self.app.state.video_cases
        with patch.object(service.monitor.config,'available',return_value=True):
            r=self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json={'kind':'metadata','confirm':True,'request_key':'uncertain-key'}).json()
        with patch.object(service.monitor,'request',side_effect=ValueError('网络结果未知')) as call:
            service.tick();service.tick();self.assertEqual(call.call_count,1)
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['jobs'][0]['state'],'attention')
        service.recover();self.assertEqual(self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json={'kind':'metadata','confirm':True,'request_key':'other-key-123'}).status_code,409)
    def test_idea_to_script_keeps_snapshot_and_link(self):
        cid=self.add(reason='选择式结尾')
        v=self.a.post(self.base+'/'+cid+'/library',headers=HEADERS,json={}).json()
        iid=self.b.get(self.base+'/'+cid).json()['ideas'][0]['id']
        payload={'source_id':v['id'],'case_id':cid,'idea_id':iid,'product':'真实产品资料','request_key':'case-script-key'}
        with patch('asr.configured_key',return_value='fake'),patch('script_creation.generate',return_value='script') as gen:
            r=self.b.post('/api/intelligence/creative-tasks',headers=HEADERS,json=payload)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(gen.call_args.args[0]['case_context']['member_idea']['reason'],'选择式结尾')
        self.assertEqual(len(self.a.get(self.base+'/'+cid).json()['tasks']),1)
    def test_ai_description_not_spoken_transcript_and_human_preserved(self):
        cid=self.add();hub=self.app.state.hub
        with hub.db() as db:db.execute('UPDATE video_cases SET source=?,human=? WHERE id=?',(json.dumps({'title':'description'}),json.dumps({'summary':'manual'}),cid))
        payload={'kind':'ai','request_key':'ai-description-key','confirm':True}
        fake={'transcript_en':'wrong','transcript_zh':'不应是逐字稿','expression':'文字摘要'}
        with patch('asr.configured_key',return_value='fake'),patch('script_enrichment.request_enrichment',return_value=fake):
            self.assertEqual(self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json=payload).status_code,200);self.app.state.video_cases.tick()
        row=self.a.get(self.base+'/'+cid).json();self.assertNotIn('transcript_en',row['ai']['fields']);self.assertEqual(row['human']['summary'],'manual');self.assertIn('仅发布文案',row['ai']['fields']['basis'])

    def test_cover_reuses_persisted_monitor_cache_without_network(self):
        cid=self.add();directory=self.app.state.hub.directory/'apify-covers';directory.mkdir(exist_ok=True)
        image=b'\xff\xd8\xff'+b'verification-only';(directory/'123456789.jpg').write_bytes(image)
        with patch('video_cases.httpx.Client',side_effect=AssertionError('cached covers must not request CDN')):
            response=self.a.get(self.base+'/'+cid+'/cover')
        self.assertEqual(response.status_code,200);self.assertEqual(response.content,image);self.assertEqual(response.headers['content-type'],'image/jpeg')
        self.assertEqual(self.a.get(self.base+'/missing-case/cover').status_code,404)

    def test_kalodata_explicit_team_consent_period_and_idempotence(self):
        cid=self.add();path=self.base+'/'+cid+'/process';service=self.app.state.video_cases
        data={'kind':'kalodata','request_key':'kalo-case-123','confirm':True,'days':30,'share_with_team':True}
        self.assertEqual(self.a.post(path,headers=HEADERS,json={**data,'share_with_team':False}).status_code,400)
        first=self.a.post(path,headers=HEADERS,json=data);self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['id'],self.a.post(path,headers=HEADERS,json=data).json()['id'])
        self.assertEqual(self.a.post(path,headers=HEADERS,json={**data,'days':7}).status_code,409)
        fake={'video_id':'123456789','video_title':'Kalodata title','belonged_creator_handle':'demo','views':123,'revenue':25,'digg_count':0,'email':'private@example.test'}
        with patch.object(service.kalodata,'post',return_value=fake) as upstream:
            service.tick();service.tick();self.assertEqual(upstream.call_count,1)
            self.assertEqual(upstream.call_args.args[0],'/video/detail')
            self.assertEqual(upstream.call_args.args[1]['video_id'],'123456789')
        row=self.b.get(self.base+'/'+cid).json();k=row['source']['kalodata']
        self.assertEqual(k['period_views'],123);self.assertNotIn('views',row['source']);self.assertEqual(k['likes'],0)
        self.assertIsNone(k['shares']);self.assertNotIn('private@example',str(row));self.assertEqual(row['source']['title'],'Kalodata title')
        self.assertEqual(self.a.post(path,headers=HEADERS,json={**data,'request_key':'fresh-kalo-key'}).json()['id'],first.json()['id'])
        self.assertEqual(self.b.get('/api/intelligence/kalodata/jobs').json(),[])

    def test_kalodata_failure_no_retry_or_source_loss(self):
        from kalodata_integration import QueryError
        cid=self.add();service=self.app.state.video_cases
        with self.app.state.hub.db() as db:db.execute('UPDATE video_cases SET source=?,human=? WHERE id=?',(json.dumps({'title':'old'}),json.dumps({'summary':'manual'}),cid))
        data={'kind':'kalodata','request_key':'kalo-failure-key','confirm':True,'days':7,'share_with_team':True}
        self.assertEqual(self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json=data).status_code,200)
        with patch.object(service.kalodata,'post',side_effect=QueryError('Kalodata API credits 余额不足（2016）')) as upstream:
            service.tick();service.tick();self.assertEqual(upstream.call_count,1)
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['source']['title'],'old');self.assertEqual(row['human']['summary'],'manual');self.assertEqual(row['jobs'][0]['state'],'attention');self.assertIn('2016',row['jobs'][0]['error'])
        self.assertEqual(self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json={**data,'request_key':'other-failure-key'}).status_code,409)

    def test_kalodata_strict_match_and_recovery(self):
        from video_case_kalodata import fetch,period
        from kalodata_integration import QueryError
        cid=self.add();service=self.app.state.video_cases
        case={'video':'123456789','handle':'demo'}
        for result in ({'video_id':'999999999'},{'video_id':'123456789','belonged_creator_handle':'other'},{'video_id':'123456789','video_region':'GB'}):
            with patch.object(service.kalodata,'post',return_value=result),self.assertRaises(QueryError):fetch(service.kalodata,case,period())
        path=self.base+'/'+cid+'/process';data={'kind':'kalodata','request_key':'recover-kalo-key','confirm':True,'share_with_team':True}
        jid=self.a.post(path,headers=HEADERS,json=data).json()['id']
        with self.app.state.hub.db() as db:db.execute("UPDATE video_case_jobs SET state='running' WHERE id=?",(jid,))
        service.recover()
        with patch.object(service.kalodata,'post') as upstream:service.tick();upstream.assert_not_called()
        self.assertEqual(self.a.get(self.base+'/'+cid).json()['jobs'][0]['state'],'attention')

    def test_automatic_add_chains_once_then_human_review(self):
        from video_case_analysis import FIELDS
        url='https://www.tiktok.com/@demo/video/123456799'
        payload={'urls':[url],'auto_process':True,'confirm_automation':True,'share_with_team':True}
        self.assertEqual(self.a.post(self.base,headers=HEADERS,json={**payload,'confirm_automation':False}).status_code,400)
        cid=self.a.post(self.base,headers=HEADERS,json=payload).json()['items'][0]['id']
        self.assertEqual(cid,self.a.post(self.base,headers=HEADERS,json=payload).json()['items'][0]['id'])
        service=self.app.state.video_cases
        def apify(method,path,**kwargs):
            if method=='POST':return {'data':{'id':'runABCDE','defaultDatasetId':'dataABCDE'}}
            if '/actor-runs/' in path:return {'data':{'status':'SUCCEEDED','defaultDatasetId':'dataABCDE'}}
            return [{'id':'123456799','text':'Tools demo','playCount':100,'collectCount':5}]
        with patch.object(service.monitor,'request',side_effect=apify) as upstream:
            service.tick('media');service.tick('media')
            self.assertEqual(upstream.call_count,3)
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['source']['collects'],5);self.assertEqual(len(row['jobs']),2)
        self.assertEqual(sum(j['kind']=='analysis' for j in row['jobs']),1)
        self.a.post(self.base+'/'+cid,headers=HEADERS,json={'revision':1,'fields':{'summary':'人工意见优先'}})
        prepared={'images':[],'transcript':'','transcript_source':'','warnings':['无画面']}
        fake={'fields':{k:'' for k in FIELDS},'evidence':{'summary':'标题推断'},'tags':['工具'],'uncertainties':[]};fake['fields'].update(summary='AI初填',expression='仅标题内容线索，待回看',hook_example='伪造原句',transcript_en='fake')
        with patch('video_case_analysis.prepare',return_value=prepared),patch('video_case_analysis.request',return_value=fake),patch('asr.configured_key',return_value='fake'):
            service.tick();service.tick()
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['human']['summary'],'人工意见优先');self.assertNotIn('summary',row['ai']['fields']);self.assertEqual(row['fields']['summary']['value'],'人工意见优先');self.assertEqual(row['ai']['fields']['hook_example'],'');self.assertEqual(row['review_status'],'待审核')
        review={'revision':row['revision'],'ai_generated':row['ai']['generated_at']}
        self.assertEqual(self.a.post(self.base+'/'+cid+'/review',headers=HEADERS,json=review).status_code,200)
        self.assertEqual(self.a.get(self.base+'/'+cid).json()['review_status'],'已审核')
        self.assertEqual(self.b.post(self.base+'/'+cid+'/review',headers=HEADERS,json={**review,'ai_generated':0}).status_code,409)

    def test_auto_metadata_failure_continues_independent_media_not_data_retry(self):
        cid=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456788'],'auto_process':True,'confirm_automation':True,'share_with_team':True}).json()['items'][0]['id']
        service=self.app.state.video_cases
        with patch.object(service.monitor,'request',side_effect=ValueError('Apify failed')) as upstream:
            service.tick('media');self.assertEqual(upstream.call_count,1)
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(len(row['jobs']),2);self.assertEqual(next(j for j in row['jobs'] if j['kind']=='analysis')['state'],'queued')
        prepared={'images':[],'transcript':'','transcript_source':'','warnings':['无媒体']}
        with patch('video_case_analysis.prepare',return_value=prepared),patch('video_case_analysis.request') as ai,patch('asr.configured_key',return_value='fake'):
            service.tick();ai.assert_not_called()
        row=self.a.get(self.base+'/'+cid).json();self.assertTrue(all(j['state']=='attention' for j in row['jobs']));self.assertFalse(row['ai'])

    def test_notes_only_ai_is_data_insufficient_not_reviewable(self):
        import time
        cid=self.add()
        with self.app.state.hub.db() as db:db.execute('UPDATE video_cases SET ai=? WHERE id=?',(json.dumps({'fields':{'notes':'无证据'},'generated_at':time.time()}),cid))
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['review_status'],'数据不足')
        self.assertEqual(self.a.post(self.base+'/'+cid+'/review',headers=HEADERS,json={'revision':row['revision'],'ai_generated':row['ai']['generated_at']}).status_code,400)

    def test_no_agnes_key_does_not_charge_video_endpoint(self):
        cid=self.add();service=self.app.state.video_cases
        with self.app.state.hub.db() as db:case=dict(db.execute('SELECT * FROM video_cases WHERE id=?',(cid,)).fetchone())
        with patch('asr.configured_key',return_value=''),patch('video_case_analysis.prepare') as prepare,self.assertRaises(ValueError):
            service.analysis({'id':'unconfigured'},case)
        prepare.assert_not_called()

    def test_asr_is_retained_when_later_ai_call_fails(self):
        cid=self.add();service=self.app.state.video_cases
        prepared={'images':[],'transcript':'已提取的真实口播','transcript_source':'test-asr','warnings':[]}
        with self.app.state.hub.db() as db:case=dict(db.execute('SELECT * FROM video_cases WHERE id=?',(cid,)).fetchone())
        with patch('asr.configured_key',return_value='fake'),patch('video_case_analysis.prepare',return_value=prepared),patch('video_case_analysis.request',side_effect=ValueError('AI失败')),self.assertRaises(ValueError):
            service.analysis({'id':'asr-retention'},case)
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['transcript'],'已提取的真实口播');self.assertFalse(row['ai'])

if __name__=='__main__':unittest.main()
