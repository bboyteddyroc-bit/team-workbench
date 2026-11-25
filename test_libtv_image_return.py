"""Regression: text-only CLI download success must publish pixels exactly once."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from libtv_gateway import cli
from test_assistant_chat import AssistantTests


class CliOutputTests(unittest.TestCase):
    def setUp(self):
        self.directory=self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch('libtv_gateway.shutil.which',return_value='libtv.exe'))
        self.enterContext(patch('libtv_gateway.profile_environment',return_value={}))

    def test_download_accepts_human_output(self):
        result=subprocess.CompletedProcess([],0,'已下载：图片.png\n','')
        with patch('libtv_gateway.run_bounded',return_value=result) as run:
            self.assertTrue(cli(['download','-p','a'*32],self.directory)['download_completed'])
            self.assertEqual(run.call_count,1)

    def test_non_download_still_requires_json(self):
        result=subprocess.CompletedProcess([],0,'unknown response','')
        with patch('libtv_gateway.run_bounded',return_value=result):
            with self.assertRaisesRegex(RuntimeError,'返回格式无法识别'):cli(['node','create'],self.directory)

    def test_download_nonzero_is_not_success(self):
        result=subprocess.CompletedProcess([],1,'已下载','unauthorized')
        with patch('libtv_gateway.run_bounded',return_value=result):
            with self.assertRaises(RuntimeError):cli(['download'],self.directory)


class ImageReturnTests(unittest.TestCase):
    setUp=AssistantTests.setUp
    tearDown=AssistantTests.tearDown
    login=AssistantTests.login
    post=AssistantTests.post

    def make_failed(self):
        tid=self.post(self.member,'/threads',{}).json()['id']
        uid=self.member.get('/api/me').json()['id'];turn='e'*32
        generation=json.dumps({'provider':'libtv','project':'b'*32,'size':'1K','ratio':'9:16'})
        with self.hub.db() as db:
            db.execute("INSERT INTO ai_turns(id,owner,thread,request_key,prompt,status,created,generation) VALUES(?,?,?,?,?,'failed',1,?)",(turn,uid,tid,'recovery-request-001','flower',generation))
        directory=self.hub.directory/'libtv'/('image-'+turn)/'download';directory.mkdir(parents=True)
        return tid,turn,directory

    def test_cached_image_recovered_without_any_cli_or_regeneration(self):
        tid,turn,directory=self.make_failed();Image.new('RGB',(16,24),'white').save(directory/'图片.png')
        endpoint='/threads/'+tid+'/turns/'+turn+'/recover'
        with patch('libtv_gateway.cli') as mock:
            self.assertEqual(self.post(self.admin,endpoint,{}).status_code,404)
            result=self.post(self.member,endpoint,{})
            self.assertEqual(result.status_code,200,result.text);asset=result.json()['result_asset']
            self.assertEqual(self.post(self.member,endpoint,{}).json()['result_asset'],asset)
            mock.assert_not_called()
        self.assertEqual(self.member.get('/api/assets/'+asset).status_code,200)
        self.assertEqual(self.admin.get('/api/assets/'+asset).status_code,404)
        self.assertEqual(self.member.get('/api/assistant/threads/'+tid).json()[0]['status'],'complete')
        self.assertTrue((directory/'图片.png').is_file())  # Keep the original download for inspection.

    def test_recovery_downloads_only_original_project(self):
        tid,turn,directory=self.make_failed()
        with self.hub.db() as db:db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        def fake(args,cwd):
            self.assertEqual(json.loads((cwd/'hub-libtv-profile.json').read_text())['profile'],'legacy')
            if args==['account','list']:
                return {'accounts':[{'accountId':42,'isActive':True}]}
            self.assertEqual(args[:3],['download','-p','b'*32])
            Image.new('RGB',(16,24),'white').save(directory/'图片.png')
            return {'download_completed':True}
        with patch('libtv_gateway.cli',side_effect=fake) as mock:
            result=self.post(self.member,'/threads/'+tid+'/turns/'+turn+'/recover',{})
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(mock.call_count,2)

    def test_invalid_pixels_preserved_and_turn_unlocked(self):
        tid,turn,directory=self.make_failed();(directory/'图片.png').write_bytes(b'broken')
        with patch('libtv_gateway.cli') as mock:
            result=self.post(self.member,'/threads/'+tid+'/turns/'+turn+'/recover',{})
            self.assertEqual(result.status_code,502);mock.assert_not_called()
        self.assertTrue((directory/'图片.png').exists())
        self.assertEqual(self.member.get('/api/assistant/threads/'+tid).json()[0]['status'],'failed')

    def test_generation_with_real_cli_text_download(self):
        with self.hub.db() as db:db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        tid=self.post(self.member,'/threads',{}).json()['id'];calls=[]
        def run(args,**kwargs):
            a=args[1:];calls.append(a)
            if a[0]=='account':payload={'accounts':[{'accountId':42,'isActive':True}]}
            elif a[0]=='model':payload={'schema':{'modelKey':'lib-image-2.5-f'}}
            elif a[0]=='project':payload={'projectMeta':{'uuid':'c'*32}}
            elif a[0]=='download':
                Image.new('RGB',(16,24),'white').save(Path(a[-1])/'图片.png')
                return subprocess.CompletedProcess(args,0,'下载完成：图片.png','')
            else:payload={'ok':True}
            return subprocess.CompletedProcess(args,0,json.dumps(payload),'')
        data={'text':'flower','mode':'image','request_key':'text-download-request-001'}
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.profile_environment',return_value={}),patch('libtv_gateway.run_bounded',side_effect=run):
            result=self.post(self.member,'/threads/'+tid+'/send',data)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['status'],'complete')
            self.assertEqual(self.post(self.member,'/threads/'+tid+'/send',data).json()['result_asset'],result.json()['result_asset'])
        self.assertEqual(sum('--run' in a for a in calls),1)

    def test_confirmed_failure_does_not_download_or_resubmit(self):
        with self.hub.db() as db:db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        tid=self.post(self.member,'/threads',{}).json()['id']
        endpoint='/threads/'+tid
        def invoke(args,work):
            if args[0]=='account':return {'accounts':[{'accountId':42,'isActive':True}]}
            if args[0]=='model':return {'schema':{'modelKey':'lib-image-2.5-f'}}
            if args[0]=='project':return {'projectMeta':{'uuid':'b'*32}}
            if '--run' in args:raise RuntimeError('operation failed')
            self.assertEqual(args,['node','图片','-p','b'*32])
            return {'data':{'url':[],'taskInfo':{'status':3,'failedReason':'生成失败，积分已返还，请稍后再试'}}}
        request={'text':'flower','mode':'image','request_key':'confirmed-failure-request'}
        with patch('libtv_gateway.cli',side_effect=invoke) as mock:
            self.assertEqual(self.post(self.member,endpoint+'/send',request).status_code,502)
            turn=self.member.get('/api/assistant'+endpoint).json()[0]
            self.assertTrue(json.loads(turn['generation'])['terminal_failure'])
            self.assertIn('平台报告积分已返还',turn['answer'])
            self.assertEqual(self.post(self.member,endpoint+'/turns/'+turn['id']+'/recover',{}).status_code,409)
            self.assertEqual(self.post(self.member,endpoint+'/send',request).json()['id'],turn['id'])
            self.assertEqual(mock.call_count,5)

    def test_probe_preserves_partial_and_unknown_results(self):
        from assistant_images import inspect_image_node
        for data,expected in [({'url':['https://example.invalid/image.png'],'taskInfo':{'status':3}},'output'),
                              ({'taskInfo':{'status':1,'failedReason':'积分已返还'}},'unknown')]:
            self.assertEqual(inspect_image_node(lambda *_:{'data':data},'b'*32,None),expected)

if __name__=='__main__':unittest.main()
