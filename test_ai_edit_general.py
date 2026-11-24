import copy,json,unittest
from unittest.mock import patch
import test_ai_edit_conversation as base
import test_hub as fixtures
from ai_edit_requirements import clean_contract,blockers,compliance,SYSTEM,PLANNER
from ai_edit_vision import POLICY,clean_map,clean_review,overview_times,detail_times,queue_review
from ai_editing import Unknown

CONTRACT={'goal':'自然的生活记录，不要广告感','kind':'生活记录','scope':'new','must_keep':['保留完整内容'],'forbidden':['广告化标题'],'unchanged':[],'creative':['合理切点'],'acceptance':['完整且没有广告标题'],'pending':[],'unsupported':[],'captions':'none','titles':False,'ranges':[]}
REVIEW={'summary':'模拟采样复查，无真实收费调用','checks':[{'requirement':'没有新增标题','status':'pass','evidence':'实际采样图像及工程无标题'}],'blocking_issues':[],'uncertainties':['没有连续看完/听音，仍需用户核对']}

class GeneralTests(unittest.TestCase):
    setUp=base.ConversationTests.setUp
    tearDown=base.ConversationTests.tearDown
    login=base.ConversationTests.login
    account=base.ConversationTests.account
    enqueue=base.ConversationTests.enqueue
    sample=base.ConversationTests.sample
    create=base.ConversationTests.create
    get=base.ConversationTests.get
    ready=base.ConversationTests.ready
    submit=base.ConversationTests.submit
    analysis=base.ConversationTests.analysis
    plan=base.ConversationTests.plan

    def general(self,contract=None):
        p=self.ready();reply={'reply':'已理解自然生活记录，不套带货模板。请最终确认。','brief':{**p['body']['brief'],'product':'','audience':'','reason':''},'instructions':'自然生活记录；不添加标题和字幕。','contract':copy.deepcopy(contract or CONTRACT),'missing':[],'ready':True}
        with patch('asr.configured_key',return_value='fixture-key'),patch('ai_edit_conversation.request_json',return_value=reply):
            r=self.member.post(self.url+'/discuss',json={'revision':p['revision'],'request_key':'general-discussion','message':'桌面助理已总结并经我确认：自然生活记录，不要广告感，不加字幕标题。','consent':True},headers=fixtures.H)
            self.assertEqual(r.status_code,200,r.text);self.app.state.ai_editing.tick()
        return self.get()

    def start(self,p):return self.submit(p,inspection_authorized=True,inspection_policy=POLICY,duration_repair_authorized=True,execution_policy=p['body']['execution_policy'])
    def native_mapping(self):
        return {'initial':self.mapping(),'detail':None,'method':'native-video-audio-v2','native_video':True}
    def mapping(self):
        return {'understanding':'自然生活记录，不新增标题字幕','observations':[{'source_id':self.tid,'start':0,'end':1.5,'fact':'模拟观察','inference':'','uncertainty':'未连续观看'}],'inspect':[],'limitations':['模拟响应，仅验流程']}

    def test_general_summary_no_commerce_fields_required_and_authorization(self):
        p=self.general();self.assertTrue(p['body']['requirements_ready'],p)
        self.assertEqual(p['body']['contract']['kind'],'生活记录')
        self.assertEqual(self.submit(p).status_code,400)
        self.assertEqual(self.submit(p,inspection_authorized=True,inspection_policy='stale').status_code,409)
        self.assertEqual(self.start(p).status_code,200)

    def test_server_origin_ledger_and_final_adoption_are_bound_to_execution(self):
        from ai_edit_provenance import confirmed
        p=self.general();self.assertTrue(p['body']['requirement_ledger']['requirements'])
        self.assertTrue(all(r['authority']=='proposed' for r in p['body']['requirement_ledger']['requirements']))
        self.assertEqual(self.start(p).status_code,200)
        service=self.app.state.ai_editing
        with self.hub.db() as db:
            row=db.execute("SELECT input FROM ai_edit_jobs WHERE kind='execute' ORDER BY created DESC LIMIT 1").fetchone()
        snap=json.loads(row['input']);self.assertTrue(confirmed(snap))
        snap['contract']['goal']='未经用户确认的新目标';self.assertFalse(confirmed(snap))

    def test_partial_cannot_be_disguised_as_full_reedit(self):
        p=self.general({**CONTRACT,'scope':'partial','unchanged':['视频声音不变']})
        self.assertFalse(p['body']['requirements_ready']);self.assertTrue(p['body']['missing'])
        self.assertEqual(self.start(p).status_code,400)
        self.assertEqual(self.member.get('/api/editor/projects').json(),[])

    def test_whole_pipeline_real_export_then_actual_review(self):
        p=self.general();self.assertEqual(self.start(p).status_code,200)
        service=self.app.state.ai_editing
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=self.plan(p)),patch('ai_edit_native_video.inspect',return_value=self.native_mapping()),patch('ai_edit_vision.request',side_effect=[REVIEW,REVIEW]) as call:
            service.tick();p=self.get();self.assertEqual(p['body']['export_status']['state'],'queued',p)
            self.app.state.editor.tick();p=self.get();self.assertEqual(p['body']['export_status']['state'],'ready',p)
            self.assertEqual(p['body']['review_status'],'queued')
            service.tick();p=self.get();self.assertEqual(p['body']['review_status'],'reviewed',p)
            self.assertEqual(call.call_count,2)
            self.assertEqual(call.call_args.args[3]['phase'],'实际成片复查')
            self.assertTrue(call.call_args.args[4]);self.assertTrue(all(str(i[1]).endswith(p['body']['export_id']+'.mp4') for i in call.call_args.args[4]))
        project=self.member.get('/api/editor/projects').json()[0]
        self.assertEqual(project['body']['captions'],[])
        self.assertEqual(len(project['body']['clips']),2)
        self.assertEqual(len(p['body']['observations']),3)
        self.assertEqual(self.admin.get(self.url).status_code,404)

    def test_fine_inspection_unknown_preserves_known_map_no_retry(self):
        p=self.general();self.start(p);service=self.app.state.ai_editing
        from a6_video import VideoOutcomeUnknown
        responses=[json.dumps(self.mapping()),VideoOutcomeUnknown('第二条素材结果未知')]
        with patch('asr.configured_key',return_value='fixture-key'),patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan') as planner,patch('ai_edit_native_video.read_video',side_effect=responses) as call:
            service.tick();service.tick();self.assertEqual(call.call_count,2);planner.assert_not_called()
        p=self.get();self.assertEqual(p['jobs'][0]['state'],'unknown')
        self.assertIn('原生视频素材观察 '+self.tid,[o['name'] for o in p['body']['observations']]);self.assertNotIn('export_id',p['body'])

    def test_fine_inspection_is_bounded_and_passed_to_planner(self):
        p=self.general();self.start(p);service=self.app.state.ai_editing
        first=self.mapping();second=self.mapping();second['observations'][0]['source_id']=self.tid2
        with patch('asr.configured_key',return_value='fixture-key'),patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=self.plan(p)) as planner,patch('ai_edit_native_video.read_video',side_effect=[json.dumps(first),json.dumps(second)]) as call,patch('ai_edit_vision.request',return_value=REVIEW):
            service.tick();self.assertEqual(call.call_count,2)
            self.assertEqual({r['source_id'] for r in planner.call_args.args[0]['inspection']['initial']['observations']},{self.tid,self.tid2})
        self.assertIn('原生视频素材观察 '+self.tid,[o['name'] for o in self.get()['body']['observations']])

    def test_preflight_known_failure_uses_only_one_correction_then_export(self):
        p=self.general();self.start(p);service=self.app.state.ai_editing
        bad=copy.deepcopy(REVIEW);bad['checks'][0].update(requirement='广告化标题',requirement_id='forbidden:0',status='fail',basis='direct',violation_kind='observed_forbidden',relation={'type':'literal_presence','subject':'广告化标题'},evidence='本次0秒采样显示禁用标题（模拟证据）',evidence_refs=[{'kind':'frame','source_id':self.tid,'at':0}])
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=self.plan(p)) as planner,patch('ai_edit_native_video.inspect',return_value=self.native_mapping()),patch('ai_edit_vision.request',return_value=bad):
            service.tick();self.assertEqual(planner.call_count,2)
            self.assertIn('duration_repair',planner.call_args.args[0])
        p=self.get();self.assertEqual(len(p['body']['execution_candidates']),2)
        self.assertEqual(p['body']['export_status']['state'],'queued')

    def test_inferred_scene_audience_failure_does_not_spend_repair_or_block_export(self):
        p=self.general();self.start(p);service=self.app.state.ai_editing
        bad=copy.deepcopy(REVIEW)
        bad['checks']=[{'requirement':p['body']['contract']['goal'],'requirement_id':'goal','status':'fail','basis':'direct','evidence':'男性户外演示，推断不适合主妇','evidence_refs':[{'kind':'frame','source_id':self.tid,'at':0}]}]
        bad['blocking_issues']=['必须厨房场景（并非用户要求）']
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=self.plan(p)) as planner,patch('ai_edit_native_video.inspect',return_value=self.native_mapping()),patch('ai_edit_vision.request',return_value=bad):
            service.tick();self.assertEqual(planner.call_count,1)
        p=self.get();self.assertEqual(p['body']['export_status']['state'],'queued')
        checks=p['body']['preflight_review']['checks'];self.assertEqual(checks[0]['status'],'unknown')

    def test_deterministic_constraints_titles_and_source_ranges(self):
        p=self.general();snap={**p['body'],'source_info':self.analysis()};candidate=self.plan(p)
        candidate['shots'][0]['title']='unwanted'
        self.assertIn('要求不添加标题，但方案含新增标题',compliance(candidate,snap))
        snap['contract']['ranges']=[{'source_id':self.tid,'start':0,'end':1,'action':'exclude'}]
        self.assertIn('方案使用了明确禁止的源区间',compliance(candidate,snap))
        snap['contract']['ranges']=[{'source_id':self.tid,'start':0,'end':2,'action':'keep'}]
        self.assertIn('方案未完整保留指定源区间',compliance(candidate,snap))

    def test_export_review_failure_preserves_video_and_unknown_no_retry(self):
        p=self.general();self.start(p);service=self.app.state.ai_editing
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=self.plan(p)),patch('ai_edit_native_video.inspect',return_value=self.native_mapping()),patch('ai_edit_vision.request',side_effect=[REVIEW,Unknown('成片复查未知')]) as call:
            service.tick();self.app.state.editor.tick();service.tick();service.tick()
            self.assertEqual(call.call_count,2)
        p=self.get();self.assertEqual(p['jobs'][0]['state'],'unknown')
        self.assertEqual(p['body']['export_status']['state'],'ready')
        self.assertEqual(self.member.get('/api/editor/exports/'+p['body']['export_id']+'/video').status_code,200)

    def test_review_cannot_omit_required_checks_and_real_images_encode(self):
        import io
        from ai_edit_vision import request,review
        p=self.general();service=self.app.state.ai_editing
        self.start(p)
        with self.hub.db() as db:
            job=db.execute('SELECT * FROM ai_edit_jobs WHERE kind=\'execute\' ORDER BY created DESC').fetchone()
            owner=job['owner'];snap=json.loads(job['input'])
        response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(self.mapping())}}]}
        path=service.editor.source(owner,False,self.tid)
        with patch('asr.configured_key',return_value='fixture-key'),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as call:
            value=request(service,job['id'],'测试',{},[('source-test',path,0)])
            self.assertEqual(value['understanding'],self.mapping()['understanding'])
            body=json.loads(call.call_args.args[0].data)
            self.assertTrue(body['messages'][1]['content'][2]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        with patch('ai_edit_vision.request',return_value=REVIEW):
            value=review(service,{**snap,'plan':self.plan(p),'analysis':self.analysis()},owner,False,job['id'])
        self.assertTrue(any(c['requirement']==CONTRACT['goal'] and c['status']=='unknown' for c in value['checks']))

    def test_validators_and_sampling_caps(self):
        snap={'source_info':[{'id':'a','duration':20}]}
        raw={'understanding':'test','observations':[],'inspect':[{'source_id':'foreign','start':0,'end':1,'reason':'test'}]}
        with self.assertRaises(ValueError):clean_map(raw,snap)
        raw['inspect'][0]['source_id']='a';raw['inspect'][0]['end']=9
        with self.assertRaises(ValueError):clean_map(raw,snap)
        raw['inspect'][0]['end']=1
        with self.assertRaises(ValueError):clean_map(raw,snap,False)
        self.assertLessEqual(sum(len(overview_times(d,600)) for d in [596,1,1,1,1]),96)
        self.assertLessEqual(len(detail_times(0,8)),17)
        self.assertTrue(clean_review(REVIEW)['sampled_only'])
        self.assertIn('不默认带货',PLANNER)
        self.assertIn('不强制商品',SYSTEM)

if __name__=='__main__':unittest.main()
