import unittest

from fastapi.testclient import TestClient
from script_board import locate, save_evidence, vetted_components
from test_kalodata_integration import BASE, HEADERS, Tests as Fixture


class ScriptBoardTests(unittest.TestCase):
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def test_deduplicates_sources_and_keeps_timing_bound_to_original(self):
        account = self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'boarddemo'}).json()['id']
        self.app.state.apify_monitor.ingest({'id':'board-run','account':account}, [
            {'id':'123456789','authorMeta':{'name':'boarddemo'},'text':'Public caption','playCount':20000,'diggCount':1200},
            {'id':'123456780','authorMeta':{'name':'boarddemo'},'text':'Lower-view caption','playCount':400}
        ])
        item = self.a.post('/api/intelligence/scripts/from-snapshot',headers=HEADERS,
                           json={'account':account,'video':'123456789'}).json()['id']
        with self.hub.db() as db:
            db.execute("""INSERT INTO video_cases(id,canonical,platform,video,handle,url,created_by,updated_by,created,updated)
                VALUES('case1','tt:123456789','TikTok','123456789','boarddemo','https://www.tiktok.com/@boarddemo/video/123456789','alice','alice',1,1)""")
            db.execute("INSERT INTO video_case_members VALUES('case1','alice',1)")
            db.execute("""INSERT INTO video_enrichment_jobs(id,account,video,period_start,period_end,state,created,updated,result)
                VALUES('estimate',?,'123456780','2026-10-01','2026-10-31','ready',1,1,'{"gmv":120,"currency":"USD"}')""",(account,))
        transcript = 'Still dropping clothes on the floor? Hang it over the door.'
        components = [
            {'phase':'demo','text':'Hang it over the door.'}, {'phase':'opening','text':'Still dropping clothes on the floor?'},
            {'phase':'proof','text':'This product is guaranteed to work.'},
        ]
        with self.hub.db() as db:
            db.execute('UPDATE script_library SET transcript_original=? WHERE id=?',(transcript,item))
            save_evidence(db,'archive',item,transcript,components=vetted_components(components,transcript))
            save_evidence(db,'archive',item,transcript,timing=[
                {'text':'Still dropping clothes on the floor?', 'start':0.15, 'end':2.8},
                {'text':'Hang it over the door.', 'start':4.2, 'end':6.5},
            ])
        path = '/api/intelligence/script-board'
        with TestClient(self.app,base_url=BASE) as stranger:
            self.assertEqual(stranger.get(path).status_code,401)
        board = self.b.get(path).json()
        self.assertEqual(board['total'],2)
        picked = next(item for item in board['items'] if item['has_transcript'])
        self.assertEqual(picked['case_id'],'case1')
        self.assertEqual(next(row for row in board['items'] if row['id']=='tiktok:123456780')['gm'],120)
        self.assertEqual([c['phase'] for c in picked['components']],['opening','demo'])
        self.assertEqual(picked['components'][1]['start'],4.2)
        self.assertNotIn('transcript',picked)
        self.assertEqual(self.b.get(path,params={'transcript':picked['id']}).json()['text'],transcript)
        with self.hub.db() as db:
            db.execute('UPDATE script_library SET transcript_original=? WHERE id=?',('Corrected description.',item))
        picked = next(row for row in self.b.get(path).json()['items'] if row['id']==picked['id'])
        self.assertNotIn('start',picked['components'][0])

    def test_repeated_words_have_no_fabricated_timestamp(self):
        component = {'text':'Hang it over the door'}
        row = {'text':component['text'],'start':0,'end':1}
        self.assertEqual(locate(component,[row,row]),component)
