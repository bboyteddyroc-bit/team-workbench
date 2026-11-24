import shutil
import unittest
from editor import run,probe
import multitrack
import test_hub as fixtures
import test_editor


class ExportRangeUnits(unittest.TestCase):
    def test_range_parsing_and_window(self):
        self.assertIsNone(multitrack.export_range(None))
        self.assertEqual(multitrack.export_range({'start':1,'end':3}),{'start':1.0,'end':3.0})
        self.assertEqual(multitrack.export_range({'start':.51,'end':1.49}),{'start':12/24,'end':36/24})
        for bad in ({'start':2,'end':2},{'start':-1,'end':2},{'start':'a','end':2},{'start':0,'end':float('inf')},[1,2],'x'):
            with self.assertRaises(ValueError,msg=str(bad)):multitrack.export_range(bad)
        self.assertEqual(multitrack.window({},5),(0.0,5))
        self.assertEqual(multitrack.window({'export_range':{'start':1,'end':3}},5),(1,3))
        self.assertEqual(multitrack.window({'export_range':{'start':1,'end':9}},5),(1,5))
        with self.assertRaises(ValueError):multitrack.window({'export_range':{'start':6,'end':8}},5)


class ExportRangeApi(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    account=fixtures.HubTests.account
    enqueue=fixtures.HubTests.enqueue
    sample=test_editor.EditorTests.sample

    def make(self,task,**extra):
        body={'ratio':'9:16','clips':[{'task_id':task,'start':0,'end':2,'at':0,'volume':1}],'captions':[]};body.update(extra)
        return self.member.post('/api/editor/projects',json={'title':'range','body':body},headers=fixtures.H)

    def export(self,project,key):
        response=self.member.post('/api/editor/projects/'+project['id']+'/export',json={'version':project['version'],'request_key':key},headers=fixtures.H)
        return response

    def finish(self,response):
        self.assertEqual(response.status_code,200,response.text);eid=response.json()['id'];self.app.state.editor.tick()
        job=next(j for j in self.member.get('/api/editor/exports').json() if j['id']==eid);self.assertEqual(job['state'],'ready',job)
        return self.app.state.editor.root/(eid+'.mp4')

    def test_range_persists_and_exports_only_the_selection(self):
        task=self.sample()
        saved=self.make(task,export_range={'start':.5,'end':1.5}).json()
        self.assertEqual(saved['body']['export_range'],{'start':.5,'end':1.5})
        self.assertEqual(self.member.get('/api/editor/projects').json()[0]['body']['export_range'],{'start':.5,'end':1.5})
        duration,streams=probe(self.finish(self.export(saved,'range-keep-selection')))
        self.assertAlmostEqual(duration,1.0,delta=.1)
        self.assertTrue(any(s['codec_type']=='audio' for s in streams))

    def test_actual_gpu_export(self):
        import os
        if os.environ.get('HUB_TEST_NVENC') != '1':self.skipTest('requires explicitly enabled NVIDIA hardware test')
        from unittest.mock import patch
        task=self.sample();saved=self.make(task,export_range={'start':0,'end':1}).json()
        original=multitrack.run_final_encode; used=[]
        def recording(*args,**kwargs):
            result=original(*args,**kwargs);used.append(result);return result
        with patch.object(multitrack,'run_final_encode',side_effect=recording):
            output=self.finish(self.export(saved,'gpu-integration-test'))
        self.assertEqual(used,['gpu'])
        duration,streams=probe(output)
        self.assertAlmostEqual(duration,1,delta=.1)
        self.assertTrue(any(s['codec_type']=='video' for s in streams))
        self.assertTrue(any(s['codec_type']=='audio' for s in streams))

    def test_range_without_selection_exports_everything(self):
        task=self.sample()
        saved=self.make(task).json();self.assertIsNone(saved['body']['export_range'])
        duration,_=probe(self.finish(self.export(saved,'range-none-selected-key')))
        self.assertAlmostEqual(duration,2.0,delta=.1)

    def test_range_is_clamped_to_the_timeline_end(self):
        task=self.sample()
        saved=self.make(task,export_range={'start':1.5,'end':6}).json()
        duration,_=probe(self.finish(self.export(saved,'range-clamp-end-key')))
        self.assertAlmostEqual(duration,.5,delta=.1)

    def test_invalid_and_out_of_bounds_ranges_are_rejected(self):
        task=self.sample()
        self.assertEqual(self.make(task,export_range={'start':1,'end':1}).status_code,400)
        self.assertEqual(self.make(task,export_range={'start':'x','end':1}).status_code,400)
        saved=self.make(task,export_range={'start':5,'end':8}).json()
        response=self.export(saved,'range-out-of-bounds')
        self.assertEqual(response.status_code,400,response.text)
        self.assertIn('选区',response.text)

    def test_range_with_captions_and_detached_audio_free_clip(self):
        task=self.sample()
        saved=self.make(task,captions=[{'text':'hi','start':.2,'end':1.8}],export_range={'start':1,'end':2}).json()
        duration,_=probe(self.finish(self.export(saved,'range-with-caption')))
        self.assertAlmostEqual(duration,1.0,delta=.1)

    def test_selected_export_isolated_and_preserves_project(self):
        task=self.sample()
        saved=self.make(task,clips=[{'task_id':task,'start':0,'end':2,'at':0,'volume':1},{'task_id':task,'start':0,'end':2,'at':3,'volume':1}],captions=[{'text':'one','start':.2,'end':1.0},{'text':'two','start':3.2,'end':4.0}]).json()
        selection={'clips':[1],'captions':[1],'audio_clips':[],'audio':False,'range':{'start':3,'end':5}}
        response=self.member.post('/api/editor/projects/'+saved['id']+'/export',json={'version':saved['version'],'request_key':'selected-export-test-1','selection':selection},headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text)
        with self.app.state.hub.db() as db:
            import json
            body=json.loads(db.execute('SELECT body FROM edit_exports WHERE id=?',(response.json()['id'],)).fetchone()[0])
        self.assertEqual(len(body['clips']),1);self.assertEqual(body['clips'][0]['at'],3)
        self.assertEqual([c['text'] for c in body['captions']],['two'])
        self.assertEqual(len(self.member.get('/api/editor/projects').json()[0]['body']['clips']),2)
        duration,_=probe(self.finish(response));self.assertAlmostEqual(duration,2,delta=.1)

    def test_range_skips_clips_outside_window(self):
        from unittest.mock import patch
        task=self.sample()
        saved=self.make(task,clips=[{'task_id':task,'start':0,'end':2,'at':0,'volume':1},{'task_id':task,'start':0,'end':2,'at':3,'volume':1}],export_range={'start':3,'end':5}).json()
        engine=self.app.state.editor; original=engine.source
        with patch.object(engine,'source',wraps=original) as source:
            duration,_=probe(self.finish(self.export(saved,'range-skip-outside-test')))
            # validate() may also inspect sources; rendering should not pre-encode the outside clip.
            self.assertAlmostEqual(duration,2,delta=.1)
        # Direct render isolates preprocessing from API validation.
        data=engine.validate(saved['body'],self.member.get('/api/me').json()['id'],False)
        with patch.object(engine,'source',wraps=original) as source:
            engine.render('range-direct-check',data,self.member.get('/api/me').json()['id'],False)
            self.assertEqual(source.call_count,1)

    def test_selection_invalid_index_is_rejected(self):
        task=self.sample();saved=self.make(task).json()
        for index in ([9],[-1],[True],[0,0],['0']):
            response=self.member.post('/api/editor/projects/'+saved['id']+'/export',json={'version':saved['version'],'request_key':'bad-selection-test-1','selection':{'clips':index,'range':{'start':0,'end':1}}},headers=fixtures.H)
            self.assertEqual(response.status_code,400,response.text)

if __name__=='__main__':
    unittest.main()
