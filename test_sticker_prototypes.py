import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'static' / 'stickers'
STYLES = ('solid', 'outline', 'curved', 'double', 'dashed', 'chevron')


class StickerAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg, cls.ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')

    def setUp(self):
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest('ffmpeg/ffprobe not installed')

    def test_each_style_is_a_12_frame_transparent_loop(self):
        for style in STYLES:
            path = ROOT / f'arrow-{style}.gif'
            with self.subTest(style=style):
                self.assertTrue(path.is_file(), path)
                info = subprocess.run(
                    [self.ffprobe, '-v', 'error', '-ignore_loop', '1', '-count_frames',
                     '-select_streams', 'v:0', '-show_entries', 'stream=width,height,nb_read_frames',
                     '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
                self.assertEqual(info.returncode, 0, info.stderr)
                stream = json.loads(info.stdout)['streams'][0]
                self.assertEqual((stream['width'], stream['height'], int(stream['nb_read_frames'])), (96, 96, 12))

    def test_frames_differ_and_keep_transparency(self):
        for style in STYLES:
            path = ROOT / f'arrow-{style}.gif'
            with self.subTest(style=style):
                raw = subprocess.run(
                    [self.ffmpeg, '-v', 'error', '-ignore_loop', '1', '-i', str(path),
                     '-frames:v', '7', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'],
                    capture_output=True, timeout=60).stdout
                frame = 96 * 96 * 4
                self.assertEqual(len(raw), frame * 7)
                first, sixth = raw[:frame], raw[6 * frame:7 * frame]
                self.assertNotEqual(first, sixth, 'animation must move between frame 0 and 6')
                alphas = set(first[3::4])
                self.assertIn(0, alphas, 'background must be transparent')
                self.assertIn(255, alphas, 'arrow must be opaque')


if __name__ == '__main__':
    unittest.main()
