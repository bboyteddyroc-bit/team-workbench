import json,time,unittest
from unittest.mock import patch
from test_hub import HubTests,ProviderError

class QueueRecoveryTests(unittest.TestCase):
    setUp=HubTests.setUp
    tearDown=HubTests.tearDown
    login=HubTests.login
    account=HubTests.account
    enqueue=HubTests.enqueue
    due=HubTests.due

    def test_poll_failure_rechecks_without_generation(self):
        account=self.account(self.admin);task=self.enqueue(self.member,account).json()['id']
        self.hub.tick();self.due()
        with patch.object(self.provider,'find',side_effect=ProviderError('query timeout')):self.hub.tick()
        rows=self.member.get('/api/tasks').json();self.assertEqual(rows[0]['state'],'attention')
        self.assertIn('60',rows[0]['error'])
        queued=self.enqueue(self.member,account,'next-request-00002').json()['id']
        rows=self.member.get('/api/tasks').json();self.assertIn('等待后台调度',next(t for t in rows if t['id']==queued)['queue_reason'])
        with self.hub.db() as db:remote=db.execute('select remote_id from tasks where id=?',(task,)).fetchone()[0]
        self.provider.results[remote]={'hasContent':True,'videoInfo':{'OriginalVideoInfo':{'MainUrl':'fake','VideoMeta':{}}}}
        self.due();self.hub.tick()
        with self.hub.db() as db:self.assertEqual(db.execute('select state from tasks where id=?',(task,)).fetchone()[0],'ready')
        self.assertEqual(len(self.provider.created),2)
        self.hub.tick();self.assertEqual(len(self.provider.created),2)

    def test_queue_positions_include_other_members_without_exposing_tasks(self):
        account=self.account(self.admin)
        first=self.enqueue(self.admin,account,'position-admin-0001').json()['id']
        second=self.enqueue(self.member,account,'position-member-001').json()['id']
        rows=self.member.get('/api/tasks').json()
        self.assertFalse(any(t['id']==first for t in rows))
        self.assertEqual(next(t for t in rows if t['id']==second)['queue_position'],2)
        with self.hub.db() as db:db.execute("UPDATE tasks SET state='cancelled' WHERE id=?",(first,))
        rows=self.member.get('/api/tasks').json()
        self.assertEqual(next(t for t in rows if t['id']==second)['queue_position'],1)

    def test_unknown_unique_history_match_and_no_resubmit(self):
        account=self.account(self.admin);task=self.enqueue(self.member,account).json()['id']
        self.provider.fail=True;self.hub.tick()
        with self.hub.db() as db:t=dict(db.execute('select * from tasks where id=?',(task,)).fetchone())
        draft={'taskId':'999999','id':'draft999','createdAt':t['submitted_at'],'settings':json.dumps({'prompt':t['prompt'],'duration':t['duration']})}
        with patch.object(self.provider,'history',return_value={'draft_infos':[draft]}):self.due();self.hub.tick()
        with self.hub.db() as db:r=db.execute('select state,remote_id from tasks where id=?',(task,)).fetchone();self.assertEqual(tuple(r),('running','999999'))
        self.assertEqual(len(self.provider.created),1)

    def test_ambiguous_history_never_guesses(self):
        account=self.account(self.admin);task=self.enqueue(self.member,account).json()['id']
        self.provider.fail=True;self.hub.tick()
        with self.hub.db() as db:t=dict(db.execute('select * from tasks where id=?',(task,)).fetchone())
        draft={'taskId':'999999','createdAt':t['submitted_at'],'settings':json.dumps({'prompt':t['prompt'],'duration':t['duration']})}
        with patch.object(self.provider,'history',return_value={'draft_infos':[draft,dict(draft,taskId='888888')]}):self.due();self.hub.tick()
        with self.hub.db() as db:self.assertEqual(db.execute('select state from tasks where id=?',(task,)).fetchone()[0],'unknown')
        self.assertEqual(len(self.provider.created),1)
