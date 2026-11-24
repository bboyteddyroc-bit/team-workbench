import json
import shutil
import subprocess
import unittest
from pathlib import Path

import test_hub as fixtures


class SfxTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login

    def seed(self):
        root=Path(self.hub.directory)/'sfx'
        root.mkdir(parents=True,exist_ok=True)
        ffmpeg=shutil.which('ffmpeg')
        self.assertTrue(ffmpeg,'需要 ffmpeg 才能生成测试音效')
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','sine=frequency=880:duration=0.6',
                        '-c:a','libmp3lame','-b:a','96k',str(root/'demo.mp3')],check=True)
        size=(root/'demo.mp3').stat().st_size
        items=[
            {'id':'demo-whoosh','name':'测试掠过','name_en':'Demo whoosh','category':'transition',
             'tags':['音效','whoosh'],'file':'demo.mp3','duration':0.6,'bytes':size,'source':'Mixkit',
             'source_url':'https://example.test/whoosh','license':'测试许可'},
            {'id':'demo-hit','name':'测试撞击','name_en':'Demo hit','category':'impact',
             'tags':['音效','impact'],'file':'demo.mp3','duration':0.6,'bytes':size,'source':'Mixkit',
             'source_url':'https://example.test/impact','license':'测试许可'},
        ]
        (root/'index.json').write_text(json.dumps({'version':1,'license':'测试许可','source':'https://example.test',
            'categories':[{'key':'transition','label':'转场'},{'key':'impact','label':'打击'},{'key':'ambient','label':'环境'}],
            'items':items},ensure_ascii=False),encoding='utf-8')
        return root

    def test_list_filters_and_categories(self):
        self.seed()
        anon=fixtures.TestClient(self.app,base_url=fixtures.BASE)
        self.assertEqual(anon.get('/api/editor/sfx').status_code,401)
        data=self.member.get('/api/editor/sfx').json()
        self.assertEqual([i['id'] for i in data['items']],['demo-whoosh','demo-hit'])
        self.assertEqual(data['total'],2)
        self.assertEqual(data['license'],'测试许可')
        self.assertTrue(data['items'][0]['audio_url'].endswith('/api/editor/sfx/demo-whoosh/audio'))
        counts={c['key']:c['count'] for c in data['categories']}
        self.assertEqual(counts,{'transition':1,'impact':1,'ambient':0})
        self.assertEqual([c['label'] for c in data['categories']],['转场','打击','环境'])
        self.assertEqual([i['id'] for i in self.member.get('/api/editor/sfx',params={'q':'撞击'}).json()['items']],['demo-hit'])
        self.assertEqual([i['id'] for i in self.member.get('/api/editor/sfx',params={'q':'demo hit'}).json()['items']],['demo-hit'])
        self.assertEqual([i['id'] for i in self.member.get('/api/editor/sfx',params={'category':'impact'}).json()['items']],['demo-hit'])
        self.assertEqual(self.member.get('/api/editor/sfx',params={'category':'ambient'}).json()['items'],[])
        self.assertEqual(self.member.get('/api/editor/sfx',params={'q':'不存在'}).json()['items'],[])

    def test_audio_stream_supports_range(self):
        self.seed()
        full=self.member.get('/api/editor/sfx/demo-whoosh/audio')
        self.assertEqual(full.status_code,200,full.text)
        self.assertEqual(full.headers['content-type'],'audio/mpeg')
        self.assertGreater(len(full.content),2000)
        part=self.member.get('/api/editor/sfx/demo-whoosh/audio',headers={'Range':'bytes=0-99'})
        self.assertEqual(part.status_code,206)
        self.assertEqual(len(part.content),100)
        self.assertEqual(part.content,full.content[:100])
        self.assertEqual(self.member.get('/api/editor/sfx/../secret/audio').status_code,404)

    def test_favorite_toggle_orders_list(self):
        self.seed()
        self.assertFalse(self.member.get('/api/editor/sfx').json()['items'][0]['favorite'])
        response=self.member.post('/api/editor/sfx/demo-hit/favorite',json={'on':True},headers=fixtures.H)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['favorite'])
        items=self.member.get('/api/editor/sfx').json()['items']
        self.assertEqual(items[0]['id'],'demo-hit')
        self.assertTrue(items[0]['favorite'])
        # Favorites are per user.
        self.assertFalse(self.admin.get('/api/editor/sfx').json()['items'][0]['favorite'])
        self.assertEqual(self.member.post('/api/editor/sfx/demo-hit/favorite',json={'on':False},headers=fixtures.H).json()['favorite'],False)
        self.assertEqual([i['id'] for i in self.member.get('/api/editor/sfx').json()['items']],['demo-whoosh','demo-hit'])

    def test_adopt_copies_once_and_is_owner_scoped(self):
        root=self.seed()
        first=self.member.post('/api/editor/sfx/demo-whoosh/adopt',headers=fixtures.H)
        self.assertEqual(first.status_code,200,first.text)
        asset=first.json()
        self.assertFalse(asset['reused'])
        self.assertEqual(asset['name'],'测试掠过.mp3')
        self.assertEqual(asset['mime'],'audio/mpeg')
        self.assertAlmostEqual(asset['duration'],0.6,places=2)
        self.assertTrue((Path(self.hub.assets)/asset['id']).is_file())
        stream=self.member.get('/api/assets/'+asset['id'])
        self.assertEqual(stream.status_code,200)
        self.assertEqual(stream.headers['content-type'],'audio/mpeg')
        self.assertEqual(len(stream.content),(Path(root/'demo.mp3')).stat().st_size)
        # Re-adopting reuses the copy instead of duplicating it.
        again=self.member.post('/api/editor/sfx/demo-whoosh/adopt',headers=fixtures.H).json()
        self.assertTrue(again['reused'])
        self.assertEqual(again['id'],asset['id'])
        self.assertEqual(len(list(Path(self.hub.assets).iterdir())),1)
        # Another owner gets their own copy and cannot read someone else's asset.
        other=self.admin.post('/api/editor/sfx/demo-whoosh/adopt',headers=fixtures.H).json()
        self.assertNotEqual(other['id'],asset['id'])
        self.assertEqual(len(list(Path(self.hub.assets).iterdir())),2)
        self.assertEqual(self.admin.get('/api/assets/'+asset['id']).status_code,404)
        # Use counters are per owner.
        rows={i['id']:i for i in self.member.get('/api/editor/sfx').json()['items']}
        self.assertEqual(rows['demo-whoosh']['uses'],2)

    def test_missing_and_unknown_items(self):
        self.seed()
        self.assertEqual(self.member.post('/api/editor/sfx/nope/adopt',headers=fixtures.H).status_code,404)
        self.assertEqual(self.member.post('/api/editor/sfx/demo-whoosh/favorite',headers=fixtures.H).status_code,200)
        (Path(self.hub.directory)/'sfx'/'demo.mp3').unlink()
        self.assertEqual(self.member.get('/api/editor/sfx/demo-whoosh/audio').status_code,404)
        self.assertEqual(self.member.post('/api/editor/sfx/demo-whoosh/adopt',headers=fixtures.H).status_code,404)


if __name__=='__main__':
    unittest.main()
