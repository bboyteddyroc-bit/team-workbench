import tempfile,unittest,shutil
from pathlib import Path
from unittest.mock import patch
from editor import run,probe
import editor_media_cache as cache
from ai_edit_vision import frame

class FrameBoundaryTests(unittest.TestCase):
    def test_stream_duration_not_container_and_fps(self):
        video={'codec_type':'video','duration':'7.041667','avg_frame_rate':'24/1'}
        with patch('editor.probe',return_value=(7.104,[video,{'codec_type':'audio','duration':'7.104'}])):
            self.assertEqual(cache.frame_time('unused',7.062),7)
            self.assertEqual(cache.frame_time('unused',0),0)
        video.pop('duration');video.update(duration_ts=169,time_base='1/24')
        with patch('editor.probe',return_value=(7.104,[video])):self.assertEqual(cache.frame_time('unused',7.062),7)

    def test_unknown_duration_and_no_video(self):
        with patch('editor.probe',return_value=(7.104,[{'codec_type':'video','avg_frame_rate':'0/0'}])):
            self.assertEqual(cache.frame_time('unused',99),7.004)
        with patch('editor.probe',return_value=(7.104,[{'codec_type':'audio'}])):
            with self.assertRaisesRegex(ValueError,'视频轨'):cache.frame_time('unused',1)

    def test_real_longer_audio_container_thumbnails_and_vision_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'audio-longer.mp4'
            run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=red:s=96x96:r=24:d=1','-f','lavfi','-i','sine=frequency=440:duration=1.104','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-threads','1',str(source)])
            duration,streams=probe(source)
            self.assertGreater(duration,float(streams[0]['duration']))
            with patch.object(cache,'ROOT',root/'cache'):
                image=cache.thumbnail(source,duration,run,'ffmpeg')
                large=frame(None,source,duration)
                self.assertTrue(image.stat().st_size);self.assertTrue(large.stat().st_size)
                self.assertNotEqual(image,large)
                self.assertLessEqual(cache.frame_time(source,duration),1-1/24+.001)
                image.write_bytes(b'')
                self.assertTrue(cache.thumbnail(source,duration,run,'ffmpeg').stat().st_size)

if __name__=='__main__':unittest.main()
