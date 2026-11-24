"""Offline regression from the single verified provider receipt. Never sends a request."""
import copy,json,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from video_case_kalodata import fetch
from video_case_commercial import projection
from video_case_presentation import metric_projection
from test_kalodata_integration import Tests as Fixture,HEADERS

ROOT=Path(__file__).resolve().parent
RECEIPT=ROOT/'verification/kalodata-known-video-7707267947466607885-20261117.json'
OPTIONS={'period_start':'2026-10-17','period_end':'2026-11-15','days':30,'region':'US','currency':'USD'}
CASE={'video':'7707267947466607885','handle':'mydlvz1'}

def observed():
    receipt=json.loads(RECEIPT.read_text(encoding='utf-8'))
    assert len(receipt['calls'])==1
    call=receipt['calls'][0]
    assert call['http_status']==200 and call['success'] is True and call['exact_match_count']==1
    return copy.deepcopy(call['exact_data'])

class RecordedResponseTests(unittest.TestCase):
    def test_real_response_projects_five_metrics_and_missing_collection(self):
        provider=SimpleNamespace(post=Mock(return_value=observed()))
        kd=fetch(provider,CASE,OPTIONS)
        self.assertEqual(provider.post.call_count,1)
        self.assertEqual(provider.post.call_args.args[1]['date_range'],'2026-10-17~2026-11-15')
        row={'source':{'kalodata':kd},'human':{}}
        metrics={x['key']:x for x in metric_projection(row)}
        for key,value in [('views',19122132),('likes',71136),('shares',4673),('comments',525),('gmv',863640)]:
            self.assertEqual(metrics[key]['value'],value)
            self.assertFalse(metrics[key]['missing'])
        self.assertTrue(metrics['collects']['missing'])
        self.assertNotIn('ad_spend',kd);self.assertNotIn('ads_spend',kd)
        self.assertEqual(kd['extra_metric_provenance']['ad_view_ratio']['raw_value'],61.644627283192065)
        rows={r['key']:r for r in projection(row)}
        self.assertAlmostEqual(rows['ad_view_ratio']['value'],0.6164462728319207)
        self.assertEqual(rows['ads_roas']['value'],4.42)
        self.assertEqual(rows['units']['value'],35985)
        self.assertAlmostEqual(rows['ad_cpa']['value'],4.346426042023327)
        # Provider fields disagree under naive arithmetic: preserve facts, don't recompute/overwrite.
        self.assertEqual(rows['ads_views']['value'],19122132)
        self.assertEqual(rows['ads_period']['value'],4)
    def test_recorded_trend_preserved_without_invented_dates(self):
        kd=fetch(SimpleNamespace(post=Mock(return_value=observed())),CASE,OPTIONS)
        self.assertEqual(kd['revenue_trend'],observed()['revenue_trend'])
        rows={r['key']:r for r in projection({'source':{'kalodata':kd}})}
        self.assertFalse(rows['revenue_trend']['missing'])
        self.assertIn('128112',rows['revenue_trend']['value'])
        self.assertIn('未确认',rows['revenue_trend']['note'])
        self.assertTrue(rows['publish_date']['missing'])
        kd['creator_debut']='2025-01-01'
        rows={r['key']:r for r in projection({'source':{'kalodata':kd}})}
        self.assertTrue(rows['publish_date']['missing'])
        self.assertEqual(rows['creator_debut']['value'],'2025-01-01')
    def test_bad_trend_does_not_create_values(self):
        for trend in ([0,-1],[1,True],[1,None],['nan'],list(range(367))):
            data=observed();data['revenue_trend']=trend
            kd=fetch(SimpleNamespace(post=Mock(return_value=data)),CASE,OPTIONS)
            self.assertNotIn('revenue_trend',kd)
    def test_percentage_contract_not_inferred_from_magnitude(self):
        for raw,want in [(0,0),(0.25,0.0025),(1,0.01),(61.644627283192065,0.6164462728319207),(100,1),(-1,None),(101,None),(True,None),(None,None),('0.25',0.0025)]:
            with self.subTest(raw=raw):
                data=observed();data['ad_view_ratio']=raw
                kd=fetch(SimpleNamespace(post=Mock(return_value=data)),CASE,OPTIONS)
                actual=kd['extra_metrics']['ad_view_ratio']
                if want is None:self.assertIsNone(actual)
                else:self.assertAlmostEqual(actual,want)
    def test_identity_mismatch_still_rejected(self):
        for field,value in [('video_id','123456789'),('belonged_creator_handle','somebody_else'),('video_region','GB')]:
            with self.subTest(field=field):
                data=observed();data[field]=value
                with self.assertRaises(Exception):fetch(SimpleNamespace(post=Mock(return_value=data)),CASE,OPTIONS)

class RecordedResponseApiTests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    def test_database_and_detail_endpoint_from_recorded_result_without_live_api(self):
        base='/api/intelligence/cases'
        response=self.a.post(base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@mydlvz1/video/'+CASE['video']]})
        self.assertEqual(response.status_code,200,response.text)
        cid=response.json()['items'][0]['id']
        process=self.a.post(base+'/'+cid+'/process',headers=HEADERS,json={'kind':'kalodata','confirm':True,'share_with_team':True,'days':30,'request_key':'recorded-known-video-response-v1'})
        self.assertEqual(process.status_code,200,process.text)
        with self.app.state.hub.db() as db:
            db.execute('UPDATE video_case_jobs SET options=? WHERE case_id=? AND kind=?',(json.dumps(OPTIONS),cid,'kalodata'))
        service=self.app.state.video_cases
        with patch.object(service.kalodata,'post',return_value=observed()) as fake:
            service.tick('data')
            service.tick('data')
            detail=self.a.get(base+'/'+cid).json()
            summary=self.a.get(base).json()['items'][0]
        self.assertEqual(fake.call_count,1)
        self.assertEqual(detail['data_status']['state'],'ready')
        self.assertEqual(detail['source']['kalodata']['gmv'],863640)
        self.assertEqual(summary['source']['kalodata']['likes'],71136)
        self.assertEqual(next(x for x in detail['commercial'] if x['key']=='ad_view_ratio')['value'],61.644627283192065/100)
        self.assertTrue(next(x for x in detail['metrics'] if x['key']=='collects')['missing'])
        self.assertFalse(any(j['kind']=='analysis' for j in detail['jobs']))

if __name__=='__main__':unittest.main()
