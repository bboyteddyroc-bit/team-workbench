import json
import unittest
from unittest.mock import patch
import test_hub as fixtures
import test_editor
from ai_editing import Unknown

class ConversationTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    account=fixtures.HubTests.account
    enqueue=fixtures.HubTests.enqueue
    sample=test_editor.EditorTests.sample

    def create(self):
        r=self.member.post('/api/ai-edit/conversations',json={'request_key':'conversation-create-1'},headers=fixtures.H)
        self.assertEqual(r.status_code,200,r.text)
        self.pid=r.json()['id'];self.url='/api/ai-edit/projects/'+self.pid
        return r.json()
    def get(self):return self.member.get(self.url).json()
    def ready(self,source=True):
        p=self.create()
        if source:
            self.tid=self.sample()
            r=self.member.post(self.url+'/conversation-sources',json={'revision':p['revision'],'sources':[self.tid]},headers=fixtures.H)
            self.assertEqual(r.status_code,200,r.text);p=r.json()
            upload=self.member.post('/api/editor/footage',content=(self.hub.media/(self.tid+'.mp4')).read_bytes(),headers={**fixtures.H,'X-File-Name':'test.mp4'})
            self.assertEqual(upload.status_code,200,upload.text);self.tid2=upload.json()['id']
            p=self.member.post(self.url+'/conversation-sources',json={'revision':p['revision'],'sources':[self.tid,self.tid2]},headers=fixtures.H).json()
        reply={'reply':'确认：3秒竖屏英文产品演示，保留原声，请点最终确认。','brief':{'product':'挂烫机','audience':'出门前整理衣物','reason':'演示使用','facts':'','avoid':'不夸大','target':3,'ratio':'9:16','language':'en','sound':'original'},'instructions':'自然节奏，保留原声，不夸大。','missing':[],'ready':True}
        with patch('asr.configured_key',return_value='fixture-key'),patch('ai_edit_conversation.request_json',return_value=reply):
            r=self.member.post(self.url+'/discuss',json={'revision':p['revision'],'request_key':'discussion-request-1','message':'按这些要求做','consent':True},headers=fixtures.H)
            self.assertEqual(r.status_code,200,r.text);self.app.state.ai_editing.tick()
        p=self.get();self.assertEqual(p['jobs'][0]['state'],'ready',p);return p
    def submit(self,p,key='execute-request-1',**extra):
        with patch('asr.configured_key',return_value='fixture-key'):
            return self.member.post(self.url+'/execute',json={'revision':p['revision'],'request_key':key,'confirmation_hash':p['body']['confirmation_hash'],'consent':True,**extra},headers=fixtures.H)
    def analysis(self):
        service=self.app.state.ai_editing
        with self.hub.db() as db:owner=db.execute('SELECT owner FROM ai_edit_projects WHERE id=?',(self.pid,)).fetchone()['owner']
        return [{**s,'language':'en','segments':[],'frames':[],'warning':'测试视频没有音轨'} for s in service.sources([self.tid,self.tid2],owner,False)]
    def plan(self,p,end=1.5,repeat=True):
        raw={'summary':'模拟方案，不发送外部请求','shots':[{'source_id':self.tid,'start':0,'end':end,'title':'','purpose':'演示','reason':'人工测试'}],'risks':[]}
        if repeat:raw['shots'].append({**raw['shots'][0],'source_id':self.tid2})
        return self.app.state.ai_editing.validate_plan(raw,{**p['body'],'source_info':self.analysis()})

    def test_no_work_before_confirmation_and_no_source_required_for_chat(self):
        with patch.object(self.app.state.ai_editing,'analyze') as analyze,patch.object(self.app.state.ai_editing,'plan') as plan:
            p=self.ready(False)
            self.assertTrue(p['body']['requirements_ready']);analyze.assert_not_called();plan.assert_not_called()
            self.assertEqual(self.submit(p).status_code,400)
        self.assertEqual(self.member.get('/api/editor/projects').json(),[])
        self.assertEqual(self.admin.get(self.url).status_code,404)

    def test_single_confirmation_to_real_export_and_replay(self):
        p=self.ready();r=self.submit(p);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.submit(p).json()['id'],r.json()['id'])
        service=self.app.state.ai_editing
        with patch.object(service,'analyze',return_value=self.analysis()) as analyze,patch.object(service,'plan',return_value=self.plan(p)) as plan:
            service.tick();service.tick();self.assertEqual(analyze.call_count,1);self.assertEqual(plan.call_count,1)
        p=self.get();self.assertEqual(p['jobs'][0]['state'],'ready',p)
        self.assertEqual(p['body']['export_status']['state'],'queued',p)
        self.assertEqual(len(self.member.get('/api/editor/projects').json()),1)
        self.app.state.editor.tick()
        p=self.get();self.assertEqual(p['body']['export_status']['state'],'ready',p)
        response=self.member.get('/api/editor/exports/'+p['body']['export_id']+'/video');self.assertEqual(response.status_code,200);self.assertGreater(len(response.content),1000)
        self.assertEqual(self.submit(p,'new-execution-key').status_code,200)
        self.assertEqual(len(self.member.get('/api/editor/projects').json()),1)

    def test_duration_mismatch_pauses_without_project_or_export(self):
        p=self.ready();self.assertEqual(self.submit(p).status_code,200)
        service=self.app.state.ai_editing
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=self.plan(p,end=.75,repeat=False)):
            service.tick()
        p=self.get();self.assertEqual(p['body']['execution_status'],'needs_review',p)
        self.assertNotIn('export_id',p['body']);self.assertEqual(self.member.get('/api/editor/projects').json(),[])
        self.assertEqual(self.submit(p,'new-execution-key').status_code,409)

    def test_new_requirement_same_plan_preserves_old_project(self):
        p=self.ready();self.assertEqual(self.submit(p).status_code,200)
        service=self.app.state.ai_editing
        candidate=self.plan(p)
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=candidate):service.tick()
        first=self.get();eid=first['body']['edit_project_id']
        reply={'reply':'新的节奏要求已记录，请最终确认。','brief':first['body']['brief'],'instructions':'换更自然的节奏，其他不变','missing':[],'ready':True}
        with patch('asr.configured_key',return_value='fixture-key'),patch('ai_edit_conversation.request_json',return_value=reply):
            r=self.member.post(self.url+'/discuss',json={'revision':first['revision'],'request_key':'discussion-new-requirement','message':'换更自然的节奏','consent':True},headers=fixtures.H)
            self.assertEqual(r.status_code,200,r.text)
            self.assertFalse(self.get()['body']['requirements_ready'])
            service.tick()
        p=self.get();self.assertEqual(self.submit(p,'execute-new-requirement').status_code,200)
        self.assertNotIn('export_id',self.get()['body'])
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',return_value=candidate):service.tick()
        p=self.get();self.assertEqual(p['jobs'][0]['state'],'ready',p)
        self.assertNotEqual(eid,p['body']['edit_project_id'])
        self.assertEqual(len(self.member.get('/api/editor/projects').json()),2)

    def test_changed_sources_require_new_conversation_confirmation(self):
        p=self.ready()
        r=self.member.post(self.url+'/conversation-sources',json={'revision':p['revision'],'sources':[]},headers=fixtures.H)
        self.assertEqual(r.status_code,200,r.text)
        self.assertFalse(r.json()['body']['requirements_ready'])
        self.assertEqual(self.submit(r.json()).status_code,400)

    def test_binding_consent_cancel_and_unknown_no_retry(self):
        p=self.ready()
        self.assertEqual(self.submit(p,confirmation_hash='stale').status_code,409)
        self.assertEqual(self.submit(p,consent=False).status_code,400)
        self.assertEqual(self.submit(p).status_code,200)
        self.member.post(self.url+'/cancel',json={},headers=fixtures.H)
        self.assertEqual(self.get()['jobs'][0]['state'],'cancelled')
        p=self.get();self.assertEqual(self.submit(p,'execute-after-cancel').status_code,200)
        service=self.app.state.ai_editing
        with patch.object(service,'analyze',return_value=self.analysis()),patch.object(service,'plan',side_effect=Unknown('模拟网络结果未知')) as call:
            service.tick();service.tick();self.assertEqual(call.call_count,1)
        p=self.get();self.assertEqual(p['jobs'][0]['state'],'unknown',p)
        self.assertEqual(self.submit(p,'execute-after-unknown').status_code,409)

if __name__=='__main__':unittest.main()
