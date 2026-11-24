import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import video_case_analysis as c

class CaseNativeTests(unittest.TestCase):
 def test_native_video_passes_context_and_consent(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.mp4';p.write_bytes(b'fixture')
   receipt=Path(d)/'answer.txt';value={'fields':{'summary':'test'},'evidence':{},'uncertainties':[]}
   with patch('a6_video.read_video',return_value=json.dumps(value)) as call:
    result=c.request_native_video({'missing_fields':['summary']},p,'fake-key',receipt,consent=True)
   self.assertEqual(result,value);self.assertTrue(receipt.exists());self.assertTrue(call.call_args.kwargs['consent'])
   self.assertIn('missing_fields',call.call_args.args[2]);self.assertIn('GMV',call.call_args.args[2])
 def test_failed_call_never_falls_back(self):
  with patch('a6_video.read_video',side_effect=ValueError('unknown')) as read,patch.object(c,'request') as old:
   with self.assertRaises(ValueError):c.request_native_video({},'x.mp4','fake-key',consent=True)
   self.assertEqual(read.call_count,1);old.assert_not_called()
if __name__=='__main__':unittest.main()
