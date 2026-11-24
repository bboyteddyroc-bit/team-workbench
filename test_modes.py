import json
import unittest
import zlib
from provider import reference_payload, TikTok, ProviderError
import test_hub as fixtures

IMAGE={'id':'image-id','name':'test.png','fileType':'image','previewUrl':'https://p19-creative-tool-sg.ibyteimg.com/tos-alisg-i-n2703mo9gi-sg/test.image'}


class PayloadTests(unittest.TestCase):
    def test_mixed_references_and_model_ids(self):
        assets=[IMAGE,dict(id='v',fileType='video',vid='v123',duration=5),dict(id='a',fileType='audio',vid='a123',duration=4)]
        for model in ('2000004','2000009','2000012'):
            payload=reference_payload('<|media:0|> moves',assets,8,model)
            self.assertEqual(payload['mentions'],[{'type':1,'id':IMAGE['previewUrl']},{'type':2,'id':'v123'},{'type':101,'id':'a123'}])
            self.assertEqual(json.loads(payload['settings'])['aiModel'],model)
        with self.assertRaises(ValueError):reference_payload('test',assets[2:])
        with self.assertRaises(ValueError):reference_payload('test',[IMAGE]*10)
        with self.assertRaises(ValueError):reference_payload('test',[IMAGE,dict(assets[1],duration=16)])

    def test_account_cookie_isolation(self):
        p=TikTok(None);original={'cookie':'session=private; s_aio_client_id=111; other=value'}
        changed=p.scoped_account(original,'222')
        self.assertIn('s_aio_client_id=111',original['cookie'])
        self.assertEqual(changed['cookie'],'session=private; other=value; s_aio_client_id=222')
        with self.assertRaises(ValueError):p.scoped_account(original,'222; injected=1')

    def test_frames_order(self):
        p=TikTok(None);calls=[]
        p.post=lambda h,o,b:calls.append((o,b)) or {'task_id':'test'}
        p.create_frames({},'movement',[IMAGE,dict(IMAGE,id='last',previewUrl=IMAGE['previewUrl']+'last')],6)
        operation,payload=calls[0]
        self.assertEqual(operation,'i2v/create_generate_task')
        self.assertEqual(payload['model'],'4000005')
        self.assertEqual(payload['image'],payload['images'][0])
        self.assertEqual(len(payload['images']),2)

    def test_media_upload_transport_and_duration_guard(self):
        from media_upload import upload_media
        class Response:
            def __init__(self,data):self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps(self.data).encode()
        class Provider:
            def __init__(self):self.opener=self;self.requests=[];self.duration=4
            def post(self,h,op,payload):
                if op=='upload/token':return dict(AccessKeyId='test',SecretAccessKey='temporary',SessionToken='temporary-token')
                return {'v123':{'status_code':0}}
            def get_cue(self,*args):return {'v123':{'VideoInfos':[{'MainUrl':'https://video.tiktokcdn.com/test'}]}}
            def open(self,request,timeout):
                self.requests.append(request)
                if 'ApplyUploadInner' in request.full_url:
                    return Response({'Result':{'InnerUploadAddress':{'UploadNodes':[{'UploadHost':'upload.tiktokcdn.com','StoreInfos':[{'StoreUri':'tos-alisg-v-0051c001-sg/test','Auth':'object-auth'}],'SessionKey':'session'}]}}})
                return Response({'code':2000,'data':{'file_info':{'crc32':format(zlib.crc32(b'media')&0xffffffff,'08x')},'post_upload_resp':{'results':[{'vid':'v123','video_meta':{'FileType':'audio','Duration':self.duration}}]}}})
        provider=Provider()
        result=upload_media(provider,{'cookie':'private-login','x-csrftoken':'private-csrf'},b'media','test.mp3','audio')
        self.assertEqual(result['vid'],'v123')
        request=provider.requests[1]
        self.assertNotIn(b'private-login',request.data)
        self.assertNotIn('cookie',{k.lower() for k,v in request.header_items()})
        self.assertIn(b'post_upload_req',request.data)
        provider.duration=30
        with self.assertRaises(ProviderError):upload_media(provider,{},b'media','test.mp3','audio')


class RoutingTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    account=fixtures.HubTests.account
    batch=fixtures.HubTests.batch

    def test_routing_ignores_unknown_but_counts_known_attention(self):
        account_id=self.account(self.admin)
        self.provider.quotas=lambda h:{'5000005':{'matched':True,'allowed':True,'remaining':20}}
        self.batch([{'prompt':'old'}],key='old-request-000001')
        self.batch([{'prompt':'new'}],key='new-request-000002')
        with self.hub.db() as db:
            account=db.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
            old=db.execute("SELECT * FROM tasks WHERE prompt='old'").fetchone()
            new=db.execute("SELECT * FROM tasks WHERE prompt='new'").fetchone()
            db.execute("UPDATE tasks SET state='unknown' WHERE id=?",(old['id'],))
        chosen,_=self.hub.route_task(account,new,{'model':'5000005','account_choice':account_id})
        self.assertEqual(chosen['id'],account_id)
        with self.hub.db() as db:
            db.execute("UPDATE tasks SET state='attention',remote_id='123' WHERE id=?",(old['id'],))
        self.provider.quotas=lambda h:{'5000005':{'matched':True,'allowed':True,'remaining':1}}
        with self.assertRaises(ProviderError):self.hub.route_task(account,new,{'model':'5000005','account_choice':account_id})

    def test_quota_fallback_before_creation(self):
        self.account(self.admin)
        with self.hub.db() as db:account=db.execute('SELECT * FROM accounts').fetchone()
        self.provider.quotas=lambda h:{'5000005':{'matched':True,'allowed':False,'remaining':0},'2000009':{'matched':True,'allowed':True,'remaining':4}}
        self.batch([{'prompt':'test'}])
        with self.hub.db() as db:task=db.execute('SELECT * FROM tasks').fetchone()
        chosen,config=self.hub.route_task(account,task,{'model':'auto','assets':[{'id':'placeholder'}]})
        self.assertEqual(config['model'],'mini')
        self.assertEqual(self.provider.created,[])
        with self.assertRaises(ProviderError):self.hub.route_task(account,task,{'model':'5000005'})
        self.provider.quotas=lambda h:{}
        with self.assertRaises(ProviderError):self.hub.route_task(account,task,{'model':'auto','assets':[{}]})
