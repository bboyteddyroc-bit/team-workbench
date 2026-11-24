import io
import json
import unittest
from unittest import mock
import asr
import test_hub as fixtures
from test_editor import EditorTests


class CaptionRowTests(unittest.TestCase):
    def test_short_line_is_kept_whole(self):
        rows = asr.caption_rows([{'start': 0, 'end': 2, 'text': '今天聊聊清洁工具'}])
        self.assertEqual([row['text'] for row in rows], ['今天聊聊清洁工具'])
        self.assertEqual(rows[0]['start'], 0)
        self.assertEqual(rows[0]['end'], 2)

    def test_long_chinese_line_splits_on_punctuation_and_keeps_order(self):
        text = '这个拖把桶可以折叠，' * 4
        rows = asr.caption_rows([{'start': 1, 'end': 13, 'text': text}])
        self.assertGreater(len(rows), 1)
        self.assertTrue(all(len(row['text']) <= 18 for row in rows), [row['text'] for row in rows])
        self.assertEqual(''.join(row['text'] for row in rows), text)
        starts = [row['start'] for row in rows]
        self.assertEqual(starts, sorted(starts))
        for previous, current in zip(rows, rows[1:]):
            self.assertAlmostEqual(previous['end'], current['start'], places=2)
        self.assertAlmostEqual(rows[0]['start'], 1, places=2)
        self.assertAlmostEqual(rows[-1]['end'], 13, places=2)

    def test_english_lines_get_a_wider_limit(self):
        text = 'Hey there friends, this is a longer English sentence for testing.'
        rows = asr.caption_rows([{'start': 0, 'end': 4, 'text': text}])
        self.assertGreater(len(rows), 1)
        self.assertTrue(all(len(row['text']) <= 42 for row in rows))
        self.assertEqual(''.join(row['text'] for row in rows).replace(' ', '') != text.replace(' ', ''), False)

    def test_unpunctuated_text_is_hard_wrapped(self):
        rows = asr.caption_rows([{'start': 0, 'end': 5, 'text': '清洁' * 20}])
        self.assertTrue(all(len(row['text']) <= 18 for row in rows))
        self.assertEqual(''.join(row['text'] for row in rows), '清洁' * 20)


class TranslationTests(unittest.TestCase):
    def payload(self, texts):
        body = {'choices': [{'message': {'content': json.dumps(texts, ensure_ascii=False)}}]}
        stream = io.BytesIO(json.dumps(body).encode())

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Response(stream.getvalue())

    def test_returns_one_line_per_input_in_order(self):
        with mock.patch('urllib.request.urlopen', return_value=self.payload(['一', '二'])) as opened:
            result = asr.translate(['one', 'two'], 'zh', 'secret')
        self.assertEqual(result, ['一', '二'])
        request = opened.call_args[0][0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer secret')
        self.assertNotIn('Bearer secret', json.dumps(result))

    def test_batches_large_lists(self):
        texts = ['line %d' % i for i in range(30)]
        responses = [self.payload(['a%d' % i for i in range(12)]),
                     self.payload(['b%d' % i for i in range(12)]),
                     self.payload(['c%d' % i for i in range(6)])]
        with mock.patch('urllib.request.urlopen', side_effect=responses) as opened:
            result = asr.translate(texts, 'zh', 'secret')
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(len(result), 30)

    def test_line_count_mismatch_retries_once_then_fails(self):
        responses = [self.payload(['只有一行']), self.payload(['还是只有一行'])]
        with mock.patch('urllib.request.urlopen', side_effect=responses) as opened:
            with self.assertRaises(ValueError) as caught:
                asr.translate(['one', 'two'], 'zh', 'secret')
        self.assertEqual(opened.call_count, 2)
        self.assertIn('条数', str(caught.exception))

    def test_mismatch_is_repaired_by_the_retry(self):
        responses = [self.payload(['只有一行']), self.payload(['一', '二'])]
        with mock.patch('urllib.request.urlopen', side_effect=responses):
            self.assertEqual(asr.translate(['one', 'two'], 'zh', 'secret'), ['一', '二'])

    def test_missing_key_is_rejected(self):
        with self.assertRaises(ValueError):
            asr.translate(['one'], 'zh', '')

    def test_status_lists_languages_and_limit(self):
        info = asr.status()
        self.assertEqual(info['engine'], 'faster-whisper')
        self.assertIn('zh', [item['id'] for item in info['languages']])
        self.assertGreater(info['max_seconds'], 0)


class RecognizeApiTests(EditorTests):
    def test_caption_source_text_and_language_roundtrip(self):
        task = self.sample()
        data = self.project(task)
        data['body']['captions'][0].update(source_text='test subtitle', lang='en')
        response = self.member.post('/api/editor/projects', json=data, headers=fixtures.H)
        self.assertEqual(response.status_code, 200, response.text)
        caption = response.json()['body']['captions'][0]
        self.assertEqual(caption['source_text'], 'test subtitle')
        self.assertEqual(caption['lang'], 'en')
        data = response.json()
        data['body']['captions'][0]['lang'] = 'xx'
        self.assertEqual(self.member.post('/api/editor/projects', json=data, headers=fixtures.H).status_code, 400)

    def test_recognize_rejects_unknown_options_and_empty_timeline(self):
        task = self.sample()
        data = self.project(task)
        response = self.member.post('/api/editor/asr/recognize',
                                    json={'body': data['body'], 'language': 'klingon'}, headers=fixtures.H)
        self.assertEqual(response.status_code, 400)
        empty = {'clips': [], 'captions': []}
        response = self.member.post('/api/editor/asr/recognize', json={'body': empty}, headers=fixtures.H)
        self.assertEqual(response.status_code, 400)

    def test_recognize_returns_captions_from_engine(self):
        task = self.sample()
        data = self.project(task)

        def fake_audio(editor, body, owner, admin, target):
            target.write_bytes(b'RIFF')
            return target

        engine = mock.Mock(transcribe=mock.Mock(return_value=(
            iter([mock.Mock(start=0, end=1, text='自动识别字幕')]), mock.Mock(language='zh'))),
            detect_language=mock.Mock(return_value=('zh', 0.99, [])))
        with mock.patch.object(asr, 'timeline_audio', side_effect=fake_audio), \
                mock.patch.object(asr, 'engine', return_value=engine), \
                mock.patch('faster_whisper.audio.decode_audio', return_value=mock.Mock()):
            response = self.member.post('/api/editor/asr/recognize',
                                        json={'body': data['body'], 'language': 'auto'}, headers=fixtures.H)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['language'], 'zh')
        self.assertEqual([row['text'] for row in body['captions']], ['自动识别字幕'])
        self.assertEqual(body['captions'][0]['lang'], 'zh')
        self.assertEqual(body['target'], '')


if __name__ == '__main__':
    unittest.main()
