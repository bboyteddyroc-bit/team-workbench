import unittest,time
from test_kalodata_integration import Tests as Fixture
from exception_center import safe_error, SOURCES

class ExceptionTests(unittest.TestCase):
 setUp=Fixture.setUp
 tearDown=Fixture.tearDown
 def test_sources_only_include_intelligence_tasks(self):
  self.assertEqual({source.table for source in SOURCES},{'script_enrichment','script_transcriptions','script_creative_tasks','grouped_runs','apify_runs','video_enrichment_jobs','kalodata_jobs','video_case_jobs','comment_sample_jobs','comment_sample_research','own_goods_lookup'})
  self.assertEqual(len({source.type for source in SOURCES}),16)
 def test_owner_scope_and_diagnostics(self):
  now=time.time()
  with self.hub.db() as db:
   db.execute("INSERT INTO grouped_runs(id,owner,state,options,start_at,end_at,created,updated,error,automatic) VALUES(?,?,'attention','{}',0,1,?,?,?,0)",('a','alice',now,now,'网络异常，结果未知；未自动重试'))
   db.execute("INSERT INTO grouped_runs(id,owner,state,options,start_at,end_at,created,updated,error,automatic) VALUES(?,?,'attention','{}',0,1,?,?,?,0)",('b','bob',now,now,'仅本人可见'))
  a=self.a.get('/api/intelligence/exceptions');b=self.b.get('/api/intelligence/exceptions')
  self.assertEqual(a.status_code,200,a.text);self.assertEqual(b.status_code,200,b.text)
  self.assertEqual([x['id'] for x in a.json()['items']],['a']);self.assertEqual([x['id'] for x in b.json()['items']],['b'])
  self.assertIn('结果未知',a.json()['items'][0]['error'])
  self.assertNotIn('secret-value',safe_error('token=secret-value https://private.example/path'))
  self.assertNotIn('private.example',safe_error('访问 https://private.example/path'))
  self.assertIn('未记录',safe_error(None))
