"""P0 contract: real persistence and access control, no TikTok generation."""
import unittest
import hashlib
import shutil
import test_editor
from test_hub import H


class WorkspaceTests(unittest.TestCase):
    setUp=test_editor.EditorTests.setUp
    tearDown=test_editor.EditorTests.tearDown
    login=test_editor.EditorTests.login
    account=test_editor.EditorTests.account
    enqueue=test_editor.EditorTests.enqueue
    sample=test_editor.EditorTests.sample
    project=test_editor.EditorTests.project
    def test_material_categories_and_selected_reference_draft(self):
        task=self.sample()
        a=self.member.post('/api/media/extract',json={'source_id':task,'kind':'frame','time':.2},headers=H).json()
        b=self.member.post('/api/media/extract',json={'source_id':task,'kind':'frame','time':.6},headers=H).json()
        url='/api/workspace/materials/'+a['id']
        self.assertEqual(self.member.post(url,json={'name':'产品正面','category':'product'},headers=H).status_code,200)
        self.assertEqual(self.admin.post(url,json={'name':'覆盖','category':'scene'},headers=H).status_code,404)
        self.assertEqual(self.member.post(url,json={'name':'测试','category':'invalid'},headers=H).status_code,400)
        found=next(x for x in self.member.get('/api/workspace/materials').json() if x['id']==a['id'])
        self.assertEqual((found['name'],found['category']),('产品正面','product'))
        draft=dict(source_id=task,project_id=None,frame_time=.2,frame_id=a['id'],model='auto',mode='omni',
                   duration=5,prompt='使用 @图片3',inherit=True,reference_ids=[b['id']],reference_tokens={b['id']:'图片3'})
        self.assertEqual(self.member.post('/api/workspace/continuation',json=draft,headers=H).status_code,200)
        saved=self.member.get('/api/workspace/continuation').json()
        self.assertEqual(saved['reference_ids'],[b['id']])
        self.assertEqual(saved['reference_tokens'],{b['id']:'图片3'})
        draft['reference_ids']=['missing']
        self.assertEqual(self.member.post('/api/workspace/continuation',json=draft,headers=H).status_code,400)
        self.assertEqual(self.admin.get('/api/workspace/materials').json(),[])
    def test_association_draft_and_reopen(self):
        task = self.sample()
        data = self.project(task)
        data['body']['target_duration'] = 45
        saved = self.member.post('/api/editor/projects', json=data, headers=H).json()
        self.assertEqual(saved['body']['target_duration'],45)
        links = self.member.get('/api/workspace/links').json()
        self.assertEqual(links[0]['task_id'],task)
        self.assertEqual(links[0]['project_id'],saved['id'])
        self.assertEqual(self.admin.get('/api/workspace/links').json(),[])
        draft = dict(source_id=task,project_id=saved['id'],frame_time=1.5,model='auto',mode='omni',
                     duration=5,prompt='下一段',inherit=True,add_library=True,append_timeline=False)
        response = self.member.post('/api/workspace/continuation',json=draft,headers=H)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.member.get('/api/workspace/continuation').json()['frame_time'],1.5)
        self.assertIsNone(self.admin.get('/api/workspace/continuation').json())
        reopened = self.member.get('/api/editor/projects').json()[0]
        self.assertEqual(reopened['body'],saved['body'])
        before = len(self.member.get('/api/tasks').json())
        draft['frame_time']=100
        self.assertEqual(self.member.post('/api/workspace/continuation',json=draft,headers=H).status_code,400)
        self.assertEqual(len(self.member.get('/api/tasks').json()),before)

    def test_cross_owner_project_rejected_and_old_project_supported(self):
        task=self.sample()
        saved=self.member.post('/api/editor/projects',json=self.project(task),headers=H).json()
        self.assertEqual(saved['body']['target_duration'],30)
        denied=self.admin.post('/api/workspace/link',json={'task_id':task,'project_id':saved['id']},headers=H)
        self.assertEqual(denied.status_code,404)
        payload={'account_id':'pool','request_key':'workspace-enqueue-123456','project_id':saved['id'],
                 'items':[{'prompt':'test','duration':5,'count':1,'mode':'omni','model':'5000005','assets':[]}]}
        self.assertEqual(self.admin.post('/api/tasks',json=payload,headers=H).status_code,404)
        response=self.member.post('/api/tasks',json=payload,headers=H)
        self.assertEqual(response.status_code,200,response.text)
        task_id=response.json()['id']
        self.assertTrue(any(l['task_id']==task_id for l in self.member.get('/api/workspace/links').json()))
        # Idempotent submission does not create a duplicate association.
        self.assertEqual(self.member.post('/api/tasks',json=payload,headers=H).json(),response.json())

    def test_real_reference_frames_cache_and_source_permissions(self):
        task=self.sample();path=self.hub.media/(task+'.mp4');before=hashlib.sha256(path.read_bytes()).hexdigest()
        response=self.member.post('/api/media/extract',json={'source_id':task,'kind':'frame','time':1.2},headers=H)
        self.assertEqual(response.status_code,200,response.text);frame=response.json()
        self.assertTrue((self.hub.assets/frame['id']).read_bytes().startswith(b'\x89PNG'))
        self.assertEqual(self.member.post('/api/media/extract',json={'source_id':task,'kind':'frame','time':1.2},headers=H).json()['id'],frame['id'])
        self.assertEqual(self.admin.get('/api/assets/'+frame['id']).status_code,404)
        self.assertEqual(self.member.post('/api/media/extract',json={'source_id':task,'kind':'audio','start':0,'end':1},headers=H).status_code,400)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
        self.assertEqual(len(self.provider.created),0)
        info=self.member.get('/api/media/source/'+task).json()
        self.assertFalse(info['has_audio'])
        account=self.admin.get('/api/accounts').json()[0]['id']
        other=self.enqueue(self.admin,account,key='other-owner-request').json()['id']
        with self.hub.db() as db:db.execute("UPDATE tasks SET state='ready' WHERE id=?",(other,))
        shutil.copyfile(path,self.hub.media/(other+'.mp4'))
        self.assertEqual(self.member.post('/api/media/extract',json={'source_id':other,'kind':'frame','time':0},headers=H).status_code,400)
        self.assertEqual(self.member.post('/api/media/extract',json={'source_id':'../vault.key','kind':'frame','time':0},headers=H).status_code,400)

    def test_real_audio_and_reference_draft(self):
        from editor import run,probe
        task=self.sample();path=self.hub.media/(task+'.mp4')
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=green:s=160x240:r=24:d=2',
             '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-threads','1','-c:a','aac','-shortest',str(path)])
        source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
        response=self.member.post('/api/media/extract',json={'source_id':task,'kind':'audio','start':.2,'end':1.7},headers=H)
        self.assertEqual(response.status_code,200,response.text);audio=response.json()
        self.assertAlmostEqual(probe(self.hub.assets/audio['id'])[0],1.5,delta=.1)
        frame=self.member.post('/api/media/extract',json={'source_id':task,'kind':'frame','time':1},headers=H).json()
        draft=dict(source_id=task,frame_time=1,frame_id=frame['id'],audio_id=audio['id'],model='auto',mode='omni',duration=5,prompt='next')
        result=self.member.post('/api/workspace/continuation',json=draft,headers=H)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.member.get('/api/workspace/continuation').json()['audio_id'],audio['id'])
        self.assertEqual(self.admin.post('/api/workspace/continuation',json=draft,headers=H).status_code,400)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),source_hash)
        saved=self.member.post('/api/editor/projects',json=self.project(task),headers=H).json()
        summary=self.member.get('/api/workspace/overview').json()
        self.assertEqual(summary[0]['id'],saved['id'])
        self.assertEqual(summary[0]['tasks'][0]['id'],task)
        self.assertEqual(self.admin.get('/api/workspace/overview').json(),[])
        self.assertEqual(len(self.admin.get('/api/workspace/materials').json()),0)

    def test_continuation_uses_existing_queue_and_appends_once(self):
        from workspace import append_completed
        task=self.sample();self.hub.reference_enabled=True
        frame=self.member.post('/api/media/extract',json={'source_id':task,'kind':'frame','time':1},headers=H).json()
        project=self.member.post('/api/editor/projects',json=self.project(task),headers=H).json()
        item=dict(prompt='next shot',model='5000005',mode='frames',duration=5,count=1,
                  assets=[{'id':frame['id'],'role':'first','token':'图片1'}],
                  continuation={'source_id':task,'frame_id':frame['id'],'append_timeline':True})
        payload={'account_id':'pool','project_id':project['id'],'request_key':'continuation-unique-request','items':[item]}
        response=self.member.post('/api/tasks',json=payload,headers=H)
        self.assertEqual(response.status_code,200,response.text);tid=response.json()['id']
        self.assertEqual(self.member.post('/api/tasks',json=payload,headers=H).json(),response.json())
        self.assertEqual(len(self.provider.created),0)
        shutil.copyfile(self.hub.media/(task+'.mp4'),self.hub.media/(tid+'.mp4'))
        with self.hub.db() as db:db.execute("UPDATE tasks SET state='ready' WHERE id=?",(tid,))
        append_completed(self.hub,tid);append_completed(self.hub,tid)
        updated=self.member.get('/api/editor/projects').json()[0]
        self.assertEqual(len(updated['body']['clips']),3)
        self.assertEqual(updated['version'],project['version']+1)
        self.assertEqual(updated['body']['clips'][-1]['task_id'],tid)
        self.assertEqual(self.member.post('/api/editor/projects',json=project,headers=H).status_code,409)
        item['continuation']['frame_id']='invalid'
        payload['request_key']='continuation-invalid-request'
        self.assertEqual(self.member.post('/api/tasks',json=payload,headers=H).status_code,400)

    def test_engineering_versions_are_private_and_restore_as_new(self):
        task=self.sample()
        first=self.member.post('/api/editor/projects',json=self.project(task),headers=H).json()
        changed={**first,'title':'修改后的项目','body':{**first['body'],'clips':first['body']['clips'][:1]}}
        # Keep subtitles within the shortened timeline.
        changed['body']['captions']=[]
        second=self.member.post('/api/editor/projects',json=changed,headers=H).json()
        url='/api/editor/projects/'+first['id']
        versions=self.member.get(url+'/versions').json()
        self.assertEqual([v['version'] for v in versions],[2,1])
        self.assertEqual(self.admin.get(url+'/versions').status_code,404)
        self.assertEqual(self.admin.post(url+'/restore',json={'version':1,'expected_version':2},headers=H).status_code,404)
        stale=self.member.post(url+'/restore',json={'version':1,'expected_version':1},headers=H)
        self.assertEqual(stale.status_code,409)
        restored=self.member.post(url+'/restore',json={'version':1,'expected_version':2},headers=H)
        self.assertEqual(restored.status_code,200,restored.text)
        self.assertEqual(restored.json()['version'],3)
        self.assertEqual(restored.json()['body'],first['body'])
        self.assertEqual([v['version'] for v in self.member.get(url+'/versions').json()],[3,2,1])
        self.assertTrue((self.hub.media/(task+'.mp4')).is_file())
