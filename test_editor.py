import json
import shutil
import unittest
from fastapi.testclient import TestClient
from editor import run,probe
import test_hub as fixtures


class EditorTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    account=fixtures.HubTests.account
    enqueue=fixtures.HubTests.enqueue

    def sample(self):
        account=self.account(self.admin)
        task=self.enqueue(self.member,account).json()['id']
        with self.hub.db() as db:db.execute("UPDATE tasks SET state='ready' WHERE id=?",(task,))
        run([shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=s=160x240:r=24:d=2','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(self.hub.media/(task+'.mp4'))])
        return task

    def project(self,task):
        return {'title':'剪辑测试','body':{'ratio':'9:16','clips':[{'task_id':task,'start':.2,'end':1,'volume':0},{'task_id':task,'start':1,'end':1.8,'volume':1}],'captions':[{'text':'测试字幕 {hello} \\N','start':0,'end':1.2}]}}

    def test_footage_import_and_permission_error(self):
        from pathlib import Path
        from unittest.mock import patch
        task=self.sample()
        content=(self.hub.media/(task+'.mp4')).read_bytes()
        headers={**fixtures.H,'Content-Type':'application/octet-stream','X-File-Name':'camera.mp4'}
        response=self.member.post('/api/editor/footage',content=content,headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        fid=response.json()['id']
        items=self.member.get('/api/editor/library').json()['items']
        self.assertTrue(any(i['id']==fid and i.get('kind')=='footage' for i in items))
        self.assertEqual(self.member.get('/api/tasks/'+fid+'/video').status_code,200)
        original=Path.open
        def denied(path,*args,**kwargs):
            if path.suffix=='.part':raise PermissionError('denied')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',denied):
            response=self.member.post('/api/editor/footage',content=content,headers=headers)
        self.assertEqual(response.status_code,503,response.text)
        self.assertIn('写入权限',response.json()['detail'])

    def test_http_phone_gateway_real_upload(self):
        from mobile_http import create_phone_app
        origin='http://192.168.100.10:8000'
        task=self.sample();content=(self.hub.media/(task+'.mp4')).read_bytes()
        d=self.member.post('/api/mobile/transfers',json={'exports':[]},headers=fixtures.H).json()
        self.assertTrue(d['url'].startswith(origin+'/mobile/#'))
        phone_app=create_phone_app(self.app,origin=origin,networks=['192.168.100.0/23'])
        with TestClient(phone_app,base_url=origin,client=('192.168.100.50',1234)) as phone:
            headers={'X-Hub-Request':'1','Origin':origin,'X-Transfer-Token':d['url'].split('#')[1],'X-File-Name':'http-phone.mp4'}
            response=phone.post('/api/mobile/upload',content=content,headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            fid=response.json()['id']
            items=self.member.get('/api/editor/library').json()['items']
            self.assertTrue(any(i['id']==fid and i['title']=='http-phone.mp4' for i in items))
            self.assertFalse(any(i['id']==fid for i in self.admin.get('/api/editor/library').json()['items']))
            self.assertEqual(phone.get('/api/editor/library').status_code,404)
            self.assertEqual(phone.post('/api/login',json={},headers=headers).status_code,404)
    def test_mobile_upload_into_editor_library(self):
        task=self.sample()
        content=(self.hub.media/(task+'.mp4')).read_bytes()
        d=self.member.post('/api/mobile/transfers',json={'exports':[]},headers=fixtures.H).json()
        token=d['url'].split('#')[1]
        phone=TestClient(self.app,base_url='http://127.0.0.1:8765')
        headers={**fixtures.H,'X-Transfer-Token':token,'X-File-Name':'phone.mp4'}
        # Use same configured host as existing test client.
        response=phone.post('/api/mobile/upload',content=content,headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        fid=response.json()['id']
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with self.hub.db() as db:row=db.execute('SELECT * FROM edit_footage WHERE id=?',(fid,)).fetchone()
        day=datetime.fromtimestamp(row['created'],ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        path=self.app.state.editor.footage/day/fid
        self.assertTrue(path.is_file())
        self.assertEqual(self.member.get('/api/tasks/'+fid+'/video').status_code,200)
        self.assertTrue(any(i['id']==fid for i in self.member.get('/api/editor/library').json()['items']))
        # Legacy flat files remain readable without changing project IDs.
        path.rename(self.app.state.editor.footage/fid)
        self.assertEqual(self.member.get('/api/tasks/'+fid+'/video').status_code,200)
        self.assertTrue(any(i['id']==fid for i in self.member.get('/api/editor/library').json()['items']))
        self.assertEqual(self.member.post('/api/mobile/upload',content=content,headers=fixtures.H).status_code,410)
        self.assertEqual(self.member.get('/api/mobile/received').status_code,200)

    def test_export_thumbnail_owner_and_cache(self):
        from unittest.mock import patch
        task=self.sample();saved=self.member.post('/api/editor/projects',json=self.project(task),headers=fixtures.H).json()
        job=self.member.post('/api/editor/projects/'+saved['id']+'/export',json={'version':saved['version'],'request_key':'thumb-export-test-01'},headers=fixtures.H).json()
        self.app.state.editor.tick()
        url='/api/editor/exports/'+job['id']+'/thumbnail'
        r=self.member.get(url);self.assertEqual(r.status_code,200,r.text if r.status_code!=200 else '')
        self.assertEqual(r.headers['content-type'],'image/jpeg')
        with patch('editor.run',side_effect=AssertionError('cache miss')):self.assertEqual(self.member.get(url).content,r.content)
        self.assertEqual(self.admin.get(url).status_code,404)

    def test_thumbnail_cached_and_owner_scoped(self):
        from unittest.mock import patch
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch('editor_media_cache.ROOT',Path(directory)):
            task=self.sample()
            url='/api/editor/thumbnail/'+task+'?at=0.2'
            first=self.member.get(url)
            self.assertEqual(first.status_code,200,first.text if first.status_code!=200 else '')
            self.assertEqual(first.headers['content-type'],'image/jpeg')
            with patch('editor.run',side_effect=AssertionError('cache miss')):
                self.assertEqual(self.member.get(url).content,first.content)
                self.assertEqual(len(self.member.get('/api/editor/library').json()['items']),1)
            self.member.post('/api/logout',headers=fixtures.H)
            self.assertIn(self.member.get(url).status_code,(401,403))

    def test_multitrack_cut_frames_and_overlap(self):
        red=self.sample()
        with self.hub.db() as db:account=db.execute('SELECT account_id FROM tasks WHERE id=?',(red,)).fetchone()[0]
        green=self.enqueue(self.member,account,'second-color-test').json()['id']
        with self.hub.db() as db:db.execute("UPDATE tasks SET state='ready' WHERE id=?",(green,))
        for task,color in [(red,'red'),(green,'lime')]:
            run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=160x240:r=24:d=2','-c:v','libx264','-pix_fmt','yuv420p',str(self.hub.media/(task+'.mp4'))])
        data={'title':'Multi','body':{'ratio':'9:16','tracks':[{'id':'upper','muted':True},{'id':'lower','muted':False}],
            'clips':[{'task_id':red,'start':0,'end':1,'at':0,'track':'lower','volume':1},{'task_id':green,'start':0,'end':1,'at':1,'track':'lower','volume':1}],'captions':[]}}
        saved=self.member.post('/api/editor/projects',json=data,headers=fixtures.H).json()
        self.assertEqual(saved['body']['schema_version'],4)
        def export(project,key):
            response=self.member.post('/api/editor/projects/'+project['id']+'/export',json={'version':project['version'],'request_key':key},headers=fixtures.H)
            self.assertEqual(response.status_code,200,response.text);eid=response.json()['id'];self.app.state.editor.tick()
            job=next(j for j in self.member.get('/api/editor/exports').json() if j['id']==eid);self.assertEqual(job['state'],'ready',job)
            return self.app.state.editor.root/(eid+'.mp4')
        output=export(saved,'multitrack-cut-frames')
        def pixels(path):
            raw=run([shutil.which('ffmpeg'),'-v','error','-i',str(path),'-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'])
            return [tuple(raw[i:i+3]) for i in range(0,len(raw),3)]
        self.assertEqual(next(s for s in probe(output)[1] if s['codec_type']=='video')['r_frame_rate'],'30/1')
        colors=pixels(output);self.assertEqual(len(colors),60)
        for pixel in colors:self.assertGreater(max(pixel),100,'Unexpected black frame')
        self.assertGreater(colors[29][0],colors[29][1]);self.assertGreater(colors[30][1],colors[30][0])
        saved['body']['clips'][0]['end']=2;saved['body']['clips'][1].update(at=.5,track='upper')
        saved=self.member.post('/api/editor/projects',json=saved,headers=fixtures.H).json()
        colors=pixels(export(saved,'multitrack-overlap-frames'))
        self.assertGreater(colors[0][0],colors[0][1]);self.assertGreater(colors[25][1],colors[25][0]);self.assertGreater(colors[50][0],colors[50][1])
        self.assertTrue(saved['body']['tracks'][0]['muted'])

    def test_compound_cut_save_and_export(self):
        import subprocess
        task=self.sample()
        body={'ratio':'9:16','clips':[{'task_id':task,'start':0,'end':2,'at':0,'track':'video-main','volume':0,'edit_compound':'whole'}],
              'captions':[{'text':'compound','start':0,'end':2,'track':'caption-main','edit_compound':'whole'}],'audio_clips':[]}
        code="const C=require('./static/compound-edit.js');let b=JSON.parse(require('fs').readFileSync(0,'utf8'));Object.assign(b,C.edit(b,'whole',{split:1,rightId:'right'}));Object.assign(b,C.edit(b,'right',{end:1.5}));process.stdout.write(JSON.stringify(b));"
        body=json.loads(subprocess.run(['node','-e',code],input=json.dumps(body),text=True,capture_output=True,check=True).stdout)
        response=self.member.post('/api/editor/projects',json={'title':'Compound cut','body':body},headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text);saved=response.json()
        self.assertEqual(saved['body']['clips'][1]['edit_compound'],'right')
        self.assertEqual(saved['body']['clips'][1]['at'],1)
        self.assertEqual(saved['body']['captions'][1]['end'],1.5)
        restore="const C=require('./static/compound-edit.js');let b=JSON.parse(require('fs').readFileSync(0,'utf8'));Object.assign(b,C.edit(b,'right',{end:2}));process.stdout.write(JSON.stringify(b));"
        restored=json.loads(subprocess.run(['node','-e',restore],input=json.dumps(saved['body']),text=True,capture_output=True,check=True).stdout)
        self.assertEqual(restored['clips'][1]['end'],2)
        self.assertEqual(restored['captions'][1]['end'],2)

        self.assertEqual(self.member.get('/api/editor/projects').json()[0]['body'],saved['body'])
        response=self.member.post('/api/editor/projects/'+saved['id']+'/export',json={'version':saved['version'],'request_key':'compound-cut-export'},headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text);eid=response.json()['id'];self.app.state.editor.tick()
        job=next(j for j in self.member.get('/api/editor/exports').json() if j['id']==eid);self.assertEqual(job['state'],'ready',job)
        output=self.app.state.editor.root/(eid+'.mp4');duration,streams=probe(output)
        self.assertAlmostEqual(duration,1.5,delta=.1)
        self.assertEqual(next(s for s in streams if s['codec_type']=='video')['r_frame_rate'],'30/1')
        raw=run([shutil.which('ffmpeg'),'-v','error','-i',str(output),'-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'])
        self.assertEqual(len(raw)//3,45)
        for i in range(0,len(raw),3):self.assertGreater(max(raw[i:i+3]),20,'Unexpected black frame')

    def test_bundle_metadata_roundtrip_and_validation(self):
        task=self.sample();data=self.project(task)
        for clip in data['body']['clips']:
            clip.update(edit_group='group-1',edit_compound='compound-1')
        data['body']['captions'][0].update(edit_group='group-1',edit_compound='compound-1')
        response=self.member.post('/api/editor/projects',json=data,headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text)
        saved=response.json()
        self.assertEqual(saved['body']['clips'][0]['edit_compound'],'compound-1')
        self.assertEqual(saved['body']['captions'][0]['edit_group'],'group-1')
        self.assertEqual(self.member.get('/api/editor/projects').json()[0]['body'],saved['body'])
        self.assertEqual(self.admin.get('/api/editor/projects').json(),[])
        data['body']['clips'][0]['edit_group']={'bad':True}
        self.assertEqual(self.member.post('/api/editor/projects',json=data,headers=fixtures.H).status_code,400)

    def test_render_and_project_privacy(self):
        task=self.sample();data=self.project(task)
        response=self.member.post('/api/editor/projects',json=data,headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text);saved=response.json()
        self.assertEqual(self.admin.get('/api/editor/projects').json(),[])
        forged=dict(saved,title='overwrite')
        self.assertEqual(self.admin.post('/api/editor/projects',json=forged,headers=fixtures.H).status_code,404)
        export={'version':saved['version'],'request_key':'export-request-000001'}
        url='/api/editor/projects/'+saved['id']+'/export'
        first=self.member.post(url,json=export,headers=fixtures.H)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.member.post(url,json=export,headers=fixtures.H).json(),first.json())
        eid=first.json()['id'];self.app.state.editor.tick()
        state=self.member.get('/api/editor/exports').json()[0]
        self.assertEqual(state['state'],'ready',state)
        duration,streams=probe(self.app.state.editor.root/(eid+'.mp4'))
        self.assertAlmostEqual(duration,1.6,delta=.12)
        video=next(s for s in streams if s['codec_type']=='video')
        self.assertEqual((video['width'],video['height']),(1080,1920))
        self.assertEqual(video['codec_name'],'h264');self.assertEqual(video['pix_fmt'],'yuv420p');self.assertEqual(video['r_frame_rate'],'30/1')
        audio=next(s for s in streams if s['codec_type']=='audio')
        self.assertEqual(audio['codec_name'],'aac');self.assertEqual(audio['sample_rate'],'48000');self.assertEqual(audio['channels'],2)
        self.assertEqual(self.admin.get('/api/editor/exports/'+eid+'/video').status_code,404)
        self.assertEqual(self.member.get('/api/editor/exports/'+eid+'/video').status_code,200)
        self.assertTrue((self.hub.media/(task+'.mp4')).exists())

    def test_unreadable_export_is_reported_not_faked(self):
        from unittest.mock import patch
        task=self.sample();data=self.project(task)
        saved=self.member.post('/api/editor/projects',json=data,headers=fixtures.H).json()
        job=self.member.post('/api/editor/projects/'+saved['id']+'/export',
            json={'version':saved['version'],'request_key':'unreadable-export-01'},headers=fixtures.H).json()
        with patch('editor.readable',return_value=False),patch('editor.ensure_shared',return_value=False):
            self.app.state.editor.tick()
        row=self.member.get('/api/editor/exports').json()[0]
        self.assertEqual(row['state'],'failed',row)
        self.assertIn('无法读取',row['error'])
        real=self.app.state.editor.root/(job['id']+'.mp4')
        self.assertTrue(real.is_file(),'成品文件仍应保留以便修复')
        with self.hub.db() as db:db.execute("UPDATE edit_exports SET state='ready',error='' WHERE id=?",(job['id'],))
        with patch('editor.readable',return_value=False):
            response=self.member.get('/api/editor/exports/'+job['id']+'/video')
        self.assertEqual(response.status_code,503,response.text)
        self.assertIn('无法读取',response.json()['detail'])
        self.assertEqual(self.member.get('/api/editor/exports/'+job['id']+'.mp4').status_code,404)
        self.assertEqual(self.member.get('/api/editor/exports/'+job['id']+'/video').status_code,200)

    def test_speed_changes_timeline_and_export(self):
        from editor import atempo_chain, timeline_duration
        task=self.sample();data=self.project(task)
        data['body']['clips']=[{'task_id':task,'start':0,'end':2,'volume':0,'speed':2}]
        data['body']['captions']=[]
        response=self.member.post('/api/editor/projects',json=data,headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text);saved=response.json()
        self.assertEqual(saved['body']['clips'][0]['speed'],2)
        job=self.member.post('/api/editor/projects/'+saved['id']+'/export',
            json={'version':saved['version'],'request_key':'speed-export-000001'},headers=fixtures.H).json()
        self.app.state.editor.tick()
        self.assertEqual(self.member.get('/api/editor/exports').json()[0]['state'],'ready')
        duration,_=probe(self.app.state.editor.root/(job['id']+'.mp4'))
        self.assertAlmostEqual(duration,1.0,delta=.15)
        for bad in (.1,4.5,0,'fast'):
            body=dict(saved['body'],clips=[{'task_id':task,'start':0,'end':2,'volume':0,'speed':bad}])
            self.assertEqual(self.member.post('/api/editor/projects',json={'title':'越界','body':body},headers=fixtures.H).status_code,400,bad)
        self.assertEqual(atempo_chain(1),'')
        self.assertEqual(atempo_chain(4),'atempo=2,atempo=2.000000')
        self.assertEqual(timeline_duration({'clips':[{'start':0,'end':4,'speed':.5}]}),8)

    def test_invalid_timing_and_stale_project(self):
        task=self.sample();data=self.project(task)
        data['body']['clips'][0]['end']=99
        self.assertEqual(self.member.post('/api/editor/projects',json=data,headers=fixtures.H).status_code,400)
        data=self.project(task);saved=self.member.post('/api/editor/projects',json=data,headers=fixtures.H).json()
        self.assertEqual(self.member.post('/api/editor/projects',json=saved,headers=fixtures.H).status_code,200)
        self.assertEqual(self.member.post('/api/editor/projects',json=saved,headers=fixtures.H).status_code,409)
        data=self.project('../vault.key')
        self.assertEqual(self.member.post('/api/editor/projects',json=data,headers=fixtures.H).status_code,400)

    def test_audio_mix(self):
        task=self.sample();audio=self.hub.directory/'tone.wav'
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=1','-c:a','pcm_s16le',str(audio)])
        uploaded=self.member.post('/api/assets',content=audio.read_bytes(),headers={**fixtures.H,'Content-Type':'audio/wav','X-File-Name':'tone.wav'}).json()
        data=self.project(task);data['body']['audio']={'asset_id':uploaded['id'],'volume':.4}
        saved=self.member.post('/api/editor/projects',json=data,headers=fixtures.H).json()
        job=self.member.post('/api/editor/projects/'+saved['id']+'/export',json={'version':saved['version'],'request_key':'audio-export-000001'},headers=fixtures.H).json()
        self.app.state.editor.tick()
        self.assertEqual(self.member.get('/api/editor/exports').json()[0]['state'],'ready')
        _,streams=probe(self.app.state.editor.root/(job['id']+'.mp4'))
        self.assertTrue(any(s['codec_type']=='audio' for s in streams))

    def test_detached_original_audio_offset_and_replacement_export(self):
        import array
        task=self.sample()
        original=self.hub.media/(task+'.mp4')
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=red:s=160x240:r=24:d=2',
             '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-threads','1','-c:a','aac',str(original)])
        with self.hub.db() as db:account=db.execute('SELECT account_id FROM tasks WHERE id=?',(task,)).fetchone()[0]
        replacement=self.enqueue(self.member,account,key='replacement-000002').json()['id']
        with self.hub.db() as db:db.execute("UPDATE tasks SET state='ready' WHERE id=?",(replacement,))
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=blue:s=160x240:r=24:d=2','-c:v','libx264','-threads','1',str(self.hub.media/(replacement+'.mp4'))])
        data=self.project(replacement)
        data['body']['clips']=[{'task_id':replacement,'start':0,'end':2,'volume':0}]
        data['body']['captions']=[]
        data['body']['audio_clips']=[{'task_id':task,'start':.2,'end':1.2,'at':.5,'volume':.7,'locked':True}]
        response=self.member.post('/api/editor/projects',json=data,headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text)
        saved=response.json()
        self.assertEqual(saved['body']['audio_clips'][0]['at'],.5)
        job=self.member.post('/api/editor/projects/'+saved['id']+'/export',
            json={'version':saved['version'],'request_key':'detach-export-00001'},headers=fixtures.H).json()
        self.app.state.editor.tick()
        self.assertEqual(self.member.get('/api/editor/exports').json()[0]['state'],'ready')
        output=self.app.state.editor.root/(job['id']+'.mp4')
        pcm=array.array('h',run([shutil.which('ffmpeg'),'-v','error','-i',str(output),'-vn','-ac','1','-ar','8000','-f','s16le','-']))
        def power(start,end):
            samples=pcm[int(start*8000):int(end*8000)]
            return sum(v*v for v in samples)/len(samples)
        self.assertGreater(power(.7,1.2),power(.1,.3)+10000)
        self.assertLess(power(1.7,1.9),power(.7,1.2)/100)
        bad=self.project(replacement);bad['body']['audio_clips']=[dict(data['body']['audio_clips'][0],task_id=replacement)]
        self.assertEqual(self.member.post('/api/editor/projects',json=bad,headers=fixtures.H).status_code,400)
        bad['body']['audio_clips'][0]['task_id']='missing-task'
        self.assertEqual(self.member.post('/api/editor/projects',json=bad,headers=fixtures.H).status_code,400)

    def test_waveform_fades_and_mute(self):
        import array
        task=self.sample();path=self.hub.media/(task+'.mp4')
        run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=red:s=160x240:r=24:d=2','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-threads','1','-c:a','aac',str(path)])
        wave=self.member.get('/api/editor/waveform/'+task)
        self.assertEqual(wave.status_code,200)
        self.assertGreater(max(wave.json()['peaks']),.05)
        self.assertLessEqual(len(wave.json()['peaks']),1200)
        self.assertEqual(self.member.get('/api/editor/waveform/missing').status_code,400)
        data=self.project(task);data['body']['clips']=[dict(task_id=task,start=0,end=2,volume=0)];data['body']['captions']=[]
        data['body']['audio_clips']=[dict(task_id=task,start=0,end=2,at=0,volume=1,locked=True,muted=False,fade_in=.8,fade_out=.8)]
        saved=self.member.post('/api/editor/projects',json=data,headers=fixtures.H).json()
        self.assertEqual(saved['body']['audio_clips'][0]['fade_in'],.8)
        with self.hub.db() as db:owner=db.execute('SELECT owner FROM tasks WHERE id=?',(task,)).fetchone()[0]
        for muted in (False,True):
            body=saved['body'];body['audio_clips'][0]['muted']=muted
            self.app.state.editor.render('wave-'+str(muted),body,owner)
            output=self.app.state.editor.root/('wave-'+str(muted)+'.mp4')
            pcm=array.array('h',run([shutil.which('ffmpeg'),'-v','error','-i',str(output),'-vn','-ac','1','-ar','8000','-f','s16le','-']))
            def power(a,b):
                values=pcm[int(a*8000):int(b*8000)];return sum(v*v for v in values)/len(values)
            if muted:self.assertLess(power(.9,1.1),10)
            else:
                self.assertGreater(power(.9,1.1),power(.05,.15)*5)
                self.assertGreater(power(.9,1.1),power(1.85,1.95)*5)
        data['body']['audio_clips'][0]['fade_in']=3
        self.assertEqual(self.member.post('/api/editor/projects',json=data,headers=fixtures.H).status_code,400)
