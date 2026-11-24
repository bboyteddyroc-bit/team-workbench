"""Offline media checks: no provider requests, credentials, ASR downloads or AI charges."""
import json,os,subprocess,tempfile,unittest
import httpx
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from video_case_analysis import prepare,download,clean,FIELDS,parse_json_answer,save_answer,request

class MediaTests(unittest.TestCase):
    def test_real_ffmpeg_sampling_and_cached_cover(self):
        root=Path(__file__).resolve().parent
        ffbin=root/'tools/ffmpeg-7.1.1/ffmpeg-7.1.1-essentials_build/bin'
        self.assertTrue((ffbin/'ffmpeg.exe').is_file(),'project FFmpeg required for this verification')
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PATH':str(ffbin)+os.pathsep+os.environ.get('PATH','')}):
            base=Path(temp);case={'id':'offline-test','video':'123456789','transcript':'','transcript_source':''}
            media=base/'case-analysis'/case['id'];media.mkdir(parents=True)
            subprocess.run([str(ffbin/'ffmpeg.exe'),'-v','error','-f','lavfi','-i','color=c=blue:s=96x160:r=12:d=1.2','-c:v','mpeg4','-an','-y',str(media/'source.mp4')],check=True,timeout=30,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            provider=Mock();stages=[]
            result=prepare(SimpleNamespace(directory=base),provider,case,'job',stages.append)
            provider.post.assert_not_called()
            self.assertEqual(len(result['images']),9,result['warnings'])
            self.assertTrue(all(0<p.stat().st_size<=600000 for _,p in result['images']))
            self.assertTrue((base/'case-covers'/'offline-test.img').read_bytes().startswith(b'\xff\xd8\xff'))
            self.assertEqual(result['transcript'],'')
            self.assertEqual(result['warnings'],[])
            self.assertGreater(result['images'][-1][0],result['images'][0][0])
    def test_reject_nonprovider_media_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            for url in ('http://x.cloudfront.net/v','https://evil.example/v','https://user:pass@x.cloudfront.net/v','https://x.cloudfront.net:444/v'):
                with patch('video_case_analysis.socket.getaddrinfo') as dns,self.assertRaises(ValueError):download(url,Path(temp)/'source.mp4')
                dns.assert_not_called()
    def test_actual_kalodata_media_hostname_is_accepted(self):
        urls=[]
        def handler(request):
            urls.append(request.url.host)
            return httpx.Response(200,content=b'test-media-bytes')
        client=httpx.Client(transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as temp,patch('video_case_analysis.httpx.Client',return_value=client),patch('video_case_analysis.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
            path=Path(temp)/'source.mp4'
            download('https://openapi-video.kalodata.com/media.mp4?signature=test',path)
            self.assertEqual(path.read_bytes(),b'test-media-bytes')
            self.assertEqual(urls,['openapi-video.kalodata.com'])
    def test_lookalike_domains_and_private_dns_still_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for host in ('openapi-video.kalodata.com.evil.example','evil.kalodata.com','kalodata.com','openapi-video-kalodata.com'):
                with patch('video_case_analysis.httpx.Client') as client,self.assertRaises(ValueError):download('https://'+host+'/v',Path(temp)/'source.mp4')
                client.assert_not_called()
            with patch('video_case_analysis.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('video_case_analysis.httpx.Client') as client,self.assertRaises(ValueError):
                download('https://openapi-video.kalodata.com/v',Path(temp)/'source.mp4')
            client.assert_not_called()
    def test_redirect_to_untrusted_domain_is_not_followed(self):
        urls=[]
        def handler(request):
            urls.append(request.url.host)
            return httpx.Response(302,headers={'location':'https://evil.example/file'})
        client=httpx.Client(transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as temp,patch('video_case_analysis.httpx.Client',return_value=client),patch('video_case_analysis.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),self.assertRaises(ValueError):
            download('https://openapi-video.kalodata.com/file',Path(temp)/'source.mp4')
        self.assertEqual(urls,['openapi-video.kalodata.com'])
    def test_structured_ai_tags_are_validated_and_preserved(self):
        raw={'fields':{'summary':'结构演示'},'tag_groups':{'product':['饮具'],'format':['结构演示'],'scene':[]}}
        fields,_,_=clean(raw,'',True)
        self.assertEqual(fields['tag_groups'],raw['tag_groups'])
        raw['tag_groups']={'invented':['标签']}
        with self.assertRaises(ValueError):clean(raw,'',True)

    def test_no_transcript_never_creates_fake_quotes(self):
        raw={'fields':{k:'' for k in FIELDS},'tags':[],'evidence':{},'uncertainties':[]}
        raw['fields'].update(hook_example='invented',transcript_en='invented',transcript_zh='编造')
        fields,_,warnings=clean(raw,'',False)
        self.assertTrue(all(fields[k]=='' for k in ('hook_example','transcript_en','transcript_zh')))
        self.assertTrue(warnings)

    def test_ai_string_lists_are_preserved_without_resubmission(self):
        raw={'fields':{'replication_actions':['动作一','动作二'],'notes':None},'evidence':{'replication_actions':['第1帧','操作推断']},'tags':[],'uncertainties':[]}
        fields,evidence,_=clean(raw,'',True)
        self.assertEqual(fields['replication_actions'],'动作一\n动作二');self.assertEqual(fields['notes'],'');self.assertEqual(evidence['replication_actions'],'第1帧\n操作推断')
        raw['fields']['replication_actions']={'invented':'object'}
        with self.assertRaises(ValueError):clean(raw,'',True)
    def test_local_json_wrapper_and_unescaped_quotes(self):
        text='```json\n{"fields":{"notes":"ASR说"Hello"一句，其余未知","summary":"测试"},"tags":[],"evidence":{},"uncertainties":[]}\n```'
        result=parse_json_answer(text);self.assertEqual(result['fields']['notes'],'ASR说"Hello"一句，其余未知')
        self.assertEqual(parse_json_answer('说明\n{"fields":{"notes":"原稿"}}\n结束')['fields']['notes'],'原稿')
        for invalid in ('not json','{"fields":','{"fields":{"notes":null, BAD}}'):
            with self.assertRaises(ValueError):parse_json_answer(invalid)
    def test_analysis_receipt_is_local_idempotent_and_path_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            hub=SimpleNamespace(directory=Path(temp));raw={'fields':{'summary':'已返回'}}
            path=save_answer(hub,'case','job',raw);self.assertEqual(json.loads(path.read_text(encoding='utf-8')),raw)
            save_answer(hub,'case','job',{'different':True});self.assertEqual(json.loads(path.read_text(encoding='utf-8')),raw)
            with self.assertRaises(ValueError):save_answer(hub,'../outside','job',raw)

    def test_answer_retained_before_invalid_json_or_truncated_output(self):
        for text,finish in [('not valid JSON','stop'),('{"fields":','length')]:
            response=Mock();response.read.return_value=json.dumps({'choices':[{'finish_reason':finish,'message':{'content':text}}]}).encode()
            response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            with tempfile.TemporaryDirectory() as temp,patch('video_case_analysis.urllib.request.urlopen',return_value=response) as upstream:
                path=Path(temp)/'answer.txt'
                with self.assertRaises(ValueError):request({},[],'test-not-a-real-key',answer_path=path)
                self.assertTrue(path.exists());self.assertIn(text,path.read_text(encoding='utf-8'));self.assertEqual(upstream.call_count,1)

if __name__=='__main__':unittest.main()
