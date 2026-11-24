import time
import unittest
from unittest.mock import patch
from test_kalodata_integration import Tests as Fixture, HEADERS

class AutomationTests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    def setup_video(self,views=100,age=3600):
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'automatedemo'}).json()['id']
        self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':True})
        self.app.state.apify_monitor.ingest({'id':'seed','account':aid},[{'id':'123456789','authorMeta':{'name':'automatedemo'},'createTime':time.time()-age,'text':'caption only','playCount':views,'diggCount':100}])
        return aid
    def configure(self,**changes):
        data=dict(enabled=True,recheck=False,transcribe=False,likes=None,collects=None,comments=None,confirm_automation=True);data.update(changes)
        return self.a.post('/api/intelligence/scripts/automation',headers=HEADERS,json=data)
    def test_defaults_and_thresholds(self):
        self.setup_video(700000)
        service=self.app.state.script_automation
        self.assertFalse(self.a.get('/api/intelligence/scripts/automation').json()['config']['enabled'])
        service.scan();self.assertEqual(self.a.get('/api/intelligence/scripts').json(),[])
        self.assertEqual(self.configure(confirm_automation=False,recheck=True).status_code,400)
        self.assertEqual(self.configure().status_code,200)
        service.scan(); rows=self.a.get('/api/intelligence/scripts').json()
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['transcript_original']);self.assertEqual(rows[0]['reasons'],['播放量 ≥ 70 万'])
        service.scan();self.assertEqual(len(self.a.get('/api/intelligence/scripts').json()),1)
    def test_recheck_disable_and_optout(self):
        aid=self.setup_video(100,age=3600)
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        self.assertEqual(self.configure(recheck=True).status_code,200)
        service=self.app.state.script_automation;service.scan()
        with self.hub.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM script_rechecks WHERE state='waiting'").fetchone()[0],2)
            db.execute("UPDATE script_rechecks SET due=? WHERE stage=2",(time.time()-1,))
        service.recheck_tick()
        with self.hub.db() as db:
            run=db.execute("SELECT run FROM script_rechecks WHERE stage=2").fetchone()[0]
            self.assertEqual(db.execute('SELECT state FROM apify_runs WHERE id=?',(run,)).fetchone()[0],'queued')
        self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':False})
        with patch.object(self.app.state.apify_monitor,'request') as request:
            self.app.state.apify_monitor.tick();request.assert_not_called()
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT state FROM apify_runs WHERE id=?',(run,)).fetchone()[0],'cancelled')
    def test_transcribe_mock_and_retry(self):
        self.setup_video(700000)
        with patch('script_automation.local_asr_ready',return_value=True):
            self.assertEqual(self.configure(transcribe=True).status_code,200)
            service=self.app.state.script_automation;service.scan()
            with patch('script_automation.transcribe',side_effect=ValueError('unavailable')) as transcribe:
                service.transcription_tick(); self.assertEqual(transcribe.call_count,1)
            info=self.a.get('/api/intelligence/scripts/automation').json();self.assertEqual(len(info['failures']),1)
            self.assertEqual(self.a.post('/api/intelligence/scripts/automation/retry/'+info['failures'][0]['item'],headers=HEADERS,json={}).status_code,200)
            with patch('script_automation.transcribe',return_value=('spoken text','test ASR')):service.transcription_tick()
            item=self.a.get('/api/intelligence/scripts').json()[0]
            self.assertEqual(item['transcript_original'],'spoken text');self.assertEqual(item['description'],'caption only')
            self.assertEqual(item['transcript_source'],'test ASR')
if __name__=='__main__':unittest.main()
