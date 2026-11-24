from test_image_fixture import png as valid_png
import json
import unittest
import urllib.parse
import zlib
import test_hub as fixtures
from image_upload import upload_image
from provider import ProviderError


class ImageFlowTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    account=fixtures.HubTests.account
    batch=fixtures.HubTests.batch

    def image(self):
        response=self.member.post('/api/assets',content=valid_png(),headers={**fixtures.H,'Content-Type':'image/png','X-File-Name':'test.png'})
        self.assertEqual(response.status_code,200)
        return {**response.json(),'token':'图片10'}

    def test_reference_cache_and_prompt_mapping(self):
        self.account(self.admin);self.hub.reference_enabled=True;calls=[];sent=[]
        def upload(headers,content,name):
            calls.append(name)
            return {'id':'verified-id','name':name,'previewUrl':'https://p19-creative-tool-sg.ibyteimg.com/tos-alisg-i-n2703mo9gi-sg/test.image'}
        def create(headers,prompt,images,duration):
            sent.append((prompt,images,duration))
            return {'task_id':str(len(sent))}
        self.provider.upload_image=upload;self.provider.create_mini_reference=create
        result=self.batch([{'prompt':'@图片10 放在桌上','model':'mini','assets':[self.image()],'duration':8,'count':3}])
        self.assertEqual(result.status_code,200,result.text)
        self.hub.tick()
        self.assertEqual(calls,['test.png']);self.assertEqual(len(sent),3)
        self.assertTrue(all(t[0]=='<|media:0|> 放在桌上' and t[2]==8 for t in sent))
        self.assertTrue(all(t['state']=='running' for t in self.member.get('/api/tasks').json()))

    def test_upload_failure_does_not_submit_or_block_account_as_unknown(self):
        self.account(self.admin);self.hub.reference_enabled=True
        def fail(*args):raise ProviderError('图片上传失败')
        self.provider.upload_image=fail
        self.assertEqual(self.batch([{'prompt':'test','model':'mini','assets':[self.image()]}]).status_code,200)
        self.hub.tick()
        self.assertEqual(self.provider.created,[])
        self.assertEqual(self.member.get('/api/tasks').json()[0]['state'],'failed')

    def test_forged_asset_type_and_dangling_mentions(self):
        self.account(self.admin);self.hub.reference_enabled=True;asset=self.image()
        result=self.batch([{'prompt':'@图片1','model':'mini','assets':[asset]}])
        self.assertEqual(result.status_code,400)
        result=self.batch([{'prompt':'test','model':'auto','assets':[asset]}])
        self.assertEqual(result.status_code,200)


class UploadTransportTests(unittest.TestCase):
    def provider(self,host='tos-test-up.tiktokcdn.com'):
        class Response:
            def __init__(self,data):self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps(self.data).encode()
        class Provider:
            def __init__(self):self.opener=self;self.requests=[]
            def post(self,headers,operation,payload):
                if operation=='upload/token':return {'AccessKeyId':'fake-key','SecretAccessKey':'fake-secret','SessionToken':'fake-token'}
                return {'assets':payload['assets']}
            def open(self,request,timeout):
                self.requests.append(request)
                if 'ApplyImageUpload' in request.full_url:
                    return Response({'Result':{'UploadAddress':{'StoreInfos':[{'StoreUri':'tos-alisg-i-n2703mo9gi-sg/test','Auth':'object-only'}],'UploadHosts':[host],'SessionKey':'fake-session'}}})
                if '/upload/v1/' in request.full_url:return Response({'code':2000,'data':{'crc32':format(zlib.crc32(request.data)&0xffffffff,'08x')}})
                return Response({'Result':{'Results':[{'Uri':'tos-alisg-i-n2703mo9gi-sg/test','UriStatus':2000}]}})
        return Provider()

    def test_credentials_not_sent_to_storage_host(self):
        p=self.provider();result=upload_image(p,{'cookie':'sensitive','x-csrftoken':'sensitive'},b'image','test.png')
        self.assertEqual(result['name'],'test.png')
        storage=p.requests[1];headers={k.lower():v for k,v in storage.header_items()}
        self.assertNotIn('cookie',headers);self.assertNotIn('x-csrftoken',headers);self.assertNotIn('x-amz-security-token',headers)
        self.assertEqual(headers['authorization'],'object-only')
        self.assertIn('x-amz-content-sha256',dict((k.lower(),v) for k,v in p.requests[2].header_items()))

    def test_untrusted_upload_host_rejected(self):
        p=self.provider('evil.invalid')
        with self.assertRaises(ProviderError):upload_image(p,{},b'image','test.png')
        self.assertEqual(len(p.requests),1)


if __name__=='__main__':unittest.main()
