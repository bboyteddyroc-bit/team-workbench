from test_image_fixture import png as valid_png
import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app import create_app, password_hash
from provider import ProviderError, parse_curl

BASE='http://127.0.0.1:8765'
H={'X-Hub-Request':'1','Origin':BASE}
PW='Example-test-password-123'


def curl(identity='company'):
    body=json.dumps(dict(model='5000005',gokuModel='5000005',duration=5,prompt='test',settings='{}'))
    return "curl 'https://ads.tiktok.com/creative_bff_i18n/api/cue/t2v/create_generate_task' -H 'content-type: application/json' -H 'x-csrftoken: fake-csrf' -H 'x-fp-id: fake-fp' -b 'identity="+identity+"' --data-raw '"+body+"'"


class FakeProvider:
    def __init__(self): self.created=[]; self.results={}; self.fail=False
    def history(self,headers): return {'draft_infos':[]}
    def create(self,headers,prompt,duration=5):
        self.created.append((headers['cookie'],prompt))
        if self.fail: raise ProviderError('模拟提交超时')
        task_id=str(100000+len(self.created));return {'task_id':task_id,'draft_infos':[{'id':'draft'+task_id}]}
    def find(self,headers,task_id): return self.results.get(task_id)
    def download(self,url,path,user_agent='Mozilla/5.0'): path.write_bytes(b'fake-test-video')


class HubTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.provider=FakeProvider()
        self.app=create_app(self.tmp.name,self.provider,worker=False);self.hub=self.app.state.hub
        self.admin=TestClient(self.app,base_url=BASE)
        self.assertEqual(self.admin.post('/api/setup',json={'username':'admin','password':PW},headers=H).status_code,200)
        self.login(self.admin,'admin')
        self.admin.post('/api/users',json={'username':'member','password':PW,'daily_limit':10},headers=H)
        self.member=TestClient(self.app,base_url=BASE);self.login(self.member,'member')
        self.assertEqual(self.member.post('/api/password',json={'old':PW,'new':PW+'new'},headers=H).status_code,200)

    def tearDown(self):
        self.admin.close();self.member.close();self.tmp.cleanup()

    def login(self,client,name):
        self.assertEqual(client.post('/api/login',json={'username':name,'password':PW},headers=H).status_code,200)

    def account(self,client,scope='shared',identity='company',limit=20):
        r=client.post('/api/accounts',json={'name':'账号','scope':scope,'curl':curl(identity),'daily_limit':limit},headers=H)
        self.assertEqual(r.status_code,200,r.text);return r.json()['id']

    def enqueue(self,client,account,key='test-request-000001'):
        return client.post('/api/tasks',json={'account_id':account,'prompt':'测试视频','request_key':key},headers=H)

    def due(self):
        with self.hub.db() as db: db.execute('UPDATE tasks SET poll_at=0')

    def test_auth_csrf_and_setup_lock(self):
        anon=TestClient(self.app,base_url=BASE)
        self.assertEqual(anon.get('/api/tasks').status_code,401)
        self.assertEqual(self.admin.post('/api/logout',json={}).status_code,403)
        self.assertEqual(self.admin.post('/api/logout',json={},headers={**H,'Origin':'https://evil.invalid'}).status_code,403)
        self.assertEqual(self.admin.post('/api/setup',json={'username':'another','password':PW},headers=H).status_code,409)
        self.assertEqual(self.admin.get('/api/tasks',headers={'Host':'evil.invalid'}).status_code,400)
        anon.close()

    def test_company_only_and_encryption(self):
        public=self.account(self.admin,'shared','shared')
        self.assertEqual(self.admin.post('/api/accounts',json={'name':'private','scope':'personal','curl':curl()},headers=H).status_code,400)
        self.assertEqual(self.member.post('/api/accounts',json={'name':'bad','scope':'shared','curl':curl()},headers=H).status_code,403)
        self.assertIn(public,[a['id'] for a in self.member.get('/api/accounts').json()])
        with self.hub.db() as db: data=db.execute('SELECT secret FROM accounts WHERE id=?',(public,)).fetchone()[0]
        self.assertNotIn(b'identity=shared',data)
        self.assertNotIn('cookie',self.admin.get('/api/accounts').text)

    def test_idempotency_without_daily_limits(self):
        a=self.account(self.admin,limit=1)
        r=self.enqueue(self.member,a);self.assertEqual(r.status_code,200)
        self.assertEqual(self.enqueue(self.member,a).json(),r.json())
        self.assertEqual(self.enqueue(self.member,a,'another-key-000002').status_code,200)
        self.hub.tick();self.hub.tick();self.assertEqual(len(self.provider.created),2)

    def test_concurrent_queue_and_ready_download(self):
        a=self.account(self.admin)
        first=self.enqueue(self.member,a).json()['id']
        self.enqueue(self.member,a,'another-key-000002')
        self.hub.tick();self.hub.tick();self.assertEqual(len(self.provider.created),2)
        with self.hub.db() as db: remote=db.execute('SELECT remote_id FROM tasks WHERE id=?',(first,)).fetchone()[0]
        self.provider.results[remote]={'hasContent':True,'draftTaskStatus':0,'renderTaskStatus':0,'videoInfo':{'OriginalVideoInfo':{'MainUrl':'https://fake.tiktokcdn.com/video','VideoMeta':{'Width':'720'}}}}
        self.due();self.hub.tick()
        self.assertEqual(self.member.get('/api/tasks/'+first+'/video').content,b'fake-test-video')
        self.hub.tick();self.assertEqual(len(self.provider.created),2)

    def test_ambiguous_submission_does_not_block_following_tasks(self):
        a=self.account(self.admin);first=self.enqueue(self.member,a).json()['id']
        self.provider.fail=True;self.hub.tick();self.provider.fail=False
        second=self.enqueue(self.member,a,'another-key-000002').json()['id'];self.hub.tick()
        rows={t['id']:t for t in self.member.get('/api/tasks').json()}
        self.assertEqual(len(self.provider.created),2)
        self.assertEqual(rows[first]['state'],'unknown')
        self.assertEqual(rows[second]['state'],'running')

    def test_failure_is_terminal_and_not_resubmitted(self):
        a=self.account(self.admin);self.enqueue(self.member,a);self.hub.tick()
        self.provider.results['100001']={'draftTaskStatus':3,'renderTaskStatus':3,'generateErrorCode':'10043301','generateErrorMessage':'output audio filtered'}
        self.due();self.hub.tick();self.hub.tick()
        task=self.member.get('/api/tasks').json()[0]
        self.assertEqual(task['state'],'failed');self.assertIn('audio',task['error']);self.assertEqual(len(self.provider.created),1)

    def test_task_privacy_and_disabled_user(self):
        a=self.account(self.admin);tid=self.enqueue(self.admin,a).json()['id']
        self.assertEqual(self.member.get('/api/tasks').json(),[])
        self.assertEqual(self.member.get('/api/tasks/'+tid+'/video').status_code,404)
        self.assertEqual(self.member.post('/api/tasks/'+tid+'/action',json={'action':'cancel'},headers=H).status_code,404)
        self.assertEqual(self.member.get('/api/users').status_code,403)
        uid=self.member.get('/api/me').json()['id']
        self.admin.post('/api/users/'+uid,json={'enabled':False,'daily_limit':10},headers=H)
        self.assertEqual(self.member.get('/api/me').status_code,401)

    def test_cancel_does_not_submit(self):
        a=self.account(self.admin);tid=self.enqueue(self.member,a).json()['id']
        self.member.post('/api/tasks/'+tid+'/action',json={'action':'cancel'},headers=H)
        self.hub.tick();self.assertEqual(self.provider.created,[])

    def test_account_pause_holds_queue(self):
        a=self.account(self.admin);self.enqueue(self.member,a)
        self.admin.post('/api/accounts/'+a+'/toggle',json={},headers=H)
        self.hub.tick();self.assertEqual(self.provider.created,[])

    def test_curl_injection_and_wrong_endpoint(self):
        with self.assertRaises(ValueError):parse_curl(curl()+' --output secrets.txt')
        with self.assertRaises(ValueError):parse_curl(curl().replace('ads.tiktok.com','evil.invalid'))
        with self.assertRaises(ValueError):parse_curl(curl().replace('create_generate_task','other'))

    def test_count_request_connect_and_validation(self):
        count="curl --url 'https://ads.tiktok.com/creative_bff_i18n/api/cue/generating-task-count?aid=123' -X POST -H 'x-csrftoken: fake-csrf' -H 'x-fp-id: fake-fp' -H 'content-length: 0' -b 'identity=fixture'"
        headers=parse_curl(count)
        self.assertNotIn('content-length',headers)
        self.assertEqual(headers['cookie'],'identity=fixture')
        with self.assertRaises(ValueError):parse_curl(count.replace('ads.tiktok.com','evil.invalid'))
        with self.assertRaises(ValueError):parse_curl(count.replace('generating-task-count','other'))
        with self.assertRaises(ValueError):parse_curl(count.replace(" -H 'x-fp-id: fake-fp'",''))
        r=self.admin.post('/api/accounts',json={'name':'count fixture','scope':'shared','curl':count},headers=H)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.provider.created,[])
        self.assertEqual(self.admin.get('/api/accounts').json()[0]['status'],'connected')
        before=len(self.admin.get('/api/accounts').json())
        def reject(_):raise ProviderError('验证失败',auth=True)
        self.provider.history=reject
        r=self.admin.post('/api/accounts',json={'name':'bad','scope':'shared','curl':count},headers=H)
        self.assertEqual(r.status_code,400)
        self.assertEqual(len(self.admin.get('/api/accounts').json()),before)
        self.assertEqual(self.provider.created,[])

    def test_long_queue_counts_timeout_from_submission(self):
        a=self.account(self.admin);tid=self.enqueue(self.member,a).json()['id']
        with self.hub.db() as db: db.execute('UPDATE tasks SET created=created-10000 WHERE id=?',(tid,))
        self.hub.tick();self.due();self.hub.tick()
        self.assertEqual(self.member.get('/api/tasks').json()[0]['state'],'running')

    def test_duplicate_account_rejected(self):
        self.account(self.admin,'shared','same')
        r=self.admin.post('/api/accounts',json={'name':'duplicate','scope':'shared','curl':curl('same')},headers=H)
        self.assertEqual(r.status_code,409)
        self.assertIn('账号',r.json()['detail'])
        self.assertIn('更新连接',r.json()['detail'])

    def test_pagination(self):
        a=self.account(self.admin)
        uid=self.member.get('/api/me').json()['id']
        with self.hub.db() as db:
            for i in range(105):
                db.execute('INSERT INTO tasks(id,owner,account_id,prompt,state,created,updated,request_key) VALUES(?,?,?,?,?,?,?,?)',(str(i),uid,a,'test','cancelled',i,i,str(i)))
        self.assertEqual(len(self.member.get('/api/tasks').json()),100)
        self.assertEqual(len(self.member.get('/api/tasks?offset=100').json()),5)


    def batch(self,items,key='batch-request-000001'):
        return self.member.post('/api/tasks',json={'request_key':key,'account_id':'pool','items':items},headers=H)

    def test_batch_atomic_validation_duration_and_repeat(self):
        self.account(self.admin)
        self.assertEqual(self.batch([{'prompt':'first','count':10},{'prompt':'bad','count':11}]).status_code,400)
        self.assertEqual(self.member.get('/api/tasks').json(),[])
        items=[{'prompt':'first','count':10,'duration':15},{'prompt':'second','count':2,'duration':4}]
        r=self.batch(items);self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(r.json()['ids']),12)
        self.assertEqual(self.batch(items).json(),r.json())
        self.assertEqual(sorted(t['duration'] for t in self.member.get('/api/tasks').json()),[4,4]+[15]*10)
        self.hub.tick();self.assertEqual(len(self.provider.created),10)
        self.hub.tick();self.assertEqual(len(self.provider.created),10)

    def test_missing_required_assets_never_submit(self):
        self.account(self.admin)
        for settings in [{'mode':'frames'},{'model':'mini'},{'model':'fast'}]:
            self.assertEqual(self.batch([{'prompt':'test',**settings}]).status_code,400 if settings.get('mode')=='frames' else 409)
        self.hub.tick();self.assertEqual(self.provider.created,[])

    def test_assets_private_and_drafts_persist(self):
        self.account(self.admin)
        r=self.member.post('/api/assets',content=valid_png(),headers={**H,'Content-Type':'image/png','X-File-Name':'reference.png'})
        self.assertEqual(r.status_code,200,r.text);asset=r.json()
        self.assertEqual(self.admin.get('/api/assets/'+asset['id']).status_code,404)
        self.assertEqual(self.member.get('/api/assets/'+asset['id']).status_code,200)
        items=[{'prompt':'@图片1','assets':[asset],'mode':'omni'}]
        self.assertEqual(self.member.post('/api/compositions',json={'items':items},headers=H).status_code,200)
        self.assertEqual(self.member.get('/api/compositions').json()['items'],items)
        self.assertEqual(self.admin.get('/api/compositions').json()['items'],[])
        self.assertEqual(self.admin.post('/api/compositions',json={'items':items},headers=H).status_code,400)
        self.assertEqual(self.batch(items).status_code,409)
        self.assertEqual(self.member.post('/api/assets',content=b'<script>bad</script>',headers={**H,'Content-Type':'image/png'}).status_code,400)

    def test_pool_distribution(self):
        self.account(self.admin,identity='a');self.account(self.admin,identity='b')
        self.assertEqual(self.batch([{'prompt':'test','count':10}]).status_code,200)
        with self.hub.db() as db: counts=[r[0] for r in db.execute('SELECT COUNT(*) FROM tasks GROUP BY account_id')]
        self.assertEqual(sorted(counts),[5,5])
        self.hub.tick();self.assertEqual(len(self.provider.created),10)

if __name__=='__main__': unittest.main(verbosity=2)
