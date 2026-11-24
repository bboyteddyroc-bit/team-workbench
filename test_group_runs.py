import sqlite3
import unittest
import group_runs as g

class Tests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE apify_accounts(id TEXT, owner TEXT, handle TEXT, deleted_at REAL DEFAULT NULL)')
        self.db.execute('CREATE TABLE apify_runs(account TEXT, state TEXT)')
        self.db.executemany('INSERT INTO apify_accounts(id,owner,handle) VALUES(?,?,?)', [('a','u','a'),('b','u','b'),('c','v','c')])
        g.init_schema(self.db)
    def tearDown(self): self.db.close()
    def enqueue(self): return g.enqueue(self.db,'u',[{'id':'a','handle':'a'},{'id':'b','handle':'b'}],{},1,2)
    def test_claim_recovery_is_not_requeued(self):
        batch=self.enqueue()
        self.assertTrue(g.claim(self.db,batch))
        self.assertFalse(g.claim(self.db,batch))
        g.recover(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM grouped_runs WHERE id=?',(batch,)).fetchone()[0],'attention')
        self.assertEqual(self.db.execute("SELECT count(*) FROM grouped_run_members WHERE state='attention'").fetchone()[0],2)
    def test_remove_only_before_submit(self):
        batch=self.enqueue()
        g.deselect_pending(self.db,'u','a')
        self.assertEqual(self.db.execute('SELECT state FROM grouped_run_members WHERE account=?',('a',)).fetchone()[0],'cancelled')
        g.claim(self.db,batch);g.submitted(self.db,batch,'remote')
        g.deselect_pending(self.db,'u','b');g.recover(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM grouped_runs WHERE id=?',(batch,)).fetchone()[0],'running')
        self.assertEqual(self.db.execute('SELECT state FROM grouped_run_members WHERE account=?',('b',)).fetchone()[0],'running')
    def test_finish_requires_all_submitted_accounts_and_propagates_attention(self):
        batch=self.enqueue()
        g.claim(self.db,batch);g.submitted(self.db,batch,'remote')
        with self.assertRaises(ValueError): g.finish(self.db,batch,{'a':'ready'})
        self.assertEqual(self.db.execute('SELECT state FROM grouped_runs WHERE id=?',(batch,)).fetchone()[0],'running')
        g.finish(self.db,batch,{'a':'ready','b':'attention'})
        self.assertEqual(self.db.execute('SELECT state FROM grouped_runs WHERE id=?',(batch,)).fetchone()[0],'attention')
        self.assertEqual(self.db.execute('SELECT state FROM grouped_run_members WHERE account=?',('a',)).fetchone()[0],'ready')
        with self.assertRaises(ValueError): g.finish(self.db,batch,{'a':'ready','b':'ready'})
    def test_owner_isolation(self):
        with self.assertRaises(ValueError): g.enqueue(self.db,'u',[{'id':'c','handle':'c'}],{},1,2)

if __name__=='__main__': unittest.main()
