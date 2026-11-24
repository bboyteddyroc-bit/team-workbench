import unittest
from test_kalodata_integration import Tests as Fixture, HEADERS
from script_library import matches

class ScriptLibraryTests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    def test_rule_boundaries_and_missing(self):
        thresholds={'likes':5,'collects':0.8,'comments':0.15}
        self.assertEqual(matches({'views':9999,'likes':9999},thresholds),[])
        self.assertEqual(matches({'views':10000,'likes':500,'collects':None,'comments':None},thresholds),['点赞率达标'])
        self.assertEqual(matches({'views':700000,'likes':None},thresholds),['播放量 ≥ 70 万'])
        self.assertEqual(matches({'views':10000,'likes':None,'collects':None,'comments':None},thresholds),[])
        self.assertEqual(matches({'views':None,'likes':1000},thresholds),[])
    def test_remove_shared_item_preserves_record_and_prevents_readd(self):
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'removedemo'}).json()['id']
        self.app.state.apify_monitor.ingest({'id':'fake','account':aid},[{'id':'123456789','authorMeta':{'name':'removedemo'},'text':'demo','playCount':700000}])
        path='/api/intelligence/scripts';item=self.a.post(path+'/from-snapshot',headers=HEADERS,json={'account':aid,'video':'123456789'}).json()['id']
        self.assertEqual(self.b.post(path+'/'+item+'/remove',headers=HEADERS,json={'confirm':True}).status_code,200)
        self.assertEqual(self.a.get(path).json(),[])
        self.assertEqual(self.a.post(path+'/from-snapshot',headers=HEADERS,json={'account':aid,'video':'123456789'}).status_code,409)
        self.assertEqual(self.a.post(path+'/'+item,headers=HEADERS,json={'notes':'change'}).status_code,404)
        with self.app.state.hub.db() as db:self.assertIsNotNone(db.execute('SELECT removed_at FROM script_library WHERE id=?',(item,)).fetchone()[0])
    def test_simulation_persistence_and_team_access(self):
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'librarydemo'}).json()['id']
        service=self.app.state.apify_monitor
        service.ingest({'id':'fake-run','account':aid},[{'id':'123456789','authorMeta':{'name':'librarydemo'},'createTime':1700000000,'text':'post description','playCount':100000,'diggCount':6000,'commentCount':50}])
        path='/api/intelligence/scripts'
        res=self.a.get(path+'/simulate').json()
        self.assertEqual(len(res['matched']),1)
        self.assertEqual(res['matched'][0]['reasons'],['点赞率达标'])
        item=self.a.post(path+'/from-snapshot',headers=HEADERS,json={'account':aid,'video':'123456789'}).json()
        self.assertFalse(item['existing'])
        self.assertTrue(self.b.post(path+'/from-snapshot',headers=HEADERS,json={'account':aid,'video':'123456789'}).json()['existing'])
        items=self.b.get(path).json()
        self.assertEqual(len(items),1)
        self.assertIsNone(items[0]['transcript_original'])
        self.assertEqual(items[0]['transcript_status'],'未提取')
        self.assertEqual(self.b.post(path+'/'+item['id'],headers=HEADERS,json={'product_category':'工具','opening':'痛点开场','audience_scenario':'车主洗车后','edited_text':'手动整理'}).status_code,200)
        saved=self.a.get(path).json()[0]
        self.assertEqual(saved['product_category'],'工具')
        self.assertEqual(saved['edited_text'],'手动整理')
        self.assertEqual(saved['audience_scenario'],'车主洗车后')
        self.assertEqual(self.a.post(path+'/'+item['id'],headers=HEADERS,json={'tags':[' 洗车 ', '痛点切入','洗车'],'pain_point':'清洁缝隙','reuse_framework':'痛点 → 方案'}).status_code,200)
        tagged=self.b.get(path).json()[0]
        self.assertEqual(tagged['tags'],['洗车','痛点切入'])
        self.assertEqual(tagged['pain_point'],'清洁缝隙')
        self.assertEqual(tagged['reuse_framework'],'痛点 → 方案')
        self.assertEqual(self.a.post(path+'/'+item['id'],headers=HEADERS,json={'tags':['x'*31]}).status_code,400)
        self.assertEqual(self.a.post(path+'/'+item['id'],headers=HEADERS,json={'tags':'bad'}).status_code,400)
        self.assertEqual(self.a.post(path+'/'+item['id'],headers=HEADERS,json={'tags':[]}).status_code,200)
        self.assertEqual(self.b.get(path).json()[0]['tags'],[])
        with service.hub.db() as db:
            db.execute("UPDATE script_library SET transcript_original=?,transcript_source=?,transcript_zh=? WHERE id=?",('Original full transcript','语言 en','中文翻译',item['id']))
        from unittest.mock import patch
        payload={'source_id':item['id'],'product':'已核实：手持工具','request_key':'test-request-key-123'}
        with patch('asr.configured_key',return_value='fake'),patch('script_creation.generate',return_value='测试脚本') as gen:
            result=self.a.post('/api/intelligence/creative-tasks',headers=HEADERS,json=payload).json()
            duplicate=self.a.post('/api/intelligence/creative-tasks',headers=HEADERS,json=payload).json()
        self.assertEqual(gen.call_count,1)
        reference=gen.call_args.args[0]
        self.assertEqual(reference['transcript_original'],'Original full transcript')
        self.assertEqual(reference['transcript_source'],'语言 en')
        self.assertEqual(reference['transcript_zh'],'中文翻译')
        self.assertEqual(reference['pain_point'],'清洁缝隙')
        self.assertEqual(reference['reuse_framework'],'痛点 → 方案')
        self.assertEqual(reference['tags'],[])
        self.assertEqual(result['id'],duplicate['id'])
        tasks=self.b.get('/api/intelligence/creative-tasks').json();self.assertEqual(tasks[0]['content'],'测试脚本')
        self.assertEqual(tasks[0]['number'],1)
        self.assertEqual(tasks[0]['reference_video'],'123456789')
        self.assertEqual(self.b.post('/api/intelligence/creative-tasks/'+result['id'],headers=HEADERS,json={'content':'修改稿','state':'待制作'}).status_code,200)
        self.assertEqual(self.a.get('/api/intelligence/creative-tasks').json()[0]['content'],'修改稿')
        self.assertEqual(saved['description'],'post description')
        self.assertIsNone(saved['transcript_original'])
        self.assertEqual(self.a.post(path+'/'+item['id'],headers=HEADERS,json={'transcript_original':'forbidden'}).status_code,400)

if __name__=='__main__': unittest.main()
