import json,threading,unittest
from unittest.mock import patch
from test_kalodata_integration import Tests as Fixture,HEADERS
from video_case_kalodata import fetch,period
from video_case_commercial import projection,date_text
from video_case_fields import projection as fields
from kalodata_integration import QueryError

class CommercialTests(unittest.TestCase):
    def test_actual_fields_and_zero_and_negative_growth(self):
        from types import SimpleNamespace
        post=unittest.mock.Mock(return_value={'video_id':'123456789','belonged_creator_handle':'demo','video_region':'US','views':0,'revenue':0,'ad':0,'ai_video':1,'creator_debut':'2026-11-01','publish_date':'2026/11/01 18:30:00','belonged_creator_id':'987654321','ads_views':'0','ads_roas':'1.5','ad_cpa':'0','ads_period':5,'ad_view_ratio':0.25,'revenue_growth_rate':-0.5,'category_ids':['fake-filter']})
        kd=fetch(SimpleNamespace(post=post),{'video':'123456789','handle':'demo'},period())
        self.assertEqual(post.call_count,1);self.assertEqual(post.call_args.args[0],'/video/detail')
        self.assertEqual(kd['extra_metrics']['revenue_growth_rate'],-0.5)
        self.assertNotIn('creator_debut',kd['provider_flags']);self.assertEqual(kd['creator_debut'],'2026-11-01')
        self.assertNotIn('category_ids',kd);self.assertNotIn('category',kd)
        rows={r['key']:r for r in projection({'source':{'kalodata':kd}})}
        self.assertEqual(rows['ads_views']['value'],0);self.assertFalse(rows['ads_views']['missing']);self.assertEqual(rows['ad_view_ratio']['value'],0.0025)
        self.assertIn('自然视频',rows['ad']['value']);self.assertEqual(rows['publish_date']['value'],'2026/11/01 18:30:00')
        row={'source':{'kalodata':kd},'human':{},'ai':{'fields':{'published_at':'invented','product_category':'AI建议品类'}}}
        self.assertEqual(fields(row)['published_at']['source'],'Kalodata');self.assertEqual(fields(row)['category']['source'],'AI建议 · 待审核')
        row['human']={'published_at':''};self.assertEqual(fields(row)['published_at']['value'],'')
    def test_invalid_values_dates_and_provider_flags_not_facts(self):
        self.assertIsNone(date_text('2026-02-30'));self.assertIsNone(date_text(True))
        rows={r['key']:r for r in projection({'source':{'kalodata':{'provider_flags':{'creator_debut':True},'duration':False,'extra_metrics':{'ads_roas':float('nan')}}}})}
        self.assertTrue(rows['publish_date']['missing']);self.assertTrue(rows['ad']['missing']);self.assertTrue(rows['ads_roas']['missing']);self.assertTrue(rows['duration']['missing'])
        self.assertTrue(rows['creator_debut']['missing']);self.assertTrue(rows['revenue_trend']['missing'])
        self.assertEqual(len(rows),17)
        resolved=fields({'source':{'kalodata':{'creator_debut':'2026-11-01'}},'human':{},'ai':{}})
        self.assertTrue(resolved['published_at']['missing'])

class FastLaneTests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    base='/api/intelligence/cases'
    def add_auto(self,video='123456789'):
        response=self.a.post(self.base,headers=HEADERS,json={'urls':['https://www.tiktok.com/@demo/video/'+video],'auto_process':True,'confirm_automation':True,'share_with_team':True})
        self.assertEqual(response.status_code,200,response.text)
        cid=response.json()['items'][0]['id']
        # Exercise the data lane explicitly; automatic cases now wait for weekly dispatch.
        from video_case_weekly import dispatch
        with self.app.state.hub.db() as db:due=db.execute('SELECT due FROM video_case_weekly_enrollment WHERE case_id=?',(cid,)).fetchone()[0]
        dispatch(self.app.state.hub,due)
        return cid
    def test_data_lane_not_blocked_by_running_media_and_two_claimers_once(self):
        cid=self.add_auto();svc=self.app.state.video_cases;entered=threading.Event();release=threading.Event();errors=[]
        with self.app.state.hub.db() as db:
            uid=db.execute('SELECT owner FROM video_case_jobs WHERE case_id=?',(cid,)).fetchone()[0]
            db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES('slow-media',?,?,'analysis','queued','slow-test',1,1,'{}')",(cid,uid))
        def slow(*args):entered.set();self.assertTrue(release.wait(10))
        def worker():
            try:svc.tick('media')
            except BaseException as exc:errors.append(exc)
        with patch.object(svc,'analysis',side_effect=slow),patch.object(svc.kalodata,'post',return_value={'video_id':'123456789','views':0,'revenue':12,'video_title':'actual','ads_roas':2}) as call:
            thread=threading.Thread(target=worker);thread.start()
            try:
                self.assertTrue(entered.wait(5));svc.tick('data');svc.tick('data')
                self.assertEqual(call.call_count,1)
                row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['data_status']['state'],'ready');self.assertEqual(row['source']['kalodata']['period_views'],0)
                self.assertTrue(any(j['id']=='slow-media' and j['state']=='running' for j in row['jobs']))
                self.assertTrue(any(r['key']=='ads_roas' and r['value']==2 for r in row['commercial']))
            finally:release.set();thread.join(10)
        self.assertFalse(thread.is_alive());self.assertFalse(errors)
    def test_two_data_claimers_share_single_submission(self):
        cid=self.add_auto();svc=self.app.state.video_cases;entered=threading.Event();release=threading.Event();errors=[]
        def blocked(*args):
            entered.set();self.assertTrue(release.wait(10));return {'video_id':'123456789','views':9}
        def worker():
            try:svc.tick('data')
            except BaseException as exc:errors.append(exc)
        with patch.object(svc.kalodata,'post',side_effect=blocked) as call:
            thread=threading.Thread(target=worker);thread.start()
            try:
                self.assertTrue(entered.wait(5));svc.tick('data');self.assertEqual(call.call_count,1)
            finally:release.set();thread.join(10)
        self.assertFalse(thread.is_alive());self.assertFalse(errors)
        self.assertEqual(self.a.get(self.base+'/'+cid).json()['data_status']['state'],'ready')
    def test_unavailable_no_retry_no_rank_guess_and_get_is_read_only(self):
        cid=self.add_auto();svc=self.app.state.video_cases
        with patch.object(svc.kalodata,'post',side_effect=QueryError('video not found',endpoint='/video/detail',reason='not_found')) as call:
            svc.tick('data');svc.tick('data');row=self.a.get(self.base+'/'+cid).json()
            self.assertEqual(row['data_status']['state'],'unavailable');self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[0],'/video/detail');self.assertEqual(row['source'],{})
            self.assertTrue(all(m['missing'] for m in row['metrics']))
            self.a.get(self.base);self.a.get(self.base+'/'+cid);self.assertEqual(call.call_count,1)
            self.assertEqual(self.add_auto(),cid);svc.tick('data');self.assertEqual(call.call_count,1)
    def test_queued_fast_state_and_light_gallery_no_long_transcript(self):
        cid=self.add_auto();row=self.a.get(self.base+'/'+cid).json();self.assertEqual(row['data_status']['state'],'loading')
        with self.app.state.hub.db() as db:
            db.execute('UPDATE video_cases SET transcript=?,human=?,ai=? WHERE id=?',('long'*2000,json.dumps({'transcript_zh':'HUMAN-LONG'}),json.dumps({'fields':{'transcript_en':'AI-LONG'}}),cid))
        text=self.a.get(self.base).text
        self.assertNotIn('HUMAN-LONG',text);self.assertNotIn('AI-LONG',text);self.assertNotIn('longlonglong',text)
        row=self.a.get(self.base+'/'+cid).json();self.assertIn('commercial',row);self.assertEqual(row['human']['transcript_zh'],'HUMAN-LONG')

if __name__=='__main__':unittest.main()
