"""fishaudio.py 的单元测试：SSE 边界、快照覆盖、时间戳、字幕分行。

不联网、不调用付费接口，全部用构造的事件流。
运行：python -B -m unittest test_fishaudio -v
"""
import base64
import json
import unittest

import fishaudio as fa


def ev_payload(audio=b'\x00\x01', seq=0, offset=0.0, segments=None,
               content='Hello', alignment='auto'):
    """构造一个事件 payload 字典。"""
    d = {'audio_base64': base64.b64encode(audio).decode() if audio else '',
         'chunk_seq': seq, 'chunk_audio_offset_sec': offset, 'content': content}
    if alignment == 'auto':
        d['alignment'] = None if segments is None else {
            'audio_duration': (segments[-1]['end'] if segments else 0),
            'segments': segments or []}
    else:
        d['alignment'] = alignment
    return d


def ev(**kw):
    """构造一条完整的 SSE data 行（带 'data: ' 前缀）。"""
    return 'data: ' + json.dumps(ev_payload(**kw))


class TestSSEFraming(unittest.TestCase):
    def test_single_event(self):
        out = list(fa.iter_sse_events([ev() + '\n\n']))
        self.assertEqual(len(out), 1)
        self.assertIn('"chunk_seq"', out[0])

    def test_crlf(self):
        out = list(fa.iter_sse_events([ev() + '\r\n\r\n']))
        self.assertEqual(len(out), 1)

    def test_split_across_network_chunks(self):
        """网络块不等于完整事件：逐字节喂入也必须还原。"""
        raw = (ev() + '\n\n' + ev() + '\n\n').encode()
        out = list(fa.iter_sse_events([raw[i:i + 1] for i in range(len(raw))]))
        self.assertEqual(len(out), 2)

    def test_split_mid_json(self):
        raw = (ev() + '\n\n').encode()
        cut = len(raw) // 2
        out = list(fa.iter_sse_events([raw[:cut], raw[cut:]]))
        self.assertEqual(len(out), 1)

    def test_comment_and_field_lines_ignored(self):
        block = ': keep-alive comment\n' + 'event: message\n\n'
        out = list(fa.iter_sse_events([block]))
        self.assertEqual(out, [])

    def test_multiple_data_lines_joined(self):
        block = 'data: {"a":\ndata: 1}\n\n'
        out = list(fa.iter_sse_events([block]))
        self.assertEqual(out, ['{"a":\n1}'])

    def test_truncated_tail_raises(self):
        with self.assertRaises(fa.StreamError):
            list(fa.iter_sse_events([ev()]))


class TestCollector(unittest.TestCase):
    def test_audio_concatenated_in_order(self):
        c = fa.StreamCollector()
        c.feed_event(ev_payload(b'\xaa'))
        c.feed_event(ev_payload(b'\xbb'))
        self.assertEqual(bytes(c.audio), b'\xaa\xbb')
        self.assertEqual(c.chunks, 2)

    def test_audio_appended_even_when_alignment_null(self):
        c = fa.StreamCollector()
        c.feed_event(ev_payload(b'\x01', segments=None))
        c.feed_event(ev_payload(b'\x02', segments=None))
        self.assertEqual(bytes(c.audio), b'\x01\x02')
        self.assertFalse(c.has_alignment())

    def test_snapshot_latest_wins(self):
        """同一 chunk_seq 的新快照必须覆盖旧快照，不能追加。"""
        c = fa.StreamCollector()
        c.feed_event(ev_payload(segments=[{'text': 'A', 'start': 0, 'end': .4}]))
        c.feed_event(ev_payload(segments=[{'text': 'A', 'start': 0, 'end': .4},
                                             {'text': 'B', 'start': .4, 'end': .8}]))
        tl = c.timeline()
        self.assertEqual([x['text'] for x in tl], ['A', 'B'])

    def test_multi_chunk_offsets(self):
        c = fa.StreamCollector()
        c.feed_event(ev_payload(seq=0, offset=0.0,
                                   segments=[{'text': 'one', 'start': 0, 'end': .5}]))
        c.feed_event(ev_payload(seq=1, offset=16.24,
                                   segments=[{'text': 'two', 'start': 0, 'end': .5}]))
        tl = c.timeline()
        self.assertAlmostEqual(tl[0]['start'], 0.0)
        self.assertAlmostEqual(tl[1]['start'], 16.24)

    def test_invalid_base64_raises(self):
        c = fa.StreamCollector()
        bad = 'data: {"audio_base64":"!!!notb64","chunk_seq":0,"alignment":null}\n\n'
        with self.assertRaises(fa.StreamError):
            for d in fa.iter_sse_events([bad]):
                c.feed_event(d)

    def test_upstream_error_surfaces(self):
        c = fa.StreamCollector()
        with self.assertRaises(fa.StreamError):
            c.feed_event(json.dumps({'error': 'quota exceeded'}))

    def test_bad_segment_dropped_with_warning(self):
        c = fa.StreamCollector()
        c.feed_event(ev_payload(segments=[{'text': 'X', 'start': 1, 'end': 0.5}]))
        self.assertEqual(c.timeline(), [])
        self.assertTrue(c.warnings)

    def test_missing_chunk_seq_ignored(self):
        c = fa.StreamCollector()
        payload = {'audio_base64': '', 'chunk_seq': None,
                   'alignment': {'segments': [{'text': 'A', 'start': 0, 'end': .3}]}}
        c.feed_event(json.dumps(payload))
        self.assertEqual(c.timeline(), [])
        self.assertTrue(c.warnings)


class TestCaptions(unittest.TestCase):
    def _tl(self, pairs):
        return [{'text': t, 'start': s, 'end': e, 'chunk_seq': 0} for t, s, e in pairs]

    def test_sentence_break(self):
        tl = self._tl([('你好。', 0, .5), ('再见。', .5, 1.0)])
        rows = fa.group_into_captions(tl)
        self.assertEqual([r['text'] for r in rows], ['你好。', '再见。'])

    def test_long_line_split_by_chars(self):
        """单段超过 max_chars 时断行。
        每段 20 字、上限 28 字：第一段 20 字未满不换行，
        第二段加入后累计 40 字触发断行 → 2 行，且每行不超 28 字。"""
        tl = self._tl([('字' * 20, 0, 1.0), ('字' * 20, 1.0, 2.0)])
        rows = fa.group_into_captions(tl, max_chars=28)
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertLessEqual(len(r['text']), 28)

    def test_short_words_merge_not_split(self):
        """短词应合并成可读行，不能每个词一行。"""
        tl = self._tl([('今天', 0, .4), ('天气', .4, .8), ('很好', .8, 1.2)])
        rows = fa.group_into_captions(tl)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['text'], '今天天气很好')

    def test_gap_forces_break(self):
        tl = self._tl([('A', 0, .3), ('B', 2.0, 2.3)])
        rows = fa.group_into_captions(tl, max_gap=0.9)
        self.assertEqual(len(rows), 2)

    def test_not_one_giant_caption(self):
        """整段口播不能挤成一条字幕。"""
        tl = self._tl([('字', i * .2, i * .2 + .2) for i in range(100)])
        rows = fa.group_into_captions(tl, max_chars=28, max_duration=6.0)
        self.assertGreater(len(rows), 3)
        for r in rows:
            self.assertLessEqual(r['end'] - r['start'], 6.01)

    def test_empty(self):
        self.assertEqual(fa.group_into_captions([]), [])


class TestRequest(unittest.TestCase):
    def test_model_explicit_and_no_key_in_body(self):
        h, b = fa.build_request('hi', 'ref-1', 's2.1-pro')
        self.assertEqual(h['model'], 's2.1-pro')
        self.assertNotIn('Authorization', h)   # 密钥不进 headers 字典
        self.assertEqual(b['reference_id'], 'ref-1')
        self.assertNotIn('api_key', json.dumps(b).lower())

    def test_text_limits(self):
        with self.assertRaises(ValueError):
            fa.build_request('', 'r', 's2.1-pro')
        text='长文案。'*2000
        self.assertEqual(fa.build_request(text,'r','s2.1-pro')[1]['text'],text)
        parts=fa.split_text(text)
        self.assertEqual(''.join(parts),text)
        self.assertTrue(all(len(p)<=fa.TEXT_CHUNK for p in parts))

    def test_speed_bounds(self):
        with self.assertRaises(ValueError):
            fa.build_request('hi', 'r', 's2.1-pro', speed=9)
        h, b = fa.build_request('hi', 'r', 's2.1-pro', speed=1.5)
        self.assertEqual(b['prosody']['speed'], 1.5)

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):
            fa.build_request('hi', 'r', 'gpt-9')

    def test_language_is_not_accent_param(self):
        """文档：language 只影响数字/日期朗读与词级对齐，不改口音。"""
        h, b = fa.build_request('hi', 'r', 's2.1-pro', language='zh-CN')
        self.assertEqual(b['language'], 'zh-CN')
        self.assertIn('normalize', b)


if __name__ == '__main__':
    unittest.main(verbosity=2)
