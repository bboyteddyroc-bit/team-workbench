import json,unittest
from unittest.mock import patch
from test_kalodata_integration import Tests as Fixture, HEADERS
from video_consent import POLICY,approved

class ConsentRoutes(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    base='/api/intelligence/cases'
    def test_auto_consent_and_child(self):
        payload={'urls':['https://www.tiktok.com/@demo/video/123456799'],'auto_process':True,'confirm_automation':True,'share_with_team':True}
        self.assertEqual(self.a.post(self.base,headers=HEADERS,json=payload).status_code,400)
        payload.update(native_video_consent=True,native_video_policy=POLICY)
        r=self.a.post(self.base,headers=HEADERS,json=payload);self.assertEqual(r.status_code,200,r.text)
        cid=r.json()['items'][0]['id'];service=self.app.state.video_cases
        with self.app.state.hub.db() as db:
            parent=dict(db.execute("SELECT * FROM video_case_jobs WHERE case_id=?",(cid,)).fetchone())
        self.assertTrue(approved(parent['options']))
        service.queue_analysis(parent,{'id':cid})
        with self.app.state.hub.db() as db:
            child=db.execute("SELECT options FROM video_case_jobs WHERE case_id=? AND kind='analysis'",(cid,)).fetchone()
        self.assertTrue(approved(child['options']))
    def test_old_task_does_not_reach_media(self):
        cid=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789']}).json()['items'][0]['id']
        with self.app.state.hub.db() as db:case=dict(db.execute('SELECT * FROM video_cases WHERE id=?',(cid,)).fetchone())
        with patch('video_case_analysis.prepare') as prep,self.assertRaises(ValueError):self.app.state.video_cases.analysis({'id':'old','options':'{}'},case)
        prep.assert_not_called()
    def test_native_analysis_keeps_human_priority(self):
        from video_case_analysis import FIELDS
        cid=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789']}).json()['items'][0]['id']
        self.a.post(self.base+'/'+cid,headers=HEADERS,json={'revision':1,'fields':{'summary':'人工优先'}})
        with self.app.state.hub.db() as db:case=dict(db.execute('SELECT * FROM video_cases WHERE id=?',(cid,)).fetchone())
        prepared={'images':[],'transcript':'真实口播','transcript_source':'本地识别','warnings':[],'duration_seconds':4,'native_video_path':'test.mp4'}
        result={'fields':{k:'' for k in FIELDS},'tags':[],'evidence':{},'uncertainties':[]}
        result['fields']['summary']='AI 不应覆盖'
        with patch('asr.configured_key',return_value='test'),patch('video_case_analysis.prepare',return_value=prepared),patch('video_case_analysis.request_native_video',return_value=result) as call:
            service=self.app.state.video_cases
            with self.app.state.hub.db() as db:
                owner=case['created_by'];db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES('native-test',?,?,'analysis','running','native-test',1,1,?)",(cid,owner,json.dumps({'native_video_consent':True,'native_video_policy':POLICY})))
            service.analysis({'id':'native-test','options':json.dumps({'native_video_consent':True,'native_video_policy':POLICY})},case)
        self.assertTrue(call.call_args.kwargs['consent'])
        row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['fields']['summary']['value'],'人工优先');self.assertNotIn('summary',row['ai']['fields'])
    def test_manual_requires_consent_and_persists(self):
        cid=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789']}).json()['items'][0]['id']
        payload={'kind':'analysis','request_key':'manualtest123','confirm':True}
        self.assertEqual(self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json=payload).status_code,400)
        payload.update(native_video_consent=True,native_video_policy=POLICY)
        with patch('asr.configured_key',return_value='test'):
            r=self.a.post(self.base+'/'+cid+'/process',headers=HEADERS,json=payload)
        self.assertEqual(r.status_code,200,r.text)
        with self.app.state.hub.db() as db:row=db.execute('SELECT options FROM video_case_jobs WHERE id=?',(r.json()['id'],)).fetchone()
        self.assertTrue(approved(row['options']))
