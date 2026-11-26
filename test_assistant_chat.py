from test_image_fixture import png as valid_png
import unittest
import io
import json
from unittest.mock import patch,MagicMock
from fastapi.testclient import TestClient
import test_hub as fixtures

class AssistantTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    def post(self,c,path,data):return c.post('/api/assistant'+path,json=data,headers=fixtures.H)
    def test_generated_image_private_material_and_idempotency(self):
        import base64
        from pathlib import Path
        from PIL import Image
        buf=io.BytesIO();Image.new('RGB',(16,24),'white').save(buf,format='PNG')
        encoded=base64.b64encode(buf.getvalue()).decode()
        with self.hub.db() as db:db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        tid=self.post(self.member,'/threads',{}).json()['id']
        data={'text':'画一朵花','mode':'image','size':'1K','ratio':'9:16','request_key':'image-generation-test-001','images':[{'name':'ref.png','url':'data:image/png;base64,'+encoded}]}
        calls=[]
        def fake(args,cwd):
            calls.append(args)
            if args[0]=='account':return {'accounts':[{'accountId':42,'isActive':True}]}
            if args[0]=='model':return {'schema':{'modelKey':'lib-image-2.5-f'}}
            if args[0]=='project':return {'projectMeta':{'uuid':'b'*32}}
            if args[0]=='download':(Path(args[-1])/'result.png').write_bytes(buf.getvalue())
            return {}
        with patch('libtv_gateway.cli',side_effect=fake),patch('assistant_chat.urllib.request.build_opener') as agnes:
            result=self.post(self.member,'/threads/'+tid+'/send',data)
            self.assertEqual(result.status_code,200,result.text);aid=result.json()['result_asset']
            self.assertEqual(self.post(self.member,'/threads/'+tid+'/send',data).json()['result_asset'],aid)
            self.assertEqual(sum('--run' in x for x in calls),1);agnes.assert_not_called()
            args=next(x for x in calls if '--run' in x)
            self.assertIn('model=Lib Image 2.5 Fast',args)
            self.assertIn('modeType=image2image',args)
            self.assertEqual(args[args.index('--left')+1],'参考1')
            upload=next(a for a in calls if a[0]=='upload')
            self.assertEqual(upload[:4],['upload','参考1','-p','b'*32])
            self.assertLess(calls.index(upload),calls.index(args))
            self.assertEqual(self.post(self.member,'/threads/'+tid+'/send',{**data,'ratio':'1:1'}).status_code,409)
        self.assertEqual(self.member.get('/api/assets/'+aid).status_code,200)
        self.assertEqual(self.admin.get('/api/assets/'+aid).status_code,404)
        self.assertEqual(self.member.get('/api/assistant/threads/'+tid).json()[0]['result_asset'],aid)
        self.assertIn(aid,[r['id'] for r in self.member.get('/api/workspace/materials').json()])

    def test_private_memory_threads_and_key(self):
        self.assertEqual(self.post(self.member,'/settings',{'key':'fake-secret-123'}).status_code,403)
        self.assertEqual(self.post(self.admin,'/settings',{'key':'fake-secret-123'}).status_code,200)
        self.post(self.admin,'/memory',{'content':'ADMIN_SECRET'})
        self.post(self.member,'/memory',{'content':'MEMBER_SECRET','owner':'admin'})
        self.assertEqual(self.admin.get('/api/assistant/memory').json()['content'],'ADMIN_SECRET')
        tid=self.post(self.member,'/threads',{}).json()['id']
        for suffix in ['', '/delete','/send']:
            r=self.admin.get('/api/assistant/threads/'+tid) if not suffix else self.post(self.admin,'/threads/'+tid+suffix,{'text':'x','request_key':'request-test-12345'})
            self.assertEqual(r.status_code,404,r.text)
        self.assertEqual(self.admin.get('/api/assistant/threads').json(),[])
        self.assertNotIn('fake-secret',self.admin.get('/api/assistant/status').text)
        with self.hub.db() as db:self.assertNotIn(b'fake-secret',db.execute('SELECT secret FROM ai_settings').fetchone()[0])
        anon=TestClient(self.app,base_url=fixtures.BASE)
        self.assertEqual(anon.get('/api/assistant/memory').status_code,401);anon.close()
    def test_context_persistence_and_idempotency(self):
        self.post(self.admin,'/settings',{'key':'fake-secret-123'})
        self.post(self.admin,'/memory',{'content':'ADMIN_SECRET'})
        self.post(self.member,'/memory',{'content':'MEMBER_MEMORY'})
        tid=self.post(self.member,'/threads',{}).json()['id']
        payload_response={'choices':[{'message':{'content':'answer'},'finish_reason':'stop'}]}
        opener=MagicMock();opener.open.side_effect=lambda *a,**k:io.BytesIO(json.dumps(payload_response).encode())
        with patch('assistant_chat.urllib.request.build_opener',return_value=opener):
            send=opener.open
            payload={'text':'hello','request_key':'unique-request-123'}
            self.assertEqual(self.post(self.member,'/threads/'+tid+'/send',payload).status_code,200)
            self.assertEqual(self.post(self.member,'/threads/'+tid+'/send',payload).status_code,200)
            self.assertEqual(send.call_count,1)
            self.post(self.member,'/threads/'+tid+'/send',{'text':'next','request_key':'unique-request-456'})
            messages=json.loads(send.call_args.args[0].data)['messages'];text=str(messages)
            self.assertIn('MEMBER_MEMORY',text);self.assertNotIn('ADMIN_SECRET',text);self.assertIn('hello',text);self.assertIn('answer',text)
            self.assertIn('团队共用 TikTok 写作规则',text)
            self.assertIn('stable_script_generation_contract_v1.md',text)
            self.assertIn('每段最多17秒',text)
            self.assertIn('不能声称已创建文件',text)
        self.assertEqual(len(self.member.get('/api/assistant/threads/'+tid).json()),2)
        self.post(self.member,'/memory',{'content':''})
        self.assertEqual(self.member.get('/api/assistant/memory').json()['content'],'')
    def test_product_guide_is_first_for_overview_and_specific_questions(self):
        self.post(self.admin,'/a6-settings',{'key':'fake-secret-123'})
        tid=self.post(self.member,'/threads',{}).json()['id']
        response={'choices':[{'message':{'content':'answer'},'finish_reason':'stop'}]}
        opener=MagicMock()
        opener.open.side_effect=lambda *args,**kwargs:io.BytesIO(json.dumps(response).encode())
        with patch('assistant_chat.urllib.request.build_opener',return_value=opener):
            for index, query in enumerate(('你现在了解中台的所有功能么','制作台的 MAGI-2 在哪里选择')):
                result=self.post(self.member,'/threads/'+tid+'/send',{'text':query,'request_key':f'product-guide-test-{index}'})
                self.assertEqual(result.status_code,200,result.text)
                messages=json.loads(opener.open.call_args.args[0].data)['messages']
                system=[m['content'] for m in messages if m['role']=='system']
                self.assertEqual(len(system),1)
                self.assertIn('素材管理',system[0][:1800])
                self.assertIn('竞对与脚本',system[0][:1800])
                self.assertLess(system[0].index('《中台功能指南》'),system[0].index('团队共用 TikTok 写作规则'))
                self.assertNotIn('自动提取的代码接口索引',system[0])
                if index:
                    self.assertIn('1080p',system[0].split('团队共用 TikTok 写作规则',1)[0])

    def test_classification_pending_and_manual(self):
        r=self.member.post('/api/assets',content=valid_png(),headers={**fixtures.H,'Content-Type':'image/png','X-File-Name':'test.png'})
        self.assertEqual(r.status_code,200,r.text);aid=r.json()['id']
        self.assertEqual(r.json()['classification_status'],'waiting_model')
        r=self.member.post('/api/workspace/materials/'+aid,json={'name':'test','category':'product'},headers=fixtures.H)
        self.assertEqual(r.status_code,200,r.text)
        from asset_classification import classify_image
        self.assertEqual(classify_image(self.hub,aid,self.member.get('/api/me').json()['id'],lambda p:'person')['source'],'manual')
        row=self.member.get('/api/workspace/materials').json()[0]
        self.assertEqual(row['category'],'product');self.assertEqual(row['classification_status'],'manual')
        self.assertEqual(self.admin.get('/api/workspace/materials').json(),[])

    def test_auto_classify_queue_ownership_and_manual_race(self):
        from asset_classification import tick,enqueue
        self.post(self.admin,'/settings',{'key':'fake-secret-123'})
        r=self.member.post('/api/assets',content=valid_png(),headers={**fixtures.H,'Content-Type':'image/png','X-File-Name':'test.png'})
        aid=r.json()['id'];uid=self.member.get('/api/me').json()['id']
        self.assertEqual(r.json()['classification_status'],'queued')
        self.assertEqual(self.admin.post('/api/workspace/materials/'+aid+'/classify',json={},headers=fixtures.H).status_code,404)
        self.assertTrue(tick(self.hub,lambda p:'product'))
        row=self.member.get('/api/workspace/materials').json()[0]
        self.assertEqual(row['category'],'product');self.assertEqual(row['classification_status'],'classified')
        enqueue(self.hub,aid,uid)
        def racing(path):
            self.member.post('/api/workspace/materials/'+aid,json={'name':'test','category':'scene'},headers=fixtures.H)
            return 'person'
        tick(self.hub,racing)
        row=self.member.get('/api/workspace/materials').json()[0]
        self.assertEqual(row['category'],'scene');self.assertEqual(row['classification_status'],'manual')

    def test_invalid_result_fails_without_retry(self):
        from asset_classification import tick
        self.post(self.admin,'/settings',{'key':'fake-secret-123'})
        self.member.post('/api/assets',content=valid_png(),headers={**fixtures.H,'Content-Type':'image/png','X-File-Name':'test.png'})
        tick(self.hub,lambda p:'bad-category')
        self.assertFalse(tick(self.hub,lambda p:'product'))
        row=self.member.get('/api/workspace/materials').json()[0]
        self.assertEqual(row['classification_status'],'failed');self.assertEqual(row['category'],'other')

    def test_image_send_history_and_isolation(self):
        import base64
        from PIL import Image
        buf=io.BytesIO();Image.new('RGB',(8,8),'red').save(buf,format='PNG')
        image={'name':'test.png','url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()}
        self.post(self.admin,'/settings',{'key':'fake-secret-123'})
        tid=self.post(self.member,'/threads',{}).json()['id']
        opener=MagicMock();opener.open.side_effect=lambda *a,**k:io.BytesIO(json.dumps({'choices':[{'message':{'content':'image answer'}}]}).encode())
        with patch('assistant_chat.urllib.request.build_opener',return_value=opener):
            data={'text':'describe','images':[image],'request_key':'image-request-12345'}
            r=self.post(self.member,'/threads/'+tid+'/send',data)
            self.assertEqual(r.status_code,200,r.text)
            payload=json.loads(opener.open.call_args.args[0].data)
            self.assertEqual(payload['messages'][-1]['content'][1]['type'],'image_url')
            self.assertTrue(payload['messages'][-1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            self.post(self.member,'/threads/'+tid+'/send',data)
            self.assertEqual(opener.open.call_count,1)
            self.post(self.member,'/threads/'+tid+'/send',{'text':'continue','request_key':'image-followup-12345'})
            self.assertIsInstance(json.loads(opener.open.call_args.args[0].data)['messages'][-3]['content'],list)
        rows=self.member.get('/api/assistant/threads/'+tid).json()
        self.assertEqual(json.loads(rows[0]['images'])[0]['name'],'test.png')
        self.assertEqual(self.admin.get('/api/assistant/threads/'+tid).status_code,404)
        invalid=self.post(self.member,'/threads/'+tid+'/send',{'text':'bad','images':[{'url':'https://example.com/private'}],'request_key':'invalid-image-12345'})
        self.assertEqual(invalid.status_code,400)
