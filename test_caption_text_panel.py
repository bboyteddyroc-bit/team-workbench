import json
import shutil
import tempfile
import unittest
from pathlib import Path

from editor import run, write_ass
from test_editor import EditorTests
from test_hub import H

STYLE_FIELDS = ('size', 'color', 'outline', 'outline_color', 'align', 'bold', 'italic', 'spacing', 'case')


def ass_text(captions, width=720, height=1280):
    temp = tempfile.TemporaryDirectory()
    try:
        path = Path(temp.name) / 'captions.ass'
        write_ass(path, captions, width, height)
        return path.read_text(encoding='utf-8-sig')
    finally:
        temp.cleanup()


def style_of(text, name):
    line = next(row for row in text.splitlines() if row.startswith(f'Style: {name},'))
    return line[len('Style: '):].split(',')


class AssTextStyleTests(unittest.TestCase):
    def test_one_percent_is_accepted_and_exported_without_eight_pixel_floor(self):
        fields = style_of(ass_text([{'text': 'a', 'start': 0, 'end': 1, 'size': 1}]), 'C0')
        self.assertEqual(float(fields[2]), 0.32)
        from editor import caption_style
        self.assertEqual(caption_style({'size': 1})['size'], 1)
        with self.assertRaises(ValueError):
            caption_style({'size': 0})

    def test_defaults_keep_the_previous_bottom_white_caption(self):
        fields = style_of(ass_text([{'text': 'a', 'start': 0, 'end': 1}]), 'C0')
        self.assertEqual(fields[0], 'C0')
        self.assertEqual(fields[1], 'Microsoft YaHei')
        self.assertEqual(fields[2], '32')
        self.assertEqual(fields[3], '&H00FFFFFF')
        self.assertEqual(fields[4], '&H00FFFFFF')
        self.assertEqual(fields[5], '&H00101010')
        self.assertEqual(fields[7], '0')
        self.assertEqual(fields[8], '0')
        self.assertEqual(fields[13], '0.0')
        self.assertEqual(fields[16], '2.0')
        self.assertEqual(fields[17], '0')
        self.assertEqual(fields[18], '2')
        self.assertEqual(fields[19], '30')
        self.assertEqual(fields[20], '30')
        self.assertEqual(fields[21], '90')

    def test_every_text_panel_field_reaches_the_ass_style(self):
        captions = [{'text': 'hello', 'start': 0, 'end': 1, 'font': 'zcool-kuaile', 'size': 200,
                     'color': '#ffcc00', 'outline': 4, 'outline_color': '#102030', 'align': 'left',
                     'bold': True, 'italic': True, 'spacing': 3, 'case': 'upper'}]
        text = ass_text(captions)
        fields = style_of(text, 'C0')
        self.assertEqual(fields[1], 'ZCOOL KuaiLe')
        self.assertEqual(fields[2], '65')
        self.assertEqual(fields[3], '&H0000CCFF')
        self.assertEqual(fields[5], '&H00302010')
        self.assertEqual(fields[7], '-1')
        self.assertEqual(fields[8], '-1')
        self.assertEqual(fields[13], '3.0')
        self.assertEqual(fields[16], '4.0')
        self.assertEqual(fields[18], '1')
        self.assertIn(',C0,,0,0,0,,HELLO', text)

    def test_each_caption_keeps_its_own_style_and_case(self):
        text = ass_text([{'text': 'Big', 'start': 0, 'end': 1, 'color': '#ff0000', 'size': 80, 'case': 'lower'},
                         {'text': 'small', 'start': 1, 'end': 2}])
        first = style_of(text, 'C0')
        second = style_of(text, 'C1')
        self.assertEqual(first[3], '&H000000FF')
        self.assertEqual(first[2], '26')
        self.assertEqual(second[3], '&H00FFFFFF')
        self.assertEqual(second[2], '32')
        self.assertIn(',C0,,0,0,0,,big', text)
        self.assertIn(',C1,,0,0,0,,small', text)


class FreePositionAssTests(unittest.TestCase):
    def test_position_becomes_an_ass_pos_scaled_to_the_frame(self):
        text = ass_text([{'text': 'a', 'start': 0, 'end': 1, 'x': 25, 'y': 40, 'align': 'center'},
                         {'text': 'b', 'start': 0, 'end': 1, 'x': 10, 'y': 90, 'align': 'left'},
                         {'text': 'c', 'start': 0, 'end': 1, 'x': 100, 'y': 0, 'align': 'right'},
                         {'text': 'd', 'start': 0, 'end': 1}], 720, 1280)
        self.assertIn(',C0,,0,0,0,,{\\an5\\pos(180,512)}a', text)
        self.assertIn(',C1,,0,0,0,,{\\an4\\pos(72,1152)}b', text)
        self.assertIn(',C2,,0,0,0,,{\\an6\\pos(720,0)}c', text)
        self.assertIn(',C3,,0,0,0,,d', text)


class CaptionTextPanelApiTests(EditorTests):
    def test_position_and_lane_roundtrip_and_invalid_positions_are_rejected(self):
        task = self.sample()
        data = self.project(task)
        data['body']['captions'] = [
            {'text': 'a', 'start': 0, 'end': 1, 'track': 'caption-main', 'x': 50, 'y': 20.126},
            {'text': 'b', 'start': 1, 'end': 2, 'track': 'caption-b', 'x': 10, 'y': 80},
            {'text': 'c', 'start': 2, 'end': 3, 'track': 'caption-b'}]
        response = self.member.post('/api/editor/projects', json=data, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        captions = response.json()['body']['captions']
        self.assertEqual([c['track'] for c in captions], ['caption-main', 'caption-b', 'caption-b'])
        self.assertEqual((captions[0]['x'], captions[0]['y']), (50.0, 20.13))
        self.assertEqual((captions[1]['x'], captions[1]['y']), (10.0, 80.0))
        self.assertNotIn('x', captions[2])
        self.assertNotIn('y', captions[2])
        for patch in ({'x': 50}, {'y': 50}, {'x': -1, 'y': 5}, {'x': 5, 'y': 101}, {'x': True, 'y': 5},
                      {'x': 'left', 'y': 5}, {'x': float('nan'), 'y': 5}):
            broken = json.loads(json.dumps(data))
            broken['body']['captions'][2] = {'text': 'c', 'start': 2, 'end': 3, **patch}
            try:
                rejected = self.member.post('/api/editor/projects', content=json.dumps(broken, allow_nan=True),
                                            headers={**H, 'content-type': 'application/json'})
            except Exception:
                continue
            self.assertEqual(rejected.status_code, 400, patch)

    def test_positioned_caption_is_burned_in_at_its_spot(self):
        task = self.sample()
        run([shutil.which('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=160x240:r=24:d=2',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(self.hub.media / (task + '.mp4'))])
        data = {'title': '自由位置导出', 'body': {'ratio': '16:9', 'clips': [{'task_id': task, 'start': 0, 'end': 2, 'volume': 0}],
                'captions': [{'text': '字幕', 'start': 0, 'end': 2, 'size': 240, 'color': '#ff0000', 'outline': 0,
                              'outline_color': '#ff0000', 'align': 'center', 'x': 75, 'y': 20}]}}
        saved = self.member.post('/api/editor/projects', json=data, headers=H).json()
        response = self.member.post('/api/editor/projects/' + saved['id'] + '/export',
                                    json={'version': saved['version'], 'request_key': 'free-position-caption'}, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        export_id = response.json()['id']
        self.app.state.editor.tick()
        job = next(item for item in self.member.get('/api/editor/exports').json() if item['id'] == export_id)
        self.assertEqual(job['state'], 'ready', job)
        raw = run([shutil.which('ffmpeg'), '-v', 'error', '-ss', '0.5', '-i',
                   str(self.app.state.editor.root / (export_id + '.mp4')), '-frames:v', '1',
                   '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
        width, height = 1920, 1080
        self.assertEqual(len(raw), width * height * 3)
        xs, ys = [], []
        for index in range(0, len(raw), 3):
            r, g, b = raw[index:index + 3]
            if r > 200 and g < 40 and b < 40:
                pixel = index // 3
                xs.append(pixel % width)
                ys.append(pixel // width)
        self.assertGreater(len(xs), 200, '导出成片里没有红色字幕像素')
        self.assertAlmostEqual(sum(xs) / len(xs) / width, 0.75, delta=0.05)
        self.assertAlmostEqual(sum(ys) / len(ys) / height, 0.20, delta=0.05)


    def test_style_fields_roundtrip_and_invalid_values_are_rejected(self):
        task = self.sample()
        data = self.project(task)
        data['body']['captions'][0].update(size=150, color='#00ff88', outline=3.5, outline_color='#ff0000',
                                          align='right', bold=True, italic=True, spacing=2.5, case='upper')
        response = self.member.post('/api/editor/projects', json=data, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        caption = response.json()['body']['captions'][0]
        self.assertEqual([caption[field] for field in STYLE_FIELDS],
                         [150.0, '#00ff88', 3.5, '#ff0000', 'right', True, True, 2.5, 'upper'])
        for patch in ({'size': 500}, {'size': 'big'}, {'color': 'red'}, {'outline': -1}, {'outline': 13},
                      {'align': 'middle'}, {'case': 'title'}, {'spacing': 99}):
            broken = json.loads(json.dumps(data))
            broken['body']['captions'][0].update(patch)
            rejected = self.member.post('/api/editor/projects', json=broken, headers=H)
            self.assertEqual(rejected.status_code, 400, patch)
        plain = json.loads(json.dumps(data))
        plain['body']['captions'][0] = {'text': '无样式字幕', 'start': 0, 'end': 1}
        response = self.member.post('/api/editor/projects', json=plain, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([response.json()['body']['captions'][0][field] for field in STYLE_FIELDS],
                         [100.0, '#ffffff', 2.0, '#101010', 'center', False, False, 0.0, 'none'])

    def test_styled_caption_is_burned_in_with_its_own_colour(self):
        task = self.sample()
        run([shutil.which('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=160x240:r=24:d=2',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(self.hub.media / (task + '.mp4'))])
        data = {'title': '文本栏导出', 'body': {'ratio': '16:9', 'clips': [{'task_id': task, 'start': 0, 'end': 2, 'volume': 0}],
                'captions': [{'text': '字幕', 'start': 0, 'end': 2, 'size': 240, 'color': '#ff0000', 'outline': 0,
                              'outline_color': '#ff0000', 'align': 'center'}]}}
        saved = self.member.post('/api/editor/projects', json=data, headers=H).json()
        response = self.member.post('/api/editor/projects/' + saved['id'] + '/export',
                                    json={'version': saved['version'], 'request_key': 'text-panel-red-caption'}, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        export_id = response.json()['id']
        self.app.state.editor.tick()
        job = next(item for item in self.member.get('/api/editor/exports').json() if item['id'] == export_id)
        self.assertEqual(job['state'], 'ready', job)
        raw = run([shutil.which('ffmpeg'), '-v', 'error', '-ss', '0.5', '-i',
                   str(self.app.state.editor.root / (export_id + '.mp4')), '-frames:v', '1',
                   '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
        pixels = [tuple(raw[index:index + 3]) for index in range(0, len(raw), 3)]
        reds = sum(1 for r, g, b in pixels if r > 200 and g < 40 and b < 40)
        self.assertGreater(reds, 200, '导出成片里没有红色字幕像素')


if __name__ == '__main__':
    unittest.main()
