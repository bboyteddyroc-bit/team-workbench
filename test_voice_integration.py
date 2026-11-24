"""Offline regression through the actual HTTP/save/export pipeline."""
import array
import json
import shutil
from unittest.mock import patch
from editor import run, probe
from test_editor import EditorTests
from test_hub import H


class VoiceIntegrationTests(EditorTests):
    def ready_voice(self, project_id):
        voice=self.hub.voice
        with self.hub.db() as db:
            owner=db.execute("SELECT id FROM users WHERE username='member'").fetchone()[0]
        voice.configure('admin',api_key='offline-test-key',enabled=True)
        vid=voice.save_voice('admin',{'name':'Offline','reference_id':'offline'})
        response=self.member.post('/api/voice/jobs',json={
            'voice_id':vid,'text':'本地测试','project_id':project_id,
            'insert_at':.4,'request_key':'offline-request'},headers=H)
        self.assertEqual(response.status_code,200,response.text)
        jid=response.json()['job']['id']
        path=voice.files/(jid+'.wav')
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i',
             'sine=frequency=660:duration=0.7','-c:a','pcm_s16le',str(path)])
        with self.hub.db() as db:
            db.execute("UPDATE voice_jobs SET state='ready',audio_path=?,duration=.7,captions=? WHERE id=?",
                       (path.name,json.dumps([{'text':'测试','start':0,'end':.6}]),jid))
        return jid, owner

    def test_voice_real_save_export_waveform_and_privacy(self):
        task=self.sample()
        project=self.member.post('/api/editor/projects',json=self.project(task),headers=H).json()
        jid,owner=self.ready_voice(project['id'])
        with patch('urllib.request.urlopen',side_effect=AssertionError('No paid calls')):
            job=self.member.get('/api/voice/jobs/'+jid).json()['job']
            self.assertEqual(job['project_id'],project['id'])
            self.assertEqual(self.admin.get('/api/voice/jobs').json()['jobs'],[])
            self.assertEqual(self.admin.get('/api/voice/jobs/'+jid+'/audio').status_code,404)
            self.assertEqual(self.member.post('/api/voice/jobs/'+jid+'/asset',json={}).status_code,403)
            asset=self.member.post('/api/voice/jobs/'+jid+'/asset',json={},headers=H)
            self.assertEqual(asset.status_code,200,asset.text)
            self.assertEqual(self.member.post('/api/voice/jobs/'+jid+'/asset',json={},headers=H).json(),asset.json())
            self.assertEqual(self.member.get('/api/assets/'+asset.json()['asset_id']).status_code,200)
            self.assertEqual(self.admin.post('/api/voice/jobs/'+jid+'/asset',json={},headers=H).status_code,404)
            wave=self.member.get('/api/editor/waveform/'+jid+'?source=voice')
            self.assertEqual(wave.status_code,200,wave.text)
            self.assertTrue(wave.json()['peaks'])
            self.assertEqual(self.admin.get('/api/editor/waveform/'+jid+'?source=voice').status_code,400)
            project['body']['audio_clips']=[dict(source='voice',voice_job_id=jid,start=0,end=.7,at=.4,volume=1,locked=True,fade_in=.05,fade_out=.05)]
            project['body']['captions']=[dict(text='配音字幕',start=.4,end=1,voice_job_id=jid)]
            saved=self.member.post('/api/editor/projects',json=project,headers=H)
            self.assertEqual(saved.status_code,200,saved.text)
            saved=saved.json()
            self.assertEqual(saved['body']['captions'][0]['voice_job_id'],jid)
            reloaded=self.member.get('/api/editor/projects').json()[0]
            self.assertEqual(reloaded['body'],saved['body'])
            response=self.member.post('/api/editor/projects/'+project['id']+'/export',json={
                'version':saved['version'],'request_key':'real-voice-export'},headers=H)
            self.assertEqual(response.status_code,200,response.text)
            eid=response.json()['id'];self.app.state.editor.tick()
            result=self.member.get('/api/editor/exports').json()[0]
            self.assertEqual(result['state'],'ready',result)
            output=self.app.state.editor.root/(eid+'.mp4')
            duration,streams=probe(output)
            self.assertAlmostEqual(duration,1.6,delta=.12)
            self.assertTrue(any(s['codec_type']=='audio' for s in streams))
            samples=array.array('h');samples.frombytes(run([shutil.which('ffmpeg'),'-v','error','-i',str(output),'-vn','-ar','8000','-ac','1','-f','s16le','pipe:1']))
            def rms(a,b):
                v=samples[int(a*8000):int(b*8000)]
                return (sum(x*x for x in v)/len(v))**.5
            self.assertLess(rms(.05,.25),50)
            self.assertGreater(rms(.55,.85),500)
            project=saved;project['body']['audio_clips'][0]['at']=1.3
            self.assertEqual(self.member.post('/api/editor/projects',json=project,headers=H).status_code,200)

    def test_worker_disabled_configuration_and_no_factory_recovery(self):
        from app import create_app
        project=self.member.post('/api/editor/projects',json={'title':'empty','body':{}},headers=H).json()
        jid,_=self.ready_voice(project['id'])
        with self.hub.db() as db:db.execute("UPDATE voice_jobs SET state='running' WHERE id=?",(jid,))
        with patch('threading.Thread.start',side_effect=AssertionError('Factory must not spawn threads')):
            create_app(self.tmp.name,self.provider,worker=False)
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT state FROM voice_jobs WHERE id=?',(jid,)).fetchone()[0],'running')
        self.hub.voice.configure('admin',enabled=False)
        with patch.object(self.hub.voice,'_run',side_effect=AssertionError('Disabled worker called upstream')):
            self.hub.voice.tick()
