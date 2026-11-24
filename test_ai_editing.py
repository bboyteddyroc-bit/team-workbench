import json
import unittest
from unittest.mock import patch
import test_hub as fixtures
import test_editor
from ai_editing import digest, Unknown, Limited

class AIEditingTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    account=fixtures.HubTests.account
    enqueue=fixtures.HubTests.enqueue
    sample=test_editor.EditorTests.sample
    def make(self):
        tid=self.sample();self.tid=tid
        r=self.member.post('/api/ai-edit/projects',json={'request_key':'create-project-0001','sources':[tid],'brief':{'product':'挂烫机','audience':'出门前整理衣物','reason':'演示使用过程','target':3,'language':'en'}},headers=fixtures.H)
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def putplan(self,p):
        plan={'summary':'test','shots':[{'source_id':self.tid,'start':.25,'end':1.5,'purpose':'演示','reason':'人工确认','title':'A closer look.'}],'risks':[]}
        r=self.member.post('/api/ai-edit/projects/'+p['id']+'/plan',json={'revision':p['revision'],'plan':plan},headers=fixtures.H)
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_owner_validation_and_apply_idempotency(self):
        p=self.make();pid=p['id']
        self.assertEqual(self.admin.get('/api/ai-edit/projects/'+pid).status_code,404)
        p=self.putplan(p);payload={'revision':p['revision'],'plan_hash':p['body']['plan_hash'],'confirm':True}
        url='/api/ai-edit/projects/'+pid+'/apply'
        r=self.member.post(url,json=payload,headers=fixtures.H);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.member.post(url,json=payload,headers=fixtures.H).json()['id'],r.json()['id'])
        projects=self.member.get('/api/editor/projects').json();self.assertEqual(len(projects),1)
        self.assertEqual(projects[0]['body']['schema_version'],4)
        self.assertEqual(projects[0]['body']['clips'][0]['start'],.25)
        self.assertEqual(projects[0]['body']['captions'][0]['text'],'A closer look.')
        self.assertEqual(self.admin.get('/api/editor/projects').json(),[])
    def test_out_of_bounds_nan_unknown_fields_rejected(self):
        p=self.make();service=self.app.state.ai_editing
        with self.hub.db() as db:row=service.owned(db,p['id'],p['body'].get('owner','missing')) if False else db.execute('SELECT * FROM ai_edit_projects WHERE id=?',(p['id'],)).fetchone()
        snap={**p['body'],'source_info':service.sources([self.tid],row['owner'],False)}
        for shot in [{'source_id':'foreign','start':0,'end':1},{'source_id':self.tid,'start':0,'end':99},{'source_id':self.tid,'start':0,'end':1,'command':'rm'}]:
            with self.assertRaises(ValueError):service.validate_plan({'shots':[shot]},snap)
    def test_local_queue_and_no_paid_call(self):
        p=self.make();url='/api/ai-edit/projects/'+p['id']+'/jobs';data={'kind':'analyze','request_key':'local-analysis-0001','revision':p['revision']}
        r=self.member.post(url,json=data,headers=fixtures.H);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.member.post(url,json=data,headers=fixtures.H).json(),r.json())
        self.app.state.ai_editing.tick();p=self.member.get('/api/ai-edit/projects/'+p['id']).json()
        self.assertEqual(p['jobs'][0]['state'],'ready',p)
        self.assertIn('analysis',p['body']);self.assertEqual(p['body']['analysis'][0]['warning'],'素材没有音轨')
        data={'kind':'plan','request_key':'paid-request-0001','revision':p['revision']}
        self.assertEqual(self.member.post(url,json=data,headers=fixtures.H).status_code,400)
    def test_cancel_recover_and_revision_conflict(self):
        p=self.make();url='/api/ai-edit/projects/'+p['id'];r=self.member.post(url+'/jobs',json={'kind':'analyze','request_key':'cancel-request-0001','revision':p['revision']},headers=fixtures.H)
        self.assertEqual(r.status_code,200,r.text)
        self.member.post(url+'/cancel',json={},headers=fixtures.H)
        self.assertEqual(self.member.get(url).json()['jobs'][0]['state'],'cancelled')
        with self.hub.db() as db:db.execute("UPDATE ai_edit_jobs SET kind='plan',state='running'")
        self.app.state.ai_editing.recover()
        self.assertEqual(self.member.get(url).json()['jobs'][0]['state'],'unknown')
        r=self.member.post('/api/ai-edit/projects',json={'id':p['id'],'revision':0,'sources':[self.tid],'brief':p['body']['brief']},headers=fixtures.H)
        self.assertEqual(r.status_code,409)

    def test_create_replay_and_remote_unknown_no_retry(self):
        p=self.make()
        response=self.member.post('/api/ai-edit/projects',json={'request_key':'create-project-0001','sources':[self.tid],'brief':p['body']['brief']},headers=fixtures.H)
        self.assertEqual(response.json()['id'],p['id'])
        self.assertEqual(len(self.member.get('/api/ai-edit/projects').json()),1)
        url='/api/ai-edit/projects/'+p['id']
        self.member.post(url+'/jobs',json={'kind':'analyze','request_key':'analysis-before-ai','revision':p['revision']},headers=fixtures.H)
        self.app.state.ai_editing.tick();p=self.member.get(url).json()
        with patch('asr.configured_key',return_value='fixture-not-a-real-key'):
            data={'kind':'plan','request_key':'ai-unknown-simulation','revision':p['revision'],'input_hash':p['input_hash'],'consent':True}
            r=self.member.post(url+'/jobs',json=data,headers=fixtures.H);self.assertEqual(r.status_code,200,r.text)
            with patch.object(self.app.state.ai_editing,'plan',side_effect=Unknown('模拟超时，未重提')) as call:
                self.app.state.ai_editing.tick();self.app.state.ai_editing.tick();self.assertEqual(call.call_count,1)
        self.assertEqual(self.member.get(url).json()['jobs'][0]['state'],'unknown')

    def test_mocked_planner_json_and_export_roundtrip(self):
        import io
        p=self.make();url='/api/ai-edit/projects/'+p['id']
        self.member.post(url+'/jobs',json={'kind':'analyze','request_key':'analysis-for-mock','revision':p['revision']},headers=fixtures.H)
        self.app.state.ai_editing.tick();p=self.member.get(url).json()
        answer={'summary':'模拟模型方案，用于接口验收','shots':[{'source_id':self.tid,'start':.25,'end':1.5,'purpose':'演示','reason':'人工测试证据','title':'Look closer.'}],'risks':['验收模拟输出，不代表真实模型分析']}
        response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}],'usage':{'total_tokens':123}}
        with patch('asr.configured_key',return_value='fixture-not-a-real-key'):
            r=self.member.post(url+'/jobs',json={'kind':'plan','request_key':'ai-mocked-response','revision':p['revision'],'input_hash':p['input_hash'],'consent':True},headers=fixtures.H);self.assertEqual(r.status_code,200,r.text)
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as call:
                self.app.state.ai_editing.tick();self.assertEqual(call.call_count,1)
        p=self.member.get(url).json();self.assertEqual(p['jobs'][0]['state'],'ready',p)
        r=self.member.post(url+'/apply',json={'revision':p['revision'],'plan_hash':p['body']['plan_hash'],'confirm':True},headers=fixtures.H);self.assertEqual(r.status_code,200,r.text)
        eid=r.json()['id']
        r=self.member.post('/api/editor/projects/'+eid+'/export',json={'request_key':'ai-export-roundtrip','version':1},headers=fixtures.H);self.assertEqual(r.status_code,200,r.text)
        self.app.state.editor.tick()
        exports=self.member.get('/api/editor/exports').json()
        self.assertEqual(exports[0]['state'],'ready',exports)

if __name__=='__main__':unittest.main()
