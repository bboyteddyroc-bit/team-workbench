import json, tempfile, unittest
from fastapi.testclient import TestClient
from app import create_app
from provider import ProviderError

BASE='http://127.0.0.1:8765'
H={'X-Hub-Request':'1','Origin':BASE}
PW='Example-test-password-123'
def curl(identity='company'):
    body=json.dumps(dict(model='5000005',gokuModel='5000005',duration=5,prompt='test',settings='{}'))
    return "curl 'https://ads.tiktok.com/creative_bff_i18n/api/cue/t2v/create_generate_task' -H 'content-type: application/json' -H 'x-csrftoken: fake-csrf' -H 'x-fp-id: fake-fp' -b 'identity=\""+identity+"\"' --data-raw '"+body+"'"

class FakeProvider:
    def __init__(self): self.created=[]; self.uploads=[]
    def history(self,headers): return {'draft_infos':[]}
    def create(self,headers,prompt,duration=5):
        self.created.append((prompt,duration)); return {'task_id':'1','draft_infos':[{'id':'d'}]}
    def upload_media(self,headers,path,kind='image'):
        self.uploads.append((kind,str(path))); return {'id':'up-'+kind,'previewUrl':'https://p19-creative-tool-sg.ibyteimg.com/x.jpg'}

class MentionTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.provider=FakeProvider()
        self.app=create_app(self.tmp.name,self.provider,worker=False); self.hub=self.app.state.hub
        self.hub.reference_enabled=True
        self.client=TestClient(self.app,base_url=BASE)
        self.assertEqual(self.client.post('/api/setup',json={'username':'admin','password':PW},headers=H).status_code,200)
        self.assertEqual(self.client.post('/api/login',json={'username':'admin','password':PW},headers=H).status_code,200)
        r=self.client.post('/api/accounts',json={'name':'账号','scope':'shared','curl':curl(),'daily_limit':20},headers=H)
        self.assertEqual(r.status_code,200,r.text); self.account=r.json()['id']
        with self.hub.db() as db:
            owner=db.execute('SELECT id FROM users LIMIT 1').fetchone()['id']
            for aid,mime in (('a-img','image/png'),('a-vid','video/mp4'),('a-aud','audio/mpeg')):
                db.execute('INSERT OR REPLACE INTO assets(id,owner,name,mime,size,created) VALUES(?,?,?,?,?,0)',(aid,owner,aid+'.dat',mime,10))

    def tearDown(self):
        self.client.close(); self.tmp.cleanup()

    def post(self,items,key='mention-request-000001'):
        return self.client.post('/api/tasks',json={'account_id':self.account,'items':items,'request_key':key},headers=H)

    def item(self,prompt,assets):
        return {'prompt':prompt,'mode':'omni','model':'auto','duration':5,'count':1,'assets':assets,'request_key':'mention-request-000001'}

    def test_video_and_audio_tokens_reach_provider_prompt(self):
        assets=[{'id':'a-img','role':'reference','token':'图片1'},{'id':'a-vid','role':'reference','token':'视频1'},{'id':'a-aud','role':'reference','token':'音频1'}]
        r=self.post([self.item('开头 @图片1 ，风格参考 @视频1 ，声音像 @音频1',assets)])
        self.assertEqual(r.status_code,200,r.text)
        with self.hub.db() as db:
            row=db.execute('SELECT * FROM tasks').fetchone()
        payload=json.loads(row['metadata']) if row['metadata'] else {}
        stored=json.loads(row['config'] or '{}')
        joined=json.dumps(payload,ensure_ascii=False)+json.dumps(stored,ensure_ascii=False)
        self.assertIn('<|media:0|>',joined)
        self.assertIn('<|media:1|>',joined)
        self.assertIn('<|media:2|>',joined)

    def test_token_label_must_match_media_kind(self):
        assets=[{'id':'a-img','role':'reference','token':'图片1'},{'id':'a-vid','role':'reference','token':'图片2'}]
        r=self.post([self.item('@图片1 @图片2 混合',assets)])
        self.assertEqual(r.status_code,400,r.text)
        self.assertIn('视频引用编号有误',r.text)

    def test_audio_only_reference_rejected(self):
        assets=[{'id':'a-aud','role':'reference','token':'音频1'}]
        r=self.post([self.item('只有声音 @音频1',assets)])
        self.assertEqual(r.status_code,400,r.text)
        self.assertIn('声音需要配合图片或视频',r.text)

    def test_unknown_token_message(self):
        assets=[{'id':'a-img','role':'reference','token':'图片1'}]
        r=self.post([self.item('引用 @图片2 不存在',assets)])
        self.assertEqual(r.status_code,400,r.text)
        self.assertIn('提示词引用了已移除的素材',r.text)

if __name__=='__main__':unittest.main()

