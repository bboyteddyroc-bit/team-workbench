import unittest
import multitrack

class CapabilityTests(unittest.TestCase):
    def setUp(self):multitrack._NVENC_CAPABILITIES.clear()
    def test_unavailable_is_probed_once(self):
        calls=[]
        def run(args,**kw):
            calls.append(args)
            if 'lavfi' in args:raise ValueError('unavailable')
        args=['ffmpeg-test','-c:v','libx264','-preset','veryfast','-crf','21','out.mp4']
        for _ in range(2):self.assertEqual(multitrack.run_final_encode(run,args,None),'cpu')
        self.assertEqual(sum('lavfi' in a for a in calls),1)
        self.assertEqual(sum('libx264' in a for a in calls),2)
    def test_supported_gpu_and_fallback(self):
        calls=[]
        def run(args,**kw):
            calls.append(args)
            if 'h264_nvenc' in args and 'lavfi' not in args:raise ValueError('temporary encode failure')
        args=['ffmpeg-test','-c:v','libx264','-preset','veryfast','-crf','21','out.mp4']
        self.assertEqual(multitrack.run_final_encode(run,args,None),'cpu')
        self.assertEqual(len(calls),3)
    def test_main_identity_roundtrip(self):
        data={'tracks':[{'id':'legacy'}],'main_track':'legacy','clips':[],'captions':[],'audio_clips':[]}
        result={'clips':[],'captions':[],'audio_clips':[]}
        multitrack.normalize(data,result)
        self.assertEqual(result['main_track'],'legacy')
        data['main_track']='../bad'
        with self.assertRaises(ValueError):multitrack.normalize(data,result)
