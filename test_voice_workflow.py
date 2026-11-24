import json,shutil,unittest
from unittest.mock import patch
import test_editor as fixtures
from test_hub import H
from editor import run
import voice_catalog
from voice_completion import finish


class VoiceWorkflowTests(unittest.TestCase):
    setUp=fixtures.EditorTests.setUp
    tearDown=fixtures.EditorTests.tearDown
    login=fixtures.EditorTests.login
    account=fixtures.EditorTests.account
    enqueue=fixtures.EditorTests.enqueue
    sample=fixtures.EditorTests.sample
    project=fixtures.EditorTests.project

    def prepare(self):
        task=self.sample();body=self.project(task)
        body['body']['captions']=[{'text':'第二句','start':.8,'end':1.5},{'text':'第一句','start':0,'end':.7}]
        project=self.member.post('/api/editor/projects',json=body,headers=H).json()
        v=self.hub.voice;v.configure('admin',api_key='test',enabled=True)
        vid=v.save_voice('admin',{'name':'test','reference_id':'test'})
        payload={'source':'subtitles','voice_id':vid,'project_id':project['id'],'project_version':project['version'],
                 'auto_asset':True,'auto_timeline':True,'insert_at':.2,'request_key':'caption-job'}
        return project,payload

    def local_ready(self,jid,duration=.6):
        file=self.hub.voice.files/(jid+'.mp3')
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'sine=frequency=500:duration={duration}','-c:a','libmp3lame',str(file)])
        with self.hub.db() as db:db.execute("UPDATE voice_jobs SET state='ready',audio_path=?,duration=? WHERE id=?",(file.name,duration,jid))

    def test_subtitles_auto_asset_timeline_and_idempotent_completion(self):
        project,payload=self.prepare()
        reply=self.member.post('/api/voice/jobs',json=payload,headers=H)
        self.assertEqual(reply.status_code,200,reply.text);job=reply.json()['job']
        self.assertEqual(job['format'],'mp3');self.assertEqual(job['text'],'第一句\n第二句')
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT make_captions FROM voice_jobs WHERE id=?',(job['id'],)).fetchone()[0],0)
        self.local_ready(job['id'])
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No provider calls')):
            finish(self.hub.voice,job['id']);finish(self.hub.voice,job['id'])
        result=self.member.get('/api/voice/jobs/'+job['id']).json()['job']
        self.assertEqual(result['timeline_status'],'added');self.assertTrue(result['asset_id'])
        updated=self.member.get('/api/editor/projects').json()[0]
        self.assertEqual(updated['version'],project['version']+1)
        self.assertEqual(len(updated['body']['audio_clips']),1)
        self.assertEqual(updated['body']['captions'],project['body']['captions'])
        asset=self.member.get('/api/assets/'+result['asset_id'])
        self.assertEqual(asset.status_code,200);self.assertIn('audio/mpeg',asset.headers['content-type'])
        versions=self.member.get('/api/editor/projects/'+project['id']+'/versions').json()
        self.assertEqual(len(versions),2)

    def test_selected_and_conflict_does_not_overwrite(self):
        project,payload=self.prepare();payload['caption_indices']=[0]
        job=self.member.post('/api/voice/jobs',json=payload,headers=H).json()['job']
        self.assertEqual(job['text'],'第二句')
        project['title']='edited';self.member.post('/api/editor/projects',json=project,headers=H)
        self.local_ready(job['id']);finish(self.hub.voice,job['id'])
        result=self.member.get('/api/voice/jobs/'+job['id']).json()['job']
        self.assertEqual(result['timeline_status'],'needs_review');self.assertTrue(result['asset_id'])
        self.assertEqual(self.member.get('/api/editor/projects').json()[0]['body']['audio_clips'],[])

    def test_long_audio_saved_without_truncation(self):
        project,payload=self.prepare()
        job=self.member.post('/api/voice/jobs',json=payload,headers=H).json()['job']
        self.local_ready(job['id'],3);finish(self.hub.voice,job['id'])
        result=self.member.get('/api/voice/jobs/'+job['id']).json()['job']
        self.assertEqual(result['timeline_status'],'added');self.assertTrue(result['asset_id'])
        saved=self.member.get('/api/editor/projects').json()[0]
        self.assertAlmostEqual(saved['body']['audio_clips'][0]['end'],3,delta=.1)

    def test_catalog_query_favorites_and_sample(self):
        model={'_id':'abc123','title':'Clear voice','type':'tts','state':'trained','languages':['en'],
               'samples':[{'audio':'https://platform.r2.fish.audio/task/example.mp3'}]}
        self.hub.voice.configure('admin',api_key='test',enabled=True)
        with patch('voice_catalog.read_model',return_value={'items':[model],'has_more':True}) as upstream:
            reply=self.member.get('/api/voice/catalog?title=clear&language=en&page=2')
            self.assertEqual(reply.status_code,200,reply.text)
            self.assertEqual(upstream.call_args.kwargs['params']['language'],'en')
            self.assertEqual(upstream.call_args.kwargs['params']['page_number'],2)
        voice=reply.json()['voices'][0];self.assertTrue(voice['has_sample']);self.assertTrue(reply.json()['has_more'])
        self.member.post('/api/voice/voices/'+voice['id']+'/favorite',headers=H)
        items=self.member.get('/api/voice/voices').json()['voices']
        self.assertTrue(next(v for v in items if v['id']==voice['id'])['favorite'])
        self.assertEqual(next(v for v in items if v['id']==voice['id'])['sample_url'],'/api/voice/voices/'+voice['id']+'/sample')
        self.assertFalse(any(v['favorite'] for v in self.admin.get('/api/voice/voices').json()['voices']))
        with patch('voice_catalog.fetch_sample',return_value=(b'ID3-test','audio/mpeg')) as fetch:
            response=self.member.get('/api/voice/voices/'+voice['id']+'/sample')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.content,b'ID3-test')
            fetch.assert_called_once_with(model['samples'][0]['audio'])
        with patch('voice_catalog.fetch_sample',side_effect=ValueError('network failure')):
            self.assertEqual(self.member.get('/api/voice/voices/'+voice['id']+'/sample').status_code,502)
        with self.assertRaises(ValueError):voice_catalog.fetch_sample('http://127.0.0.1/secret')
        model['samples']=[{'audio':'http://127.0.0.1/secret'}]
        self.assertFalse(voice_catalog.normalize(model)['has_sample'])
