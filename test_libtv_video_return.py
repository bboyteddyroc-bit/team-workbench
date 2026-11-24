"""Video result return regressions: no paid provider calls in this suite."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import test_hub as fixtures


class VideoReturnTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login

    def post(self,path,data=None,client=None):
        return (client or self.member).post('/api/libtv'+path,json=data or {},headers=fixtures.H)

    def failed(self,content=b'valid-video',suffix='.mp4'):
        jid='c'*32
        uid=self.member.get('/api/me').json()['id']
        payload=json.dumps({'prompt':'test','duration':5,'model':'star-video2','resolution':'720p'})
        with self.hub.db() as db:
            db.execute("INSERT INTO libtv_jobs(id,owner,request_key,payload,state,created,updated,project) VALUES(?,?,?,?,'attention',0,0,?)",(jid,uid,'video-return-fixture',payload,'a'*32))
        output=self.hub.directory/'libtv'/jid/'download'
        output.mkdir(parents=True)
        source=output/('成片'+suffix)
        if content is not None:source.write_bytes(content)
        return jid,source

    def test_cached_recovery_private_idempotent_and_editor(self):
        jid,source=self.failed(suffix='.MP4')
        with patch('libtv_gateway.cli') as cli,patch('editor.probe',return_value=(5,[{'codec_type':'video'}])):
            result=self.post('/jobs/'+jid+'/recover')
            self.assertEqual(result.status_code,200,result.text)
            aid=result.json()['asset_id']
            self.assertEqual(self.post('/jobs/'+jid+'/recover').json()['asset_id'],aid)
            cli.assert_not_called()
        self.assertFalse(source.exists())
        self.assertEqual(self.member.get('/api/assets/'+aid).content,b'valid-video')
        self.assertEqual(self.member.get('/api/tasks/'+jid+'/video').status_code,200)
        with patch('editor.probe',return_value=(5,[{'codec_type':'video'}])):
            self.assertIn(jid,[r['id'] for r in self.member.get('/api/editor/library').json()['items']])
        self.assertEqual(self.admin.get('/api/assets/'+aid).status_code,404)
        self.assertEqual(self.post('/jobs/'+jid+'/recover',client=self.admin).status_code,404)

    def test_missing_cache_only_downloads_original(self):
        jid,source=self.failed(content=None)
        calls=[]
        def download(args,cwd):
            calls.append(args)
            if args[0]!='download':return {}
            self.assertEqual(args[:5],['download','-p','a'*32,'-n','成片'])
            source.write_bytes(b'video')
        with patch('libtv_gateway.cli',side_effect=download),patch('editor.probe',return_value=(5,[{'codec_type':'video'}])):
            self.assertEqual(self.post('/jobs/'+jid+'/recover').status_code,200)
            self.assertEqual(calls[0][0],'node')  # canvas is checked before any download
            self.assertEqual(len([c for c in calls if c[0]=='download']),1)

    def test_invalid_video_preserved_and_no_ready_asset(self):
        jid,source=self.failed()
        with patch('libtv_gateway.cli') as cli,patch('editor.probe',side_effect=ValueError('媒体处理失败')):
            self.assertEqual(self.post('/jobs/'+jid+'/recover').status_code,502)
            cli.assert_not_called()
        self.assertTrue(source.exists())
        with self.hub.db() as db:
            row=db.execute('SELECT state,asset_id,runner,error FROM libtv_jobs WHERE id=?',(jid,)).fetchone()
        self.assertEqual((row['state'],row['asset_id'],row['runner']),('attention','',0))
        self.assertIn('媒体处理失败',row['error'])

    def test_database_failure_preserves_bytes_then_recover(self):
        jid,source=self.failed()
        with self.hub.db() as db:
            db.execute("CREATE TRIGGER fail_video_asset BEFORE INSERT ON assets BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with patch('libtv_gateway.cli') as cli,patch('editor.probe',return_value=(5,[{'codec_type':'video'}])):
            self.assertEqual(self.post('/jobs/'+jid+'/recover').status_code,502)
            self.assertEqual(source.read_bytes(),b'valid-video')
            with self.hub.db() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM assets').fetchone()[0],0)
                db.execute('DROP TRIGGER fail_video_asset')
            self.assertEqual(self.post('/jobs/'+jid+'/recover').status_code,200)
            cli.assert_not_called()

    def test_in_progress_recovery_does_not_download(self):
        jid,_=self.failed()
        with self.hub.db() as db:db.execute("UPDATE libtv_jobs SET state='importing' WHERE id=?",(jid,))
        with patch('libtv_gateway.cli') as cli:
            self.assertEqual(self.post('/jobs/'+jid+'/recover').status_code,409)
            cli.assert_not_called()

    def test_multiple_results_retained_for_manual_check(self):
        jid,source=self.failed()
        source.with_name('other.mp4').write_bytes(b'other')
        with patch('libtv_gateway.cli') as cli:
            self.assertEqual(self.post('/jobs/'+jid+'/recover').status_code,502)
            cli.assert_not_called()
        self.assertTrue(source.exists())

    def test_download_text_complete_pipeline_no_duplicate_generation(self):
        with self.hub.db() as db:db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        calls=[]
        def execute(command,**kwargs):
            args=command[1:];calls.append(args)
            out={'account':{'accounts':[{'accountId':42,'isActive':True}]},'model':{'schema':{'modelKey':'star-video2'}},'project':{'projectMeta':{'uuid':'a'*32}}}.get(args[0],{'ok':True})
            if args[0]=='node' and args[1]=='成片' and '--run' not in args:out={'data':{'url':['https://example.test/video.mp4']}}
            if args[0]=='download':
                (Path(args[-1])/'成片.mp4').write_bytes(b'video')
                return subprocess.CompletedProcess(command,0,'下载完成：成片.mp4','')
            return subprocess.CompletedProcess(command,0,json.dumps(out),'')
        with patch('libtv_gateway.shutil.which',return_value='libtv.exe'),patch('libtv_gateway.subprocess.run',side_effect=execute),patch('editor.probe',return_value=(5,[{'codec_type':'video'}])):
            payload={'prompt':'video test','duration':5,'request_key':'video-text-download-request'}
            result=self.post('/jobs',payload)
            self.assertEqual(result.status_code,200,result.text)
            repeated=self.post('/jobs',payload)
            self.assertEqual(repeated.json()['asset_id'],result.json()['asset_id'])
        self.assertEqual(sum('--run' in args for args in calls),1)
        self.assertEqual(sum(args[0]=='download' for args in calls),1)

if __name__=='__main__':unittest.main()
