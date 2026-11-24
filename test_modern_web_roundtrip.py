"""Isolated API acceptance: no live service or paid provider calls."""
import json
import shutil
import unittest
from pathlib import Path
from test_editor import EditorTests
from editor import probe
import test_hub as fixtures

class ModernWebRoundtripTests(EditorTests):
    def test_import_edit_reopen_update_export(self):
        task = self.sample()
        content = (self.hub.media / (task + '.mp4')).read_bytes()
        imported = self.member.post('/api/editor/footage', content=content,
            headers={**fixtures.H, 'Content-Type':'application/octet-stream', 'X-File-Name':'roundtrip-local.mp4'})
        self.assertEqual(imported.status_code, 200, imported.text)
        footage = imported.json()['id']
        payload = {'title':'隔离验收-保存重开', 'body':{
            'ratio':'1:1', 'clips':[{'task_id':footage,'start':0,'end':1.5,'volume':0}],
            'captions':[{'text':'中文保存重开 ABC 123','start':0,'end':1}],
            'stickers':[{'id':'audit-arrow','style':'solid','start':.25,'end':1.25,'x':.5,'y':.5,'width':.3}]}}
        response = self.member.post('/api/editor/projects', json=payload, headers=fixtures.H)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        reopened = next(p for p in self.member.get('/api/editor/projects').json() if p['id']==saved['id'])
        self.assertEqual(reopened['body'], saved['body'])
        self.assertEqual(reopened['body']['captions'][0]['text'], '中文保存重开 ABC 123')
        reopened['title'] = '隔离验收-二次编辑'
        reopened['body']['captions'][0]['text'] = '二次编辑后导出'
        update = self.member.post('/api/editor/projects', json=reopened, headers=fixtures.H)
        self.assertEqual(update.status_code, 200, update.text)
        updated = update.json()
        self.assertGreater(updated['version'], saved['version'])
        reloaded = next(p for p in self.member.get('/api/editor/projects').json() if p['id']==saved['id'])
        self.assertEqual(reloaded['body']['captions'][0]['text'], '二次编辑后导出')
        exported = self.member.post('/api/editor/projects/'+saved['id']+'/export',
            json={'version':updated['version'],'request_key':'modern-roundtrip-unique'}, headers=fixtures.H)
        self.assertEqual(exported.status_code, 200, exported.text)
        eid = exported.json()['id']
        self.app.state.editor.tick()
        job = next(j for j in self.member.get('/api/editor/exports').json() if j['id']==eid)
        self.assertEqual(job['state'],'ready',job)
        output = self.app.state.editor.root / (eid+'.mp4')
        duration, streams = probe(output)
        video = next(s for s in streams if s['codec_type']=='video')
        self.assertAlmostEqual(duration,1.5,delta=.12)
        self.assertEqual((video['width'],video['height']),(1080,1080))
        self.assertEqual(video['codec_name'],'h264')
        self.assertEqual(video['r_frame_rate'],'30/1')
        self.assertEqual(self.member.get('/api/editor/exports/'+eid+'/video').status_code,200)
        report = Path(__file__).parent/'modern-web-phase5'
        report.mkdir(exist_ok=True)
        shutil.copy2(output,report/'roundtrip-verified.mp4')
        (report/'roundtrip-result.json').write_text(json.dumps({'isolated':True,'steps':['import','save','reopen','update','reopen','export','download'],'duration':duration,'width':video['width'],'height':video['height'],'codec':video['codec_name'],'fps':video['r_frame_rate'],'bytes':output.stat().st_size},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__ == '__main__':
    unittest.main()
