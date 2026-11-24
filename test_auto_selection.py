import sqlite3
import unittest
from auto_selection import init_schema, select_account, selected_accounts, get_config, set_config

class Tests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE apify_accounts(id TEXT, owner TEXT, handle TEXT, deleted_at REAL DEFAULT NULL)')
        self.db.executemany('INSERT INTO apify_accounts(id,owner,handle) VALUES(?,?,?)', [('a','u','a'),('b','u','b'),('c','v','c')])
        init_schema(self.db)
    def tearDown(self): self.db.close()
    def test_default_off_and_confirmation(self):
        self.assertEqual(get_config(self.db,'u'), {'collection_enabled':False,'enrichment_enabled':False})
        with self.assertRaises(ValueError): set_config(self.db,'u',True,False)
        set_config(self.db,'u',True,True,confirmed=True)
        self.assertTrue(get_config(self.db,'u')['enrichment_enabled'])
        set_config(self.db,'u',False,False)
        self.assertFalse(get_config(self.db,'u')['collection_enabled'])
    def test_selection_ownership_and_persistence(self):
        select_account(self.db,'u','a',True)
        with self.assertRaises(ValueError): select_account(self.db,'u','c',True)
        self.assertEqual(selected_accounts(self.db,'u'),['a'])
        self.assertEqual(selected_accounts(self.db,'v'),[])
        select_account(self.db,'u','a',False)
        self.assertEqual(selected_accounts(self.db,'u'),[])

if __name__ == '__main__': unittest.main()
