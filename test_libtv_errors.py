"""Safe diagnostics must never replay a failed paid invocation or leak raw output."""
import subprocess,unittest,json,tempfile
from pathlib import Path
from unittest.mock import patch
from libtv_gateway import cli,decoded,error_excerpt

class LibTVErrorTests(unittest.TestCase):
    def setUp(self):
        # Diagnostics tests fake the isolated CLI environment, never use a real
        # login profile or weaken production identity validation.
        p=patch('libtv_gateway.profile_environment',return_value={});p.start();self.addCleanup(p.stop)
    def failure(self,args,text):
        result=subprocess.CompletedProcess([],1,'',text+' secret=DO_NOT_EXPOSE')
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.run_bounded',return_value=result) as run:
            with self.assertRaises(RuntimeError) as exc:cli(args,'.')
            self.assertEqual(run.call_count,1)
            message=str(exc.exception);self.assertNotIn('DO_NOT_EXPOSE',message)
            return message
    def test_auth_error(self):
        message=self.failure(['project','create'],'code: 10001 用户未授权')
        self.assertIn('登录已失效',message);self.assertIn('libtv login web',message);self.assertIn('未自动重试',message)
    def test_not_logged_in_401(self):
        message=self.failure(['download','-p','x','-n','成片'],"API Request Error: {\n  code: 401,\n  msg: '未登录'\n}\n接口错误 [401]: 未登录")
        self.assertIn('登录已失效',message);self.assertIn('401',message);self.assertIn('结果下载',message)
        self.assertIn('不需要去官网重做视频',message)
    def test_quota(self):self.assertIn('可用额度不足',self.failure(['node','create','--run'],'insufficient credits'))
    def test_unknown_network(self):self.assertIn('操作结果可能未知',self.failure(['node','create','--run'],'fetch failed ECONNRESET'))
    def test_missing_canvas(self):self.assertIn('找不到',self.failure(['node','list'],'拉取画布失败 [10004]: 画布不存在'))
    def test_model_not_found_is_not_missing_canvas(self):
        message=self.failure(['node','create'],'未找到模型名字：StarVideo 2.0')
        self.assertIn('模型名称未被 CLI 识别',message)
        self.assertNotIn('可能已被删除',message)
    def test_compliance_names_reference(self):
        message=self.failure(['node','--run'],'校验失败：您有素材未通过Seedance的合规检测；未通过合规的节点：参考4（uuid）')
        self.assertIn('参考4',message)
        self.assertIn('生成尚未启动',message)
        self.assertNotIn('接口 未知',message)
    def test_download_supplies_watermark_assertion(self):
        result=subprocess.CompletedProcess([],0,'downloaded','')
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.run_bounded',return_value=result) as run:
            cli(['download','-p','canvas','-o','output'],'.')
            command=run.call_args.args[0]
            self.assertIn('--watermark',command)
            self.assertEqual(command[-2:],['-o','output'])
    def test_generic(self):
        message=self.failure(['project','create'],'code: 50000 opaque')
        self.assertIn('画布操作未成功',message);self.assertIn('50000',message);self.assertIn('不要直接重新生成',message)
    def test_diagnostic_preserves_unknown_error_without_secrets(self):
        raw=json.dumps({'code':54321,'message':'invalid resolution','token':'PRIVATE_SECRET','prompt':'PRIVATE_PROMPT'})
        result=subprocess.CompletedProcess([],1,raw,'')
        with tempfile.TemporaryDirectory() as directory, patch('libtv_gateway.shutil.which',return_value='libtv.exe'), patch('libtv_gateway.run_bounded',return_value=result) as run:
            with self.assertRaises(RuntimeError) as exc:cli(['node','--run'],directory)
            record=json.loads((Path(directory)/'cli-diagnostics.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(run.call_count,1)
            self.assertEqual(record['stage'],'启动生成')
            self.assertIn(record['diagnostic_id'],str(exc.exception))
            self.assertIn('invalid resolution',record['excerpt'])
            self.assertNotIn('PRIVATE',json.dumps(record))
    def test_excerpt_redacts_credentials_and_signed_urls(self):
        text=error_excerpt('Error: fetch failed https://example.com/a?signature=PRIVATE\nAuthorization: Bearer PRIVATE\nprompt: PRIVATE')
        self.assertIn('fetch failed',text)
        self.assertNotIn('PRIVATE',text)
        self.assertNotIn('example.com',text)
    def test_gbk_output_is_decoded(self):
        gbk="拉取画布失败 [10001]: 用户未授权".encode('gbk')
        result=subprocess.CompletedProcess([],1,b'',gbk)
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.run_bounded',return_value=result):
            with self.assertRaises(RuntimeError) as exc:cli(['node','list'],'.')
        self.assertIn('登录已失效',str(exc.exception))
        self.assertEqual(decoded('already-text'),'already-text')

if __name__=='__main__':unittest.main()
