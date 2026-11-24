import unittest
from unittest import mock
import asr

class BilingualTests(unittest.TestCase):
    def run_language(self, detected):
        segments=[{'start':0,'end':2,'text':'Hello.'}]
        def fake_translate(texts, target, key):
            return ['你好。' if target=='zh' else 'Hello.']
        with mock.patch('editor.timeline_duration',return_value=2), mock.patch.object(asr,'configured_key',return_value='test'), mock.patch.object(asr,'timeline_audio'), mock.patch.object(asr,'transcribe',return_value=(detected,segments)), mock.patch.object(asr,'translate',side_effect=fake_translate) as translate:
            from pathlib import Path
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as root:
                editor=mock.Mock(root=Path(root))
                result=asr.recognize(editor,object(),{},'user',False,'auto','zh-en')
        self.assertEqual(result['target'],'zh-en')
        self.assertEqual({c['lang'] for c in result['captions']},{'zh','en'})
        self.assertEqual([(c['start'],c['end']) for c in result['captions']],[(0,2),(0,2)])
        self.assertEqual(translate.call_count,1 if detected in ('en','zh') else 2)
    def test_english(self):self.run_language('en')
    def test_chinese(self):self.run_language('zh')
    def test_other_language(self):self.run_language('ja')

if __name__=='__main__':unittest.main()
