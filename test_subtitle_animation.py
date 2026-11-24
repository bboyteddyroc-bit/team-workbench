import json
import tempfile
import unittest
from pathlib import Path

from editor import caption_anim, write_ass
from test_editor import EditorTests
from test_hub import H


def ass_lines(captions, width=720, height=1280):
    temp = tempfile.TemporaryDirectory()
    try:
        path = Path(temp.name) / 'captions.ass'
        write_ass(path, captions, width, height)
        text = path.read_text(encoding='utf-8-sig')
    finally:
        temp.cleanup()
    return [row for row in text.splitlines() if row.startswith('Dialogue:')]


def dialogue_body(line):
    return line.split(',,0,0,0,,', 1)[1]


def base(**extra):
    caption = {'text': '字幕动画', 'start': 0, 'end': 3, 'size': 110, 'outline': 2}
    caption.update(extra)
    return caption


class CaptionAnimValidationTests(unittest.TestCase):
    def test_missing_block_is_empty(self):
        self.assertEqual(caption_anim({}), {})
        self.assertEqual(caption_anim({'anim': None}), {})
        self.assertEqual(caption_anim({'anim': {}}), {})

    def test_known_animations_are_kept_with_duration(self):
        anim = caption_anim({'anim': {'in': {'id': 'fade', 'dur': .5}, 'out': {'id': 'sink', 'dur': .3}, 'loop': {'id': 'breathe', 'dur': .8}}})
        self.assertEqual(anim['in'], {'id': 'fade', 'dur': .5})
        self.assertEqual(anim['out'], {'id': 'sink', 'dur': .3})
        self.assertEqual(anim['loop'], {'id': 'breathe', 'dur': .8})

    def test_karaoke_needs_no_duration(self):
        self.assertEqual(caption_anim({'anim': {'loop': {'id': 'karaoke', 'dur': 9}}}), {'loop': {'id': 'karaoke'}})

    def test_duration_must_stay_inside_the_slider_range(self):
        with self.assertRaises(ValueError):
            caption_anim({'anim': {'in': {'id': 'fade', 'dur': 3}}})
        with self.assertRaises(ValueError):
            caption_anim({'anim': {'in': {'id': 'fade', 'dur': 0}}})
        self.assertEqual(caption_anim({'anim': {'in': {'id': 'fade', 'dur': 2}}})['in']['dur'], 2)

    def test_unknown_animation_is_rejected(self):
        with self.assertRaises(ValueError):
            caption_anim({'anim': {'in': {'id': 'explode'}}})
        with self.assertRaises(ValueError):
            caption_anim({'anim': {'out': {'id': 'zoom'}}})
        with self.assertRaises(ValueError):
            caption_anim({'anim': 'fade'})
        self.assertEqual(caption_anim({'anim': {'in': 'fade'}}), {'in': {'id': 'fade', 'dur': .4}})


class AssAnimationTests(unittest.TestCase):
    def test_plain_caption_has_no_animation_tags(self):
        body = dialogue_body(ass_lines([base()])[0])
        self.assertEqual(body, '字幕动画')

    def test_fade_in_and_out_merge_into_one_fad(self):
        body = dialogue_body(ass_lines([base(anim={'in': {'id': 'fade', 'dur': .5}, 'out': {'id': 'fade', 'dur': .4}})])[0])
        self.assertIn(r'\fad(500,400)', body)

    def test_rise_uses_move_anchored_at_the_bottom_centre(self):
        body = dialogue_body(ass_lines([base(anim={'in': {'id': 'rise', 'dur': .4}})])[0])
        self.assertIn(r'\an2\move(360,1344,360,1190,0,400)', body)

    def test_rise_then_sink_splits_into_two_events(self):
        lines = ass_lines([base(anim={'in': {'id': 'rise', 'dur': .4}, 'out': {'id': 'sink', 'dur': .4}})])
        self.assertEqual(len(lines), 2)
        self.assertIn('0:00:00.00,0:00:02.60', lines[0])
        self.assertIn('0:00:02.60,0:00:03.00', lines[1])
        self.assertIn(r'\move(360,1344,360,1190,0,400)', lines[0])
        self.assertIn(r'\move(360,1190,360,1344,0,400)', lines[1])

    def test_zoom_and_shrink_do_not_overlap_transform_windows(self):
        body = dialogue_body(ass_lines([base(anim={'in': {'id': 'zoom', 'dur': .3}, 'out': {'id': 'shrink', 'dur': .4}})])[0])
        self.assertIn(r'\t(0,300,\fscx100\fscy100)', body)
        self.assertIn(r'\t(2600,3000,\fscx72\fscy72)', body)

    def test_typewriter_reveals_one_character_per_syllable(self):
        body = dialogue_body(ass_lines([base(anim={'in': {'id': 'type', 'dur': 1.2}})])[0])
        self.assertTrue(body.startswith(r'{\2a&HFF&}'))
        self.assertEqual(body.count(r'\k300'), 4)
        visible = body[body.index('}') + 1:]
        self.assertEqual(visible.replace(r'{\k300}', ''), '字幕动画')

    def test_karaoke_sweeps_the_whole_caption(self):
        body = dialogue_body(ass_lines([base(anim={'loop': {'id': 'karaoke'}})])[0])
        self.assertIn(r'\1c&H00BDA923', body)
        self.assertEqual(body.count(r'\kf750'), 4)

    def test_breathe_and_shake_repeat_after_the_entrance(self):
        breathe = dialogue_body(ass_lines([base(anim={'in': {'id': 'fade', 'dur': .4}, 'loop': {'id': 'breathe', 'dur': .5}})])[0])
        self.assertIn(r'\t(400,650,', breathe)
        self.assertNotIn(r'\t(0,250,', breathe)
        shake = dialogue_body(ass_lines([base(anim={'loop': {'id': 'shake', 'dur': .4}})])[0])
        self.assertIn(r'\frz0', shake)
        self.assertLessEqual(shake.count(r'\t('), 28)

    def test_free_position_is_dropped_when_a_move_is_emitted(self):
        body = dialogue_body(ass_lines([base(x=50, y=15, anim={'in': {'id': 'rise', 'dur': .3}})])[0])
        self.assertIn(r'\an5\move(360,346,360,192,0,300)', body)
        self.assertNotIn(r'\pos(', body)

    def test_free_position_survives_non_positional_animation(self):
        body = dialogue_body(ass_lines([base(x=50, y=15, anim={'in': {'id': 'fade', 'dur': .3}})])[0])
        self.assertIn(r'\an5\pos(360,192)', body)

    def test_animation_without_style_keeps_default_position(self):
        body = dialogue_body(ass_lines([{'text': 'a', 'start': 0, 'end': 1, 'anim': {'in': {'id': 'fade', 'dur': .2}}}])[0])
        self.assertNotIn(r'\pos(', body)
        self.assertIn(r'\fad(200,0)', body)


class AnimPersistenceTests(EditorTests):
    def test_animation_survives_save_and_reload(self):
        task = self.sample()
        body = self.project(task)
        anim = {'in': {'id': 'pop', 'dur': .5}, 'loop': {'id': 'breathe', 'dur': .6}}
        body['body']['captions'][0]['anim'] = anim
        project = self.member.post('/api/editor/projects', json=body, headers=H)
        self.assertEqual(project.status_code, 200, project.text)
        saved = project.json()['body']['captions'][0]
        self.assertEqual(saved['anim'], anim)
        listed = self.member.get('/api/editor/projects', headers=H).json()[0]
        self.assertEqual(listed['body']['captions'][0]['anim'], anim)
        version = self.member.get(f"/api/editor/projects/{listed['id']}/versions", headers=H).json()[0]
        reopened = dict(body, id=listed['id'], version=listed['version'], body=listed['body'])
        restored = self.member.post(f"/api/editor/projects/{listed['id']}/restore", json={'version': version['version'], 'expected_version': listed['version']}, headers=H)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()['body']['captions'][0]['anim']['loop']['id'], 'breathe')
        self.assertEqual(reopened['body']['captions'][0]['anim'], anim)

    def test_invalid_animation_is_rejected_on_save(self):
        task = self.sample()
        body = self.project(task)
        body['body']['captions'][0]['anim'] = {'in': {'id': 'explode'}}
        bad = self.member.post('/api/editor/projects', json=body, headers=H)
        self.assertEqual(bad.status_code, 400)
        with self.assertRaises(ValueError):
            caption_anim(body['body']['captions'][0])


if __name__ == '__main__':
    unittest.main()
