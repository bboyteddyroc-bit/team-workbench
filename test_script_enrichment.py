import sqlite3, tempfile, unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import script_enrichment as e

class Hub:
 def __init__(self,p): self.p=p
 @contextmanager
 def db(self):
  c=sqlite3.connect(self.p);c.row_factory=sqlite3.Row
  try:
   with c: yield c
  finally: c.close()

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.h=Hub(str(Path(self.tmp.name)/'test.db'))
  with self.h.db() as d:
   d.executescript("CREATE TABLE script_library(id TEXT PRIMARY KEY,created_by TEXT,transcript_original TEXT,transcript_source TEXT,description TEXT,product_category TEXT,content_type TEXT,opening TEXT,expression TEXT,ending TEXT,updated REAL); CREATE TABLE users(id TEXT,enabled INTEGER); CREATE TABLE script_auto_config(owner TEXT,enabled INTEGER); INSERT INTO users VALUES('u',1); INSERT INTO script_auto_config VALUES('u',1); INSERT INTO script_library VALUES('i','u','Hello','语言 en','description','人工类目','','','','',0);")
   d.execute('ALTER TABLE script_library ADD COLUMN removed_at REAL')
   e.initialize(d);d.execute("INSERT INTO script_enrichment_consent VALUES('u',1,0)")
 def tearDown(self): self.tmp.cleanup()
 def test_success_preserves_manual(self):
  data={k:'分类' for k in e.FIELDS};data.update(transcript_en='Hello',transcript_zh='你好',tags=['使用讲解'])
  with patch('asr.configured_key',return_value='test'),patch.object(e,'request_enrichment',return_value=data) as call:e.tick(self.h);e.tick(self.h)
  self.assertEqual(call.call_count,1)
  with self.h.db() as d:
   r=d.execute('select * from script_library').fetchone();self.assertEqual(r['product_category'],'人工类目');self.assertEqual(r['audience_scenario'],'分类');self.assertEqual(r['transcript_en'],'Hello');self.assertEqual(r['transcript_zh'],'你好');self.assertIn('使用讲解',r['tags']);self.assertEqual(d.execute('select state from script_enrichment').fetchone()[0],'ready')
 def test_error_never_retries(self):
  with patch('asr.configured_key',return_value='test'),patch.object(e,'request_enrichment',side_effect=ValueError('未知')) as call:e.tick(self.h);e.tick(self.h)
  self.assertEqual(call.call_count,1)
  with self.h.db() as d:self.assertEqual(d.execute('select state from script_enrichment').fetchone()[0],'attention')
 def test_no_consent_no_call(self):
  with self.h.db() as d:d.execute('delete from script_enrichment_consent')
  with patch.object(e,'request_enrichment') as call:e.tick(self.h)
  call.assert_not_called()
if __name__=='__main__':unittest.main()
