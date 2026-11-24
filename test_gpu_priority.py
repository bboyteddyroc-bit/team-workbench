import unittest
from unittest.mock import Mock
from multitrack import run_final_encode

class GPUFallbackTests(unittest.TestCase):
 def setUp(self):
  self.args=['ffmpeg','-y','-i','input','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','finished.mp4']
 def test_gpu_first(self):
  run=Mock();self.assertEqual(run_final_encode(run,self.args,'tmp'),'gpu')
  called=run.call_args.args[0];self.assertIn('h264_nvenc',called);self.assertNotIn('libx264',called)
 def test_cpu_fallback(self):
  run=Mock(side_effect=[ValueError('GPU unavailable'),None]);self.assertEqual(run_final_encode(run,self.args,'tmp'),'cpu')
  self.assertEqual(run.call_count,2);self.assertIn('h264_nvenc',run.call_args_list[0].args[0]);self.assertEqual(run.call_args_list[1].args[0],self.args)
 def test_cpu_failure_is_not_hidden(self):
  run=Mock(side_effect=[ValueError('GPU unavailable'),ValueError('CPU failed')])
  with self.assertRaisesRegex(ValueError,'CPU failed'):run_final_encode(run,self.args,'tmp')
 def test_unknown_options_refused(self):
  with self.assertRaises(ValueError):run_final_encode(Mock(),['ffmpeg','-c:v','copy'],'tmp')
if __name__=='__main__':unittest.main()
