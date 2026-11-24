import copy
import math
import unittest
from sticker_model import (ARROW_STYLES, MAX_STICKERS, STYLE_FILES,
                           sticker_path, validate_stickers)


class StickerValidationTests(unittest.TestCase):
    def setUp(self):
        self.item = {'id': 'sticker-1', 'style': 'solid', 'start': 0, 'end': 2, 'track': 'sticker-main'}

    def test_every_style_has_a_bundled_asset(self):
        self.assertEqual(len(ARROW_STYLES), 6)
        for style in ARROW_STYLES:
            with self.subTest(style=style):
                self.assertTrue(sticker_path(style).is_file())
        self.assertEqual(len(STYLE_FILES),56)
        for style in STYLE_FILES:
            self.assertTrue(sticker_path(style).is_file())
            validate_stickers([dict(self.item,style=style)])

    def test_style_keys_are_not_paths(self):
        for bad in ('../static/stickers/arrow-solid.gif', 'arrow-solid', 'C:/x.gif', ''):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sticker_path(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_stickers([dict(self.item, style=bad)])

    def test_normalises_without_mutating_input(self):
        item = dict(self.item, style='chevron')
        original = copy.deepcopy(item)
        result = validate_stickers([item])[0]
        self.assertEqual(item, original)
        self.assertEqual(result, {'id': 'sticker-1', 'style': 'chevron', 'start': 0.0, 'end': 2.0,
                                  'x': .5, 'y': .5, 'width': .25, 'rotation': 0.0,
                                  'track': 'sticker-main', 'locked': False})

    def test_aligns_to_frames(self):
        result = validate_stickers([dict(self.item, start=.06, end=1.02)])[0]
        self.assertAlmostEqual(result['start'], 1 / 24)
        self.assertAlmostEqual(result['end'], 1.0)

    def test_rejects_invalid_data(self):
        invalid = [dict(self.item, x=math.nan), dict(self.item, x=True),
                   dict(self.item, width=0), dict(self.item, width=1.5),
                   dict(self.item, track='../bad'), dict(self.item, id='a b'),
                   dict(self.item, locked=1), dict(self.item, end=.001),
                   dict(self.item, rotation=720), dict(self.item, future_option=1),
                   {'style': 'solid', 'start': 0, 'end': 1, 'x': 'middle'}]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_stickers([item])
        with self.assertRaises(ValueError):
            validate_stickers({'style': 'solid'})
        with self.assertRaises(ValueError):
            validate_stickers([self.item] * (MAX_STICKERS + 1))

    def test_allows_full_frame_bounds(self):
        result = validate_stickers([dict(self.item, x=0, y=1, width=1, rotation=-360)])[0]
        self.assertEqual((result['x'], result['y'], result['width'], result['rotation']), (0.0, 1.0, 1.0, -360.0))

    def test_empty_list_is_valid(self):
        self.assertEqual(validate_stickers([]), [])


if __name__ == '__main__':
    unittest.main()
