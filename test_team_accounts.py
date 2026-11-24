import time
import unittest
from unittest.mock import patch
from test_kalodata_integration import Tests as Fixture, HEADERS

class TeamAccounts(unittest.TestCase):
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def add(self, client, handle):
        response = client.post('/api/intelligence/apify/accounts', headers=HEADERS, json={'handle':handle})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def test_team_read_only_and_restore(self):
        aid = self.add(self.a, 'sharedcreator')
        base = '/api/intelligence/apify/accounts/' + aid
        row = next(x for x in self.b.get('/api/intelligence/apify/accounts').json() if x['id'] == aid)
        self.assertFalse(row['is_owner']); self.assertEqual(row['owner_name'], 'alice')
        self.assertEqual(self.b.get(base + '/videos').status_code, 200)
        for path, payload in [('/selection', {'selected':True}),('/schedule', {'hours':0}),('/enrichment', {'enabled':False}),('/collect', {'allow_paid':True}),('/delete', {})]:
            self.assertEqual(self.b.post(base+path,headers=HEADERS,json=payload).status_code,404,path)
        self.assertEqual(self.b.post('/api/intelligence/apify/batch',headers=HEADERS,json={'accounts':[aid],'allow_paid':True}).status_code,404)
        self.assertEqual(self.a.post(base+'/selection',headers=HEADERS,json={'selected':True}).status_code,200)
        with self.hub.db() as db:
            now=time.time()
            db.execute("INSERT INTO apify_runs(id,account,state,created,updated) VALUES(?,?,'ready',?,?)",('historic',aid,now,now))
            db.execute("INSERT INTO apify_snapshots(run,account,video,published,title,views,collected) VALUES(?,?,?,?,?,?,?)",('historic',aid,'123456789',now,'history',42,now))
        with patch.object(self.app.state.apify_monitor,'request') as apify, patch.object(self.app.state.video_enrichment,'post',create=True) as kalo:
            self.assertEqual(self.a.post(base+'/delete',headers=HEADERS,json={}).status_code,200)
            self.assertFalse(any(x['id']==aid for x in self.b.get('/api/intelligence/apify/accounts').json()))
            self.assertEqual(self.b.get(base+'/videos').status_code,404)
            self.assertEqual(self.a.post(base+'/selection',headers=HEADERS,json={'selected':True}).status_code,404)
            restored=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'sharedcreator'}).json()
            self.assertEqual(restored['id'],aid); self.assertTrue(restored['restored'])
            self.assertEqual(self.a.get('/api/intelligence/apify/selection').json()['accounts'],[])
            self.assertEqual(self.b.get(base+'/videos').json()[0]['views'],42)
            apify.assert_not_called(); kalo.assert_not_called()
        other=self.add(self.b,'sharedcreator')
        self.assertNotEqual(aid,other)

    def test_queued_cancelled_but_submitting_preserved(self):
        aid=self.add(self.a,'queuedcreator'); service=self.app.state.apify_monitor
        with self.hub.db() as db:
            from group_runs import enqueue, claim
            batch=enqueue(db,'alice',[{'id':aid,'handle':'queuedcreator'}],{},1,2,automatic=True)
        self.assertEqual(self.a.post('/api/intelligence/apify/accounts/'+aid+'/delete',headers=HEADERS,json={}).status_code,200)
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT state FROM grouped_runs WHERE id=?',(batch,)).fetchone()[0],'cancelled')
        second=self.add(self.a,'inflightcreator')
        with self.hub.db() as db:
            inflight=enqueue(db,'alice',[{'id':second,'handle':'inflightcreator'}],{},1,2,automatic=True)
            claim(db,inflight)
        self.assertEqual(self.a.post('/api/intelligence/apify/accounts/'+second+'/delete',headers=HEADERS,json={}).status_code,200)
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT state FROM grouped_runs WHERE id=?',(inflight,)).fetchone()[0],'submitting')

if __name__ == '__main__': unittest.main()
