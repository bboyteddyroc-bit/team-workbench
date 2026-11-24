import unittest, shutil, array
from editor import run, probe
from test_editor import EditorTests
import test_hub as fixtures

class IndependentTimelineTests(unittest.TestCase):
    setUp=EditorTests.setUp
    tearDown=EditorTests.tearDown
    login=EditorTests.login
    account=EditorTests.account
    enqueue=EditorTests.enqueue
    sample=EditorTests.sample

    def test_audio_without_video_and_beyond_video(self):
        tone=self.hub.directory/'independent.wav'
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=2','-c:a','pcm_s16le',str(tone)])
        upload=self.member.post('/api/assets',content=tone.read_bytes(),headers={**fixtures.H,'Content-Type':'audio/wav','X-File-Name':'tone.wav'}).json()
        task=self.sample()
        for with_video in (False,True):
            body={'clips':[{'task_id':task,'start':0,'end':.5,'volume':0}] if with_video else [],'captions':[], 'audio_clips':[{'source':'asset','asset_id':upload['id'],'start':0,'end':2,'at':.5,'volume':1,'locked':False}]}
            response=self.member.post('/api/editor/projects',json={'title':'Independent','body':body},headers=fixtures.H)
            self.assertEqual(response.status_code,200,response.text)
            saved=response.json()
            job=self.member.post('/api/editor/projects/'+saved['id']+'/export',json={'version':saved['version'],'request_key':'independent-export-'+str(with_video)},headers=fixtures.H)
            self.assertEqual(job.status_code,200,job.text)
            self.app.state.editor.tick()
            result=next(j for j in self.member.get('/api/editor/exports').json() if j['id']==job.json()['id'])
            self.assertEqual(result['state'],'ready',result)
            output=self.app.state.editor.root/(result['id']+'.mp4')
            self.assertAlmostEqual(probe(output)[0],2.5,delta=.15)
            pcm=array.array('h',run([shutil.which('ffmpeg'),'-v','error','-ss','1.8','-i',str(output),'-t','0.3','-vn','-ac','1','-ar','8000','-f','s16le','-']))
            self.assertGreater(sum(v*v for v in pcm)/len(pcm),10000)

    def test_caption_only_and_position_beyond_ten_minutes(self):
        response=self.member.post('/api/editor/projects',json={'title':'Long timeline','body':{'clips':[],'captions':[{'text':'Independent caption','start':720,'end':724}]}},headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['body']['captions'][0]['end'],724)
