"""Regression: text-only CLI download success must publish pixels exactly once."""
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from libtv_gateway import cli
from test_assistant_chat import AssistantTests


class CliOutputTests(unittest.TestCase):
    def test_download_accepts_human_output(self):
        result=subprocess.CompletedProcess([],0,'已下载：图片.png\n','')
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.subprocess.run',return_value=result) as run:
            self.assertTrue(cli(['download','-p','a'*32],'.')['download_completed'])
            self.assertEqual(run.call_count,1)

    def test_non_download_still_requires_json(self):
        result=subprocess.CompletedProcess([],0,'unknown response','')
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.subprocess.run',return_value=result):
            with self.assertRaisesRegex(RuntimeError,'返回格式无法识别'):cli(['node','create'],' .')

    def test_download_nonzero_is_not_success(self):
        result=subprocess.CompletedProcess([],1,'已下载','unauthorized')
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.subprocess.run',return_value=result):
            with self.assertRaises(RuntimeError):cli(['download'],'.')


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
        self.assertFalse((directory/'图片.png').exists())

    def test_recovery_downloads_only_original_project(self):
        tid,turn,directory=self.make_failed()
        def fake(args,cwd):
            self.assertEqual(args[:3],['download','-p','b'*32])
            Image.new('RGB',(16,24),'white').save(directory/'图片.png')
            return {'download_completed':True}
        with patch('libtv_gateway.cli',side_effect=fake) as mock:
            result=self.post(self.member,'/threads/'+tid+'/turns/'+turn+'/recover',{})
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(mock.call_count,1)

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
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.subprocess.run',side_effect=run):
            result=self.post(self.member,'/threads/'+tid+'/send',data)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['status'],'complete')
            self.assertEqual(self.post(self.member,'/threads/'+tid+'/send',data).json()['result_asset'],result.json()['result_asset'])
        self.assertEqual(sum('--run' in a for a in calls),1)

if __name__=='__main__':unittest.main()
