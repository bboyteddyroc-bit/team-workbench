import json
import unittest
from provider import mini_reference_payload, TikTok


class ReferenceTests(unittest.TestCase):
    def image(self):
        return {'id':'test-upload-id','name':'reference.jpg','previewUrl':'https://p19-creative-tool-sg.ibyteimg.com/tos-alisg-i-n2703mo9gi-sg/test~tplv-n2703mo9gi-webp:1280:1280.image'}

    def test_observed_request_structure(self):
        payload=mini_reference_payload('一只白色陶瓷杯',[self.image()])
        self.assertEqual(set(payload),{'prompt','duration','model','settings','mentions'})
        self.assertEqual(payload['model'],'2000009')
        self.assertIsInstance(payload['settings'],str)
        settings=json.loads(payload['settings'])
        self.assertEqual(settings['aiModel'],'2000009')
        self.assertEqual(settings['images'][0]['label'],'image 1')
        self.assertEqual(settings['prompt'],payload['prompt'])
        self.assertEqual(payload['mentions'],[{'type':1,'id':self.image()['previewUrl']}])

    def test_local_or_untrusted_reference_rejected(self):
        for url in ['/api/assets/local','http://127.0.0.1/private','https://evil.invalid/image','https://p19-creative-tool-sg.ibyteimg.com.evil.invalid/image']:
            with self.assertRaises(ValueError):mini_reference_payload('test',[{**self.image(),'previewUrl':url}])

    def test_count_duration_and_endpoint(self):
        with self.assertRaises(ValueError):mini_reference_payload('test',[self.image()]*11)
        with self.assertRaises(ValueError):mini_reference_payload('test',[self.image()],True)
        class RecordingProvider(TikTok):
            def __init__(self): self.record=None
            def post(self,headers,operation,payload):
                self.record=(headers,operation,payload);return {'task_id':'test'}
        provider=RecordingProvider();original={'x-creative-source':'old'}
        provider.create_mini_reference(original,'test',[self.image()],15)
        self.assertEqual(provider.record[1],'i2v/gen_r2v_video')
        self.assertEqual(provider.record[0]['x-creative-source'],'cue/avatar')
        self.assertEqual(provider.record[2]['duration'],15)
        self.assertEqual(original['x-creative-source'],'old')


if __name__=='__main__':unittest.main()
