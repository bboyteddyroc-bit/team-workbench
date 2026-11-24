import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from ai_edit_native_video import inspect,POLICY
from a6_video import VideoOutcomeUnknown
from ai_editing import Unknown

class NativeVideoTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'x.mp4';self.path.write_bytes(b'\x00\x00\x00\x18ftypisomfake')
  self.s=Mock();self.s.editor.source.return_value=self.path
  self.snap={'sources':['s1'],'source_info':[{'id':'s1','duration':4}],'inspection_authorized':True,'inspection_policy':POLICY,'analysis':[]}
  self.answer='{"understanding":"剪辑","observations":[{"source_id":"s1","start":0,"end":1,"fact":"画面","inference":"","uncertainty":""}],"inspect":[],"limitations":[]}'
 def test_explicit_policy_and_valid_result(self):
  with patch('asr.configured_key',return_value='fake'),patch('ai_edit_native_video.read_video',return_value=self.answer) as call,patch('ai_edit_vision.save'):
   r=inspect(self.s,self.snap,'owner',False,'job')
  self.assertTrue(r['native_video']);self.assertEqual(r['initial']['observations'][0]['source_id'],'s1');self.assertTrue(call.call_args.kwargs['consent'])
 def test_legacy_policy_never_sends(self):
  with patch('ai_edit_native_video.read_video') as call,self.assertRaises(ValueError):inspect(self.s,{**self.snap,'inspection_policy':'general-inspection-v1'},'owner',False,'job')
  call.assert_not_called()
 def test_unknown_never_retried(self):
  with patch('asr.configured_key',return_value='fake'),patch('ai_edit_native_video.read_video',side_effect=VideoOutcomeUnknown('未知')) as call,self.assertRaises(Unknown):inspect(self.s,self.snap,'owner',False,'job')
  self.assertEqual(call.call_count,1)
 def test_all_sources_checked_before_any_upload(self):
  self.s.editor.source.side_effect=[self.path,Path(self.tmp.name)/'missing.mov']
  snap={**self.snap,'source_info':self.snap['source_info']+[{'id':'s2','duration':2}]}
  with patch('asr.configured_key',return_value='fake'),patch('ai_edit_native_video.read_video') as call,self.assertRaises(ValueError):inspect(self.s,snap,'owner',False,'job')
  call.assert_not_called()
