import base64,io,json,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
import a6_video as v

class VideoTransportTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.file=Path(self.temp.name)/'test.mp4';self.file.write_bytes(b'\x00\x00\x00\x18ftypisomfixture-video-bytes')
 def tearDown(self):self.temp.cleanup()
 def test_consent_and_size_guard(self):
  with self.assertRaises(ValueError):v.build_video_request('fixture-key',self.file,'analyze')
  with patch.object(v,'MAX_BYTES',3):
   with self.assertRaises(ValueError):v.build_video_request('fixture-key',self.file,'analyze',True)
 def test_50mb_boundary(self):
  self.assertEqual(v.MAX_BYTES,50_000_000)
  with self.file.open('r+b') as f:f.truncate(50_000_001)
  with patch('urllib.request.build_opener') as op:
   with self.assertRaises(ValueError):v.read_video('fixture-key',self.file,'describe',True)
   op.assert_not_called()
  with self.file.open('r+b') as f:f.truncate(50_000_000)
  req=v.build_video_request('fixture-key',self.file,'describe',True)
  self.assertGreater(len(req.data),50_000_000)  # base64 adds overhead
 def test_header_not_extension_and_oversize_before_network(self):
  extensionless=Path(self.temp.name)/'footage_id';extensionless.write_bytes(self.file.read_bytes())
  self.assertTrue(v.is_mp4(extensionless))
  fake=Path(self.temp.name)/'fake.mp4';fake.write_bytes(b'not a video')
  with patch('urllib.request.build_opener') as op:
   with self.assertRaises(ValueError):v.read_video('fixture-key',fake,'describe',True)
   with patch.object(v,'MAX_BYTES',3):
    with self.assertRaises(ValueError):v.read_video('fixture-key',extensionless,'describe',True)
   op.assert_not_called()
 def test_native_video_request_and_parse(self):
  r=v.build_video_request('fixture-key',self.file,'describe',True); d=json.loads(r.data)
  self.assertEqual(r.full_url,v.ENDPOINT)
  self.assertEqual(base64.b64decode(d['contents'][0]['parts'][1]['inline_data']['data']),b'\x00\x00\x00\x18ftypisomfixture-video-bytes')
  body=io.BytesIO(json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'ok'}]}}]}).encode())
  with patch('urllib.request.build_opener') as op:
   op.return_value.open.return_value=body
   self.assertEqual(v.read_video('fixture-key',self.file,'describe',True),'ok');self.assertEqual(op.return_value.open.call_count,1)
 def test_unknown_does_not_retry(self):
  with patch('urllib.request.build_opener') as op:
   op.return_value.open.side_effect=TimeoutError()
   with self.assertRaises(v.VideoOutcomeUnknown):v.read_video('fixture-key',self.file,'describe',True)
   self.assertEqual(op.return_value.open.call_count,1)
if __name__=='__main__':unittest.main()
