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
