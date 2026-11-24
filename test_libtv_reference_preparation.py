import tempfile
import unittest
from pathlib import Path
from PIL import Image
from libtv_gateway import prepare_reference_image

class ReferencePreparationTests(unittest.TestCase):
    def test_large_image_is_resized_without_touching_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / 'original.jpg'
            Image.new('RGB', (5000, 4200), 'red').save(original)
            before = original.read_bytes()
            result = prepare_reference_image(original, root, 4)
            self.assertNotEqual(result, original)
            self.assertEqual(original.read_bytes(), before)
            with Image.open(result) as image:
                self.assertLessEqual(max(image.size), 4096)
            self.assertLessEqual(result.stat().st_size, 8 * 1024 * 1024)

    def test_small_image_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'small.png'
            Image.new('RGBA', (100, 100), (10, 20, 30, 100)).save(path)
            self.assertEqual(prepare_reference_image(path, Path(tmp), 1), path)

    def test_invalid_image_reports_no_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.png'
            path.write_bytes(b'not an image')
            with self.assertRaisesRegex(RuntimeError, '生成尚未提交'):
                prepare_reference_image(path, Path(tmp), 1)

if __name__ == '__main__': unittest.main()
