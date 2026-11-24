import json
import unittest
import test_hub as fixtures
from fastapi.testclient import TestClient

class CompactTaskTests(fixtures.HubTests):
    def test_compact_preserves_contract_and_detail_permissions(self):
        account=self.account(self.admin)
        task=self.enqueue(self.member,account).json()['id']
        config={'prompt':'中文'*10000,'provider_prompt':'provider'*10000,'model':'mini','id':'composition','assets':[{'id':'asset'}],'continuation':{'source_id':'source'}}
        with self.hub.db() as db:db.execute('UPDATE tasks SET config=? WHERE id=?',(json.dumps(config,ensure_ascii=False),task))
        full=self.member.get('/api/tasks');compact=self.member.get('/api/tasks?compact=true')
        self.assertEqual(full.status_code,200);self.assertEqual(compact.status_code,200)
        a=full.json()[0];b=compact.json()[0]
        self.assertEqual({k:v for k,v in a.items() if k!='config'},{k:v for k,v in b.items() if k!='config'})
        self.assertEqual(json.loads(b['config']),{k:v for k,v in config.items() if k not in ('prompt','provider_prompt')})
        self.assertLess(len(compact.content),len(full.content)/4)
        self.assertEqual(json.loads(self.member.get('/api/tasks/'+task+'/config').json()['config']),config)
        anon=TestClient(self.app,base_url=fixtures.BASE)
        self.assertEqual(anon.get('/api/tasks/'+task+'/config').status_code,401);anon.close()
        self.assertEqual(self.admin.get('/api/tasks/'+task+'/config').status_code,200)
        self.assertEqual(self.member.get('/api/tasks/missing/config').status_code,404)

if __name__=='__main__':unittest.main()
