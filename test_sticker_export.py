import shutil
import unittest
from pathlib import Path
import test_hub as fixtures
from editor import probe, run
from sticker_model import sticker_path


class StickerExportTests(unittest.TestCase):
    setUp = fixtures.HubTests.setUp
    tearDown = fixtures.HubTests.tearDown
    login = fixtures.HubTests.login
    account = fixtures.HubTests.account
    enqueue = fixtures.HubTests.enqueue

    def sample(self):
        account = self.account(self.admin)
        task = self.enqueue(self.member, account).json()['id']
        with self.hub.db() as db:
            db.execute("UPDATE tasks SET state='ready' WHERE id=?", (task,))
        run([shutil.which('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
             '-i', 'color=c=0x101010:s=160x240:r=24:d=4', '-c:v', 'libx264', '-threads', '1',
             '-pix_fmt', 'yuv420p', str(self.hub.media / (task + '.mp4'))])
        return task

    def export(self, project, key):
        response = self.member.post('/api/editor/projects/' + project['id'] + '/export',
                                   json={'version': project['version'], 'request_key': key}, headers=fixtures.H)
        self.assertEqual(response.status_code, 200, response.text)
        eid = response.json()['id']
        self.app.state.editor.tick()
        job = next(j for j in self.member.get('/api/editor/exports').json() if j['id'] == eid)
        self.assertEqual(job['state'], 'ready', job)
        return self.app.state.editor.root / (eid + '.mp4')

    def frame_region(self, path, at, box):
        """Mean channel value inside a pixel box at one timestamp."""
        x, y, w, h = box
        raw = run([shutil.which('ffmpeg'), '-v', 'error', '-ss', str(at), '-i', str(path),
                   '-frames:v', '1', '-vf', f'crop={w}:{h}:{x}:{y}', '-pix_fmt', 'rgb24',
                   '-f', 'rawvideo', '-'])
        pixels = [raw[i:i + 3] for i in range(0, len(raw), 3)]
        return sum(sum(p) / 3 for p in pixels) / max(1, len(pixels))

    def test_sticker_is_saved_normalised_and_composited(self):
        task = self.sample()
        body = {'ratio': '1:1', 'clips': [{'task_id': task, 'start': 0, 'end': 2, 'volume': 0}],
                'captions': [],
                'stickers': [{'id': 'sticker-a', 'style': 'solid', 'start': .5, 'end': 1.5,
                              'x': .5, 'y': .5, 'width': .8, 'track': 'sticker-main'}]}
        saved = self.member.post('/api/editor/projects', json={'title': '贴纸测试', 'body': body},
                                 headers=fixtures.H)
        self.assertEqual(saved.status_code, 200, saved.text)
        saved = saved.json()
        sticker = saved['body']['stickers'][0]
        self.assertEqual((sticker['style'], sticker['start'], sticker['end']), ('solid', .5, 1.5))
        self.assertIn('sticker-main', [t['id'] for t in saved['body']['tracks']])

        output = self.export(saved, 'sticker-composite-1')
        # Centre box: bright arrow while the sticker is on, dark source footage outside it.
        inside = self.frame_region(output, 1.0, (400, 400, 200, 200))
        before = self.frame_region(output, 0.2, (400, 400, 200, 200))
        after = self.frame_region(output, 1.8, (400, 400, 200, 200))
        self.assertGreater(inside, before + 40, f'sticker missing inside window: {inside} vs {before}')
        self.assertLess(after, inside / 2, f'sticker leaked outside window: {after} vs {inside}')

    def test_sticker_assets_and_validation_errors(self):
        task = self.sample()
        base = {'ratio': '1:1', 'clips': [{'task_id': task, 'start': 0, 'end': 1}], 'captions': []}
        for bad in ({'style': '../../etc/passwd', 'start': 0, 'end': 1},
                    {'style': 'solid', 'start': 0, 'end': 0},
                    {'style': 'solid', 'start': 0, 'end': 1, 'x': 5}):
            with self.subTest(bad=bad):
                response = self.member.post('/api/editor/projects',
                                            json={'title': '坏贴纸', 'body': dict(base, stickers=[bad])},
                                            headers=fixtures.H)
                self.assertEqual(response.status_code, 400, response.text)

    def test_exported_sticker_keeps_animation(self):
        task = self.sample()
        body = {'ratio': '1:1', 'clips': [{'task_id': task, 'start': 0, 'end': 2, 'volume': 0}],
                'captions': [],
                'stickers': [{'id': 's', 'style': 'chevron', 'start': 0, 'end': 2,
                              'x': .5, 'y': .5, 'width': .8}]}
        saved = self.member.post('/api/editor/projects', json={'title': '动画贴纸', 'body': body},
                                 headers=fixtures.H).json()
        output = self.export(saved, 'sticker-animation-1')
        frames = [self.frame_region(output, at, (300, 300, 480, 480)) for at in (0.05, 0.3, 0.55)]
        self.assertGreater(max(frames) - min(frames), 2.0, f'animated sticker looks static: {frames}')

    def test_all_styles_have_assets(self):
        for style in ('solid', 'outline', 'curved', 'double', 'dashed', 'chevron'):
            with self.subTest(style=style):
                self.assertTrue(Path(sticker_path(style)).is_file())


if __name__ == '__main__':
    unittest.main()
