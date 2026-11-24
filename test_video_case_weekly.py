import json, unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from test_kalodata_integration import Tests as Fixture, HEADERS
from video_case_weekly import next_friday,dispatch

CN=timezone(timedelta(hours=8))
class WeeklyTests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    base='/api/intelligence/cases'
    def test_next_friday_boundaries(self):
        fri=datetime(2026,11,20,8,tzinfo=CN).timestamp()
        self.assertEqual(next_friday(fri-1),fri)
        self.assertEqual(next_friday(fri),fri+7*86400)
    def test_new_consent_enrolls_one_apify_and_weekly_once(self):
        now=datetime(2026,11,18,10,tzinfo=CN).timestamp();due=next_friday(now)
        r=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789'],'auto_process':True,'confirm_automation':True,'share_with_team':True})
        self.assertEqual(r.status_code,200,r.text);cid=r.json()['items'][0]['id']
        with self.app.state.hub.db() as db:db.execute('UPDATE video_case_weekly_enrollment SET created=?,due=? WHERE case_id=?',(now,due,cid))
        with self.app.state.hub.db() as db:
            jobs=db.execute('SELECT kind,options FROM video_case_jobs WHERE case_id=?',(cid,)).fetchall()
            self.assertEqual([j['kind'] for j in jobs],['metadata'])
            self.assertEqual(db.execute('SELECT due FROM video_case_weekly_enrollment WHERE case_id=?',(cid,)).fetchone()[0],due)
        hub=self.app.state.hub
        self.assertFalse(dispatch(hub,due-1));self.assertTrue(dispatch(hub,due));self.assertFalse(dispatch(hub,due+1))
        with hub.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE case_id=? AND kind='kalodata'",(cid,)).fetchone()[0],1)
    def test_expired_and_unknown_are_not_retried(self):
        now=datetime(2026,11,18,10,tzinfo=CN).timestamp()
        cid=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789'],'auto_process':True,'confirm_automation':True,'share_with_team':True}).json()['items'][0]['id']
        due=next_friday(now)
        with self.app.state.hub.db() as db:db.execute('UPDATE video_case_weekly_enrollment SET created=?,due=? WHERE case_id=?',(now,due,cid))
        self.assertTrue(dispatch(self.app.state.hub,due+7*86400))
        with self.app.state.hub.db() as db:
            self.assertEqual(db.execute('SELECT state FROM video_case_weekly_enrollment WHERE case_id=?',(cid,)).fetchone()[0],'skipped')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE kind='kalodata' AND case_id=?",(cid,)).fetchone()[0],0)
    def test_busy_limit_defers_without_enqueuing(self):
        cid=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789'],'auto_process':True,'confirm_automation':True,'share_with_team':True}).json()['items'][0]['id']
        with self.app.state.hub.db() as db:
            e=db.execute('SELECT owner,due FROM video_case_weekly_enrollment WHERE case_id=?',(cid,)).fetchone();owner,due=e['owner'],e['due']
            for n in range(100):
                db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'kalodata','queued',?,?,?,'{}')",('busy'+str(n),'other'+str(n),owner,'busy'+str(n),1,1))
        self.assertFalse(dispatch(self.app.state.hub,due))
        with self.app.state.hub.db() as db:self.assertEqual(db.execute('SELECT state FROM video_case_weekly_enrollment WHERE case_id=?',(cid,)).fetchone()[0],'pending')
    def test_failed_apify_still_enqueues_analysis_without_retry(self):
        cid=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789'],'auto_process':True,'confirm_automation':True,'share_with_team':True}).json()['items'][0]['id']
        svc=self.app.state.video_cases
        with patch.object(svc.monitor,'request',side_effect=ValueError('unknown')) as req:
            svc.tick('media');self.assertEqual(req.call_count,1)
        with self.app.state.hub.db() as db:
            self.assertEqual(db.execute("SELECT state FROM video_case_jobs WHERE kind='metadata' AND case_id=?",(cid,)).fetchone()[0],'attention')
            self.assertEqual(db.execute("SELECT state FROM video_case_jobs WHERE kind='analysis' AND case_id=?",(cid,)).fetchone()[0],'queued')
if __name__=='__main__':unittest.main()
