"""Subtitle font catalog regressions, including the bundled English fonts."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from fontTools import ttLib
import editor
import test_hub as fixtures

FONTS = Path(editor.__file__).parent / 'static' / 'fonts'
MANIFEST = json.loads((FONTS / 'fonts.json').read_text(encoding='utf-8'))
ENGLISH = [f for f in MANIFEST if f.get('latin')]
ASCII = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,!?-\'"')


class CatalogTests(unittest.TestCase):
    def test_every_entry_resolves_to_a_real_font_file(self):
        for item in MANIFEST:
            if item['id'] == 'default':
                self.assertIn('css', item)
                continue
            path = FONTS / item['file']
            self.assertTrue(path.exists(), item['file'])
            self.assertEqual(item['license'], 'SIL OFL 1.1', item['id'])
            self.assertEqual(ttLib.TTFont(path)['name'].getDebugName(1), item['family'], item['id'])

    def test_english_fonts_are_static_regular_with_full_latin(self):
        self.assertTrue(ENGLISH, 'English fonts missing from the catalog')
        for item in ENGLISH:
            font = ttLib.TTFont(FONTS / item['file'])
            self.assertNotIn('fvar', font, item['id'])          # a variable font can be picked at the wrong weight
            self.assertEqual(font['OS/2'].usWeightClass, 400, item['id'])
            covered = set(font.getBestCmap())
            self.assertEqual({ord(c) for c in ASCII} - covered, set(), item['id'])
            self.assertNotIn(0x5B57, covered, item['id'])        # no CJK: these are English-only faces

    def test_font_ids_are_unique_and_stable(self):
        ids = [f['id'] for f in MANIFEST]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('inter', ids)
        self.assertIn('anton', ids)

    def test_catalog_is_grouped_for_the_dropdown(self):
        groups = {}
        for item in MANIFEST:
            self.assertTrue(item.get('group'), item['id'])
            groups.setdefault(item['group'], []).append(item['id'])
        self.assertGreaterEqual(len(ENGLISH), 40, 'English library is too thin')
        for name in ('英文 · 无衬线', '英文 · 窄体标题', '英文 · 衬线', '英文 · 手写', '英文 · 展示', '英文 · 等宽'):
            self.assertTrue(groups.get(name), name)
        self.assertIn('default', groups['中文'])


class ExportTests(unittest.TestCase):
    setUp = fixtures.HubTests.setUp
    tearDown = fixtures.HubTests.tearDown
    login = fixtures.HubTests.login
    account = fixtures.HubTests.account
    enqueue = fixtures.HubTests.enqueue

    def task(self):
        account = self.account(self.admin)
        task = self.enqueue(self.member, account).json()['id']
        with self.hub.db() as db:
            db.execute("UPDATE tasks SET state='ready' WHERE id=?", (task,))
        editor.run([shutil.which('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                    '-i', 'testsrc2=s=160x240:r=24:d=2', '-c:v', 'libx264', '-threads', '1',
                    '-pix_fmt', 'yuv420p', str(self.hub.media / (task + '.mp4'))])
        return task

    def export(self, task, font, key):
        data = {'title': '英文字体', 'body': {'ratio': '9:16', 'clips': [{'task_id': task, 'start': 0, 'end': 1.5, 'volume': 0}],
                'captions': [{'text': 'Subtitle Test 123', 'start': 0, 'end': 1.2, 'font': font}]}}
        saved = self.member.post('/api/editor/projects', json=data, headers=fixtures.H)
        self.assertEqual(saved.status_code, 200, saved.text)
        saved = saved.json()
        eid = self.member.post('/api/editor/projects/' + saved['id'] + '/export',
                               json={'version': saved['version'], 'request_key': key}, headers=fixtures.H).json()['id']
        self.app.state.editor.tick()
        job = next(j for j in self.member.get('/api/editor/exports').json() if j['id'] == eid)
        self.assertEqual(job['state'], 'ready', job)
        return self.app.state.editor.root / (eid + '.mp4')

    def frame(self, path):
        raw = editor.run([shutil.which('ffmpeg'), '-v', 'error', '-ss', '0.6', '-i', str(path), '-frames:v', '1',
                          '-vf', 'scale=180:-1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
        self.assertGreater(len(raw), 1000, 'no frame decoded')
        return raw

    def test_english_fonts_are_accepted_and_render_differently(self):
        task = self.task()
        anton = self.frame(self.export(task, 'anton', 'font-anton-export-01'))
        caveat = self.frame(self.export(task, 'caveat', 'font-caveat-export1'))
        self.assertNotEqual(anton, caveat, 'two different fonts produced identical pixels: font not applied')
        band = anton[len(anton) * 2 // 3:]                    # lower third where the subtitle sits
        self.assertGreater(max(band) - min(band), 30, 'subtitle pixels missing from the export')


if __name__ == '__main__':
    unittest.main()
