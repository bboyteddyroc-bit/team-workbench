import unittest
from unittest.mock import patch
from test_apify_config import Tests as Fixture
from apify_config import ApifyConfig
from apify_pool import KeyPool

class Tests(unittest.TestCase):
 setUp=Fixture.setUp
 tearDown=Fixture.tearDown
 def test_admin_add_round_robin_and_pin(self):
  path='/api/intelligence/apify/pool';h={'X-Hub-Request':'1','Origin':'http://127.0.0.1:8765'}
  self.assertEqual(self.b.get(path).status_code,403)
  for i in range(2):
   r=self.a.post(path,headers=h,json={'name':'key'+str(i),'secret_key':'fake-token-'+str(i)})
   self.assertEqual(r.status_code,200);self.assertNotIn('fake-token',r.text)
  pool=self.a.app.state.apify_pool if hasattr(self.a,'app') else KeyPool(self.hub,ApifyConfig(self.hub))
  first=pool.token('run:first',True);second=pool.token('group:second',True)
  self.assertNotEqual(first,second);self.assertEqual(pool.token('run:first'),first)
  self.assertEqual(pool.token('run:third',True),first)
  with self.hub.db() as db:kid=db.execute("SELECT key_id FROM apify_key_bindings WHERE run='run:first'").fetchone()[0]
  self.assertEqual(self.a.post(path+'/'+kid+'/toggle',headers=h,json={'enabled':False}).status_code,200)
  self.assertEqual(pool.token('run:first'),first)
  self.assertEqual(pool.token('run:fourth',True),second)
  self.assertEqual(self.a.post(path,headers=h,json={'secret_key':'fake-token-0'}).status_code,409)
 def test_balance_mapping_and_no_secret_return(self):
  pool=KeyPool(self.hub,ApifyConfig(self.hub));pool.add('one','fake-token-123');kid=pool.rows()[0]['id']
  import httpx
  def get(url,**kwargs):
   data={'limits':{'maxMonthlyUsageUsd':10},'current':{'monthlyUsageUsd':2}} if url.endswith('/limits') else {'totalUsageCreditsUsd':3} if url.endswith('/monthly') else {'id':'account'}
   return httpx.Response(200,json={'data':data},request=httpx.Request('GET',url))
  with patch('apify_pool.httpx.Client.get',side_effect=get):rows=pool.refresh(kid)
  self.assertEqual(rows[0]['usage'],2);self.assertEqual(rows[0]['limit_usd'],10);self.assertNotIn('secret',rows[0])
if __name__=='__main__':unittest.main()
