import unittest
import color_adjust
from test_export_range import ExportRangeApi
from editor import run
import shutil

class ColorTests(ExportRangeApi):
    def test_color_roundtrip_and_render(self):
        task=self.sample()
        grade={'brightness':35,'contrast':20,'saturation':-20,'hsl':{'red':{'h':20,'s':40,'l':10}}}
        body={'ratio':'9:16','clips':[{'task_id':task,'start':0,'end':1,'at':0,'volume':1,'color':grade}],'captions':[]}
        response=self.member.post('/api/editor/projects',json={'title':'调色测试','body':body},headers=__import__('test_hub').H)
        self.assertEqual(response.status_code,200,response.text)
        saved=response.json(); self.assertEqual(saved['body']['clips'][0]['color']['hsl']['red']['s'],40)
        output=self.finish(self.export(saved,'color-output-test'))
        pixels=run([shutil.which('ffmpeg'),'-v','error','-ss','0.3','-i',str(output),'-frames:v','1','-vf','scale=2:2','-threads','1','-f','rawvideo','-pix_fmt','rgb24','-'])
        self.assertEqual(len(pixels),12)
        body['clips'][0]['color']={}
        base=self.member.post('/api/editor/projects',json={'title':'原片测试','body':body},headers=__import__('test_hub').H).json()
        original=self.finish(self.export(base,'color-original-test'))
        other=run([shutil.which('ffmpeg'),'-v','error','-ss','0.3','-i',str(original),'-frames:v','1','-vf','scale=2:2','-threads','1','-f','rawvideo','-pix_fmt','rgb24','-'])
        self.assertNotEqual(pixels,other)
    def test_invalid(self):
        for grade in ({'brightness':101},{'hsl':{'red':{'h':float('inf')}}}):
            with self.assertRaises(ValueError):color_adjust.validate(grade)
