import sqlite3
import unittest
from unittest.mock import patch

import apify_run_archive as archive
import apify_transcripts as captions
import test_kalodata_integration as fixture


class ApifyTranscriptTests(unittest.TestCase):
    def test_caption_selects_original_and_keeps_cue_timestamps(self):
        url = 'https://api.apify.com/v2/key-value-stores/example/records/subtitle-abc.vtt'
        item = {'text':'This is the post caption', 'videoMeta':{'subtitleLinks':[
            {'source':'MT','language':'fr','downloadLink':url.replace('abc','translated')},
            {'source':'ASR','language':'eng-US','downloadLink':url+'?token=never-stored'},
        ]}}
        self.assertEqual(captions.subtitle(item),('/key-value-stores/example/records/subtitle-abc.vtt','eng-US'))
        self.assertEqual(captions.subtitle_resource(url.replace('api.apify.com','localhost')), '')
        self.assertEqual(captions.subtitle_resource(url.replace('abc','%2F%2E%2E')), '')
        text,cues=captions.parse_caption(b'WEBVTT\n\n00:00:01.350 --> 00:00:03.500 align:start\nHey &amp; welcome!\n\n2\n00:03.500 --> 00:05.000\n<b>Demo</b>\n')
        self.assertEqual(text,'Hey & welcome! Demo')
        self.assertEqual([(row['start'],row['end']) for row in cues],[(1.35,3.5),(3.5,5.0)])
        with self.assertRaises(ValueError):
            captions.parse_caption(b'no timed speech')

    def test_register_ignores_duplicate_success(self):
        db=sqlite3.connect(':memory:')
        captions.initialize(db)
        captions.register(db,'123','one','group:a',('/key-value-stores/a/records/x.vtt','en'))
        db.execute("UPDATE apify_video_transcripts SET state='ready',transcript='existing'")
        captions.register(db,'123','two','group:b',('/key-value-stores/b/records/y.vtt','en'))
        self.assertEqual(db.execute('SELECT run,state,transcript FROM apify_video_transcripts').fetchall(),[('one','ready','existing')])
        db.close()

    def test_run_archive_restores_only_the_specified_batch(self):
        with sqlite3.connect(':memory:') as db:
            db.row_factory=sqlite3.Row
            db.executescript("""CREATE TABLE apify_accounts(id TEXT PRIMARY KEY,handle TEXT);
                CREATE TABLE apify_runs(id TEXT PRIMARY KEY,account TEXT,state TEXT);
                CREATE TABLE apify_snapshots(run TEXT,account TEXT,video TEXT,title TEXT,PRIMARY KEY(run,video));
                INSERT INTO apify_accounts VALUES('a','demo');
                INSERT INTO apify_runs VALUES('1','a','ready'),('2','a','ready');
                INSERT INTO apify_snapshots VALUES('1','a','42','older'),('2','a','42','newer'),('1','a','43','other');""")
            self.assertEqual(archive.hide(db,'1','demo',2),2)
            db.commit()
            self.assertEqual(db.execute('SELECT title FROM apify_snapshots').fetchone()[0],'newer')
            self.assertEqual(archive.restore(db,'1','demo'),2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM apify_snapshots').fetchone()[0],3)


class ApifyTranscriptPipelineTests(unittest.TestCase):
    setUp = fixture.Tests.setUp
    tearDown = fixture.Tests.tearDown

    def test_existing_subtitle_is_saved_and_exposed_without_a_paid_call(self):
        account=self.a.post('/api/intelligence/apify/accounts',headers=fixture.HEADERS,json={'handle':'dailydemo'}).json()['id']
        source='https://api.apify.com/v2/key-value-stores/example/records/subtitle-daily.vtt'
        monitor=self.app.state.apify_monitor
        monitor.ingest({'id':'daily-run','account':account,'subtitle_binding':'group:test'},[
            {'id':'1234','authorMeta':{'name':'dailydemo'},'text':'a caption',
             'videoMeta':{'subtitleLinks':[{'source':'ASR','language':'en','downloadLink':source}]}}])
        with patch('apify_transcripts.download',return_value=b'WEBVTT\n\n00:00:00.700 --> 00:00:02.000\nThis is speech.') as get:
            captions.tick(self.hub,monitor.config)
            captions.tick(self.hub,monitor.config)
        self.assertEqual(get.call_count,1)
        board=self.b.get('/api/intelligence/script-board').json()['items'][0]
        self.assertEqual(board['description'],'a caption')
        self.assertTrue(board['has_transcript'])
        self.assertEqual(board['components'][0]['start'],.7)
        result=self.b.get('/api/intelligence/script-board',params={'transcript':'tiktok:1234'}).json()
        self.assertEqual(result['text'],'This is speech.')
