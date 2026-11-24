import json, shutil
from unittest.mock import patch
from test_voice_workflow import VoiceWorkflowTests
from test_hub import H
from editor import run
import fishaudio as fa

class LongSpeechTests(VoiceWorkflowTests):
    def test_long_caption_and_complete_merge(self):
        project,payload=self.prepare()
        text=('Long spoken paragraph. '*200)+'THE FINAL SENTENCE.'
        project['body']['captions']=[dict(text=text,start=0,end=1.5)]
        saved=self.member.post('/api/editor/projects',json=project,headers=H)
        self.assertEqual(saved.status_code,200,saved.text)
        project=saved.json()
        payload.update(project_version=project['version'],auto_timeline=False)
        result=self.member.post('/api/voice/jobs',json=payload,headers=H)
        self.assertEqual(result.status_code,200,result.text)
        jid=result.json()['job']['id'];voice=self.hub.voice
        sample=voice.files/'test-tone.wav'
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=0.4',str(sample)])
        received=[]
        def collect(job,key,part):
            received.append(part)
            collector=fa.StreamCollector();collector.audio=bytearray(sample.read_bytes())
            return collector
        with patch.object(voice,'_collect',side_effect=collect):
            voice._run(jid)
        self.assertEqual(''.join(received),text)
        self.assertGreater(len(received),1)
        job=self.member.get('/api/voice/jobs/'+jid).json()['job']
        self.assertEqual(job['state'],'ready')
        self.assertAlmostEqual(job['duration'],len(received)*.4,delta=.15)
