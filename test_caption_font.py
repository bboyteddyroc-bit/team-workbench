import json
import tempfile
import unittest
from pathlib import Path
from editor import FONT_DIR, subtitle_fonts, write_ass
from test_editor import EditorTests
from test_hub import H


class FontManifestTests(unittest.TestCase):
    def test_manifest_fonts_have_files_and_licenses(self):
        fonts = subtitle_fonts()
        self.assertGreaterEqual(len(fonts), 8)
        self.assertEqual(fonts['default']['label'], '默认 · 微软雅黑')
        for item in fonts.values():
            if item['id'] == 'default':
                continue
            self.assertTrue((FONT_DIR / item['file']).is_file(), item['file'])
            self.assertTrue(item.get('family') and item.get('license'), item['id'])
        licenses = {p.name for p in FONT_DIR.glob('LICENSE-*.txt')}
        self.assertGreaterEqual(len(licenses), len(fonts) - 1)

    def test_ass_bundles_only_used_fonts_with_distinct_styles(self):
        fonts = subtitle_fonts()
        captions = [
            {'text': 'a', 'start': 0, 'end': 1, 'font': 'zcool-kuaile'},
            {'text': 'b', 'start': 1, 'end': 2, 'font': 'long-cang'},
            {'text': 'c', 'start': 2, 'end': 3, 'font': 'zcool-kuaile'},
            {'text': 'd', 'start': 3, 'end': 4},
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'captions.ass'
            write_ass(path, captions, 720, 1280)
            text = path.read_text(encoding='utf-8-sig')
            self.assertIn('Style: C0,ZCOOL KuaiLe,', text)
            self.assertIn('Style: C1,Long Cang,', text)
            self.assertIn(',C0,,0,0,0,,a', text)
            self.assertIn(',C1,,0,0,0,,b', text)
            self.assertIn(',C2,,0,0,0,,c', text)
            self.assertIn(',C3,,0,0,0,,d', text)
            copied = {p.name for p in (path.parent / 'subtitle-fonts').iterdir()}
            self.assertEqual(copied, {fonts['zcool-kuaile']['file'], fonts['long-cang']['file']})

    def test_default_only_copies_no_font(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'captions.ass'
            write_ass(path, [{'text': 'x', 'start': 0, 'end': 1}], 720, 1280)
            self.assertEqual(list((path.parent / 'subtitle-fonts').iterdir()), [])


class CaptionFontTests(EditorTests):
    def test_every_manifest_font_roundtrips_and_unknown_is_rejected(self):
        task = self.sample()
        data = self.project(task)
        for font_id in subtitle_fonts():
            data['body']['captions'][0]['font'] = font_id
            response = self.member.post('/api/editor/projects', json=data, headers=H)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data['body']['captions'][0]['font'], font_id)
        data['body']['captions'][0]['font'] = 'unknown'
        self.assertEqual(self.member.post('/api/editor/projects', json=data, headers=H).status_code, 400)


if __name__ == '__main__':
    unittest.main()
