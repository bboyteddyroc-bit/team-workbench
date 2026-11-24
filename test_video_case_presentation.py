import json,unittest
from unittest.mock import patch
from video_case_presentation import metric_projection,tag_projection,validate_tag_groups
from test_kalodata_integration import Tests as Fixture,HEADERS

class ProjectionTests(unittest.TestCase):
    def test_metric_provenance_zero_missing_and_no_cross_metric_guess(self):
        row={'human':{},'source':{'views':822800,'collects':6647,'likes':49000,'collected':1,'origin':'账号监测快照','kalodata':{'period_views':0,'gmv':25.5,'currency':'USD','period_start':'2026-10-01','period_end':'2026-10-30','likes':0,'comments':283,'shares':8121,'collected':2}}}
        m={x['key']:x for x in metric_projection(row)}
        self.assertEqual(m['views']['value'],0);self.assertEqual(m['views']['source'],'Kalodata');self.assertIn('区间播放',m['views']['scope'])
        self.assertEqual(m['likes']['value'],0);self.assertEqual(m['collects']['value'],6647);self.assertIn('累计',m['collects']['scope'])
        self.assertEqual(m['gmv']['currency'],'USD');self.assertEqual(m['comments']['value'],283);self.assertEqual(m['shares']['value'],8121)
        missing=metric_projection({'human':{},'source':{}});self.assertTrue(all(x['missing'] for x in missing))
        invalid=metric_projection({'source':{'kalodata':{'likes':float('nan'),'gmv':True,'period_views':-1}}});self.assertTrue(all(x['missing'] for x in invalid))
    def test_human_override_is_independent_and_explicit_blank_is_not_zero(self):
        row={'human':{'manual_views':'0','manual_gmv':'100','manual_gmv_currency':'EUR','manual_metric_basis':'2026年10月截图'},'source':{'kalodata':{'period_views':99,'gmv':5,'currency':'USD'}}}
        m={x['key']:x for x in metric_projection(row)};self.assertEqual(m['views']['value'],0);self.assertEqual(m['views']['source'],'人工核实');self.assertEqual(m['gmv']['currency'],'EUR')
        row['human']['manual_views']='';self.assertTrue(metric_projection(row)[0]['missing']);self.assertEqual(row['source']['kalodata']['period_views'],99)
    def test_tag_groups_are_category_stable_and_no_new_inference(self):
        p=tag_projection({'human':{},'ai':{'fields':{'tags':['围巾','多场景','母亲节','自定义词']}}})
        self.assertEqual(p['groups']['product'],['围巾']);self.assertEqual(p['groups']['scene'],['母亲节']);self.assertEqual(p['groups']['other'],['自定义词']);self.assertTrue(p['suggested'])
        p=tag_projection({'human':{'tag_groups':{'scene':[],'product':['饮具']}},'ai':{'fields':{'tags':['母亲节']}}});self.assertNotIn('母亲节',str(p));self.assertFalse(p['suggested'])
        self.assertEqual(tag_projection({'human':{'tags':[]},'ai':{'fields':{'tag_groups':{'scene':['母亲节']}}}})['groups'],{})
        for value in ({'bad':[]},{'format':['x']*9},{'scene':[{'bad':1}]},{'scene':['x'*31]}):
            with self.assertRaises(ValueError):validate_tag_groups(value)

class ApiTests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    base='/api/intelligence/cases'
    def test_end_to_end_metrics_and_tags_survive_reload_and_source_preserved(self):
        cid=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/123456789']}).json()['items'][0]['id']
        source={'views':1000,'collects':0,'origin':'账号监测快照','kalodata':{'period_views':123,'likes':0,'comments':6,'shares':7,'gmv':25,'currency':'USD','period_start':'2026-10-01','period_end':'2026-10-30'}}
        with self.app.state.hub.db() as db:db.execute('UPDATE video_cases SET source=? WHERE id=?',(json.dumps(source),cid))
        fields={'tag_groups':{'product':['饮具'],'format':['结构演示'],'scene':['圣诞送礼']},'manual_gmv':'50','manual_gmv_currency':'USD','manual_metric_basis':'人工截图核实'}
        r=self.a.post(self.base+'/'+cid,headers=HEADERS,json={'revision':1,'fields':fields});self.assertEqual(r.status_code,200,r.text)
        row=self.b.get(self.base+'/'+cid).json();self.assertEqual(row['human'],fields);self.assertEqual(row['source'],source)
        m={x['key']:x for x in row['metrics']};self.assertEqual(m['views']['value'],123);self.assertEqual(m['likes']['value'],0);self.assertEqual(m['collects']['value'],0);self.assertEqual(m['gmv']['value'],50)
        listed=self.b.get(self.base+'?limit=24').json()['items'][0];self.assertEqual(listed['metrics'],row['metrics']);self.assertEqual(listed['tagging']['groups'],fields['tag_groups'])
        self.assertEqual(self.a.post(self.base+'/'+cid,headers=HEADERS,json={'revision':1,'fields':{'tag_groups':{}}}).status_code,409)
        self.assertEqual(self.a.post(self.base+'/'+cid,headers=HEADERS,json={'revision':2,'fields':{'tag_groups':{'bad':['x']}}}).status_code,400)
    def test_large_gallery_real_pagination_and_search(self):
        urls=['https://www.tiktok.com/@demo/video/'+str(123450000+i) for i in range(65)]
        with patch.object(self.app.state.kalodata,'post') as upstream:
            self.assertEqual(self.a.post(self.base,headers=HEADERS,json={'urls':urls}).status_code,200);upstream.assert_not_called()
        first=self.a.get(self.base+'?limit=24').json();second=self.a.get(self.base+'?offset=24&limit=24').json();last=self.a.get(self.base+'?offset=48&limit=24').json()
        self.assertEqual(first['total'],65);self.assertEqual(len(last['items']),17);self.assertFalse({x['id'] for x in first['items']}&{x['id'] for x in second['items']})
        self.assertEqual(self.a.get(self.base+'?q=123450001').json()['total'],1)

if __name__=='__main__':unittest.main()
