import tempfile
import unittest
from pathlib import Path
import asr
from editor import caption_anim, caption_words, write_ass

class SpokenHighlightTests(unittest.TestCase):
    def test_recognizer_word_timings_survive_grouping(self):
        segments=[{'start':0,'end':2,'text':'The quick brown', 'words':[
            {'text':'The','start':.12,'end':.35}, {'text':'quick','start':.5,'end':.8},
            {'text':'brown','start':1.2,'end':1.7}]}]
        row=asr.timed_caption_rows(segments)[0]
        self.assertEqual([w['text'] for w in row['words']],['The','quick','brown'])
        self.assertEqual(row['words'][2]['start'],1.2)
        self.assertEqual(caption_words(row,row['text'],row['end']-row['start']),row['words'])

    def test_auto_rows_resolve_overlap_at_word_boundary(self):
        from unittest.mock import patch
        rows=[{'start':0.0,'end':1.94,'text':'one'},
              {'start':1.72,'end':3.18,'text':'two'}]
        segments=[{'start':0,'end':3.18,'text':'one two','words':[
            {'text':'one','start':1.72,'end':1.94},
            {'text':'two','start':1.94,'end':2.10}]}]
        with patch.object(asr,'place_rows',return_value=rows):
            result=asr.timed_caption_rows(segments)
        self.assertEqual(result[0]['end'],1.94)
        self.assertEqual(result[1]['start'],1.94)
        self.assertEqual(result[1]['words'][0]['start'],0)
        for row in result:
            self.assertEqual(caption_words(row,row['text'],row['end']-row['start']),row['words'])

    def test_invalid_and_missing_words(self):
        self.assertEqual(caption_words({},'hello',2),[])
        with self.assertRaises(ValueError):
            caption_words({'words':[{'text':'no','from':0,'to':2,'start':0,'end':1}]},'hello',2)

    def test_export_uses_spoken_timings_and_color(self):
        caption={'text':'The quick','start':0,'end':2,'font':'default',
                 'anim':{'loop':{'id':'spoken','color':'#f02030'}},
                 'words':[{'text':'The','from':0,'to':3,'start':.2,'end':.5},
                          {'text':'quick','from':4,'to':9,'start':1,'end':1.5}]}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'test.ass';write_ass(path,[caption],720,1280)
            content=path.read_text(encoding='utf-8-sig')
        self.assertIn(r'\t(200,201,\1c&H003020F0)',content)
        self.assertIn(r'\t(500,501,\1c&H00FFFFFF)',content)
        self.assertIn(r'\t(1000,1001,\1c&H003020F0)',content)
        self.assertEqual(caption_anim(caption)['loop']['color'],'#f02030')

if __name__=='__main__': unittest.main()
