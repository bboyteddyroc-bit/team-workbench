"""Isolated end-to-end product evidence tests and deterministic UI fixtures."""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from comment_research import SIGNALS, pack
from own_goods import PREFIX
from product_research import build, DAY
from product_research_tags import product_profile
from test_own_goods import BASE, HEADERS, PROFILE, fixture

PRODUCT_ID='1720000000000123456'
HAMPER=dict(PROFILE,name='Basketball Hoop',shop='案例验收店',sku='',facts='',
            url='https://www.tiktok.com/us/pdp/over-the-door-laundry-hamper-with-basketball-hoop-space-saving/'+PRODUCT_ID)


def add_case(db,key,video,now,handle='example',category='脏衣篮',tags=None,fmt='实物演示',views=20000,age=15,snap=None,
             human=None,estimate=None,platform='TikTok',member='fixture_a',gone=False,transcript='Fits doors up to two inches thick. Hang it on the top of the door.'):
    snap=now if snap is None else snap
    url=f'https://www.tiktok.com/@{handle}/video/{video}'
    source={'title':f'{handle} · 门后收纳实测','views':views,'likes':1000,'collects':320,'comments':64,'collected':snap,
            'origin':'Apify 单视频采集','published':now-age*DAY}
    if estimate:source['kalodata']=estimate
    ai={'generated_at':now-500,'fields':{'product_category':category,'tag_groups':{'product':tags or []},'content_type':fmt,
        'summary':'视频展示门后挂装、投衣和取出衣物。','audience_scenario':'小空间住户整理衣物'},'evidence':{'summary':'开头 3 秒演示挂在门背面。'}}
    db.execute('''INSERT INTO video_cases(id,canonical,platform,video,handle,url,source,human,ai,transcript,transcript_source,created_by,updated_by,created,updated,removed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(key,f'{platform.lower()}:{video}',platform,video,handle,url,json.dumps(source),json.dumps(human or {}),json.dumps(ai),
            transcript,'原口播转录','fixture_a','fixture_a',now-DAY,now,now if gone else None))
    if member:db.execute('INSERT INTO video_case_members VALUES(?,?,?)',(key,member,now-DAY))
    return url


def mark_case(db,video,url,now,legacy=False):
    rows=[{'cid':'10001','parent':'','text':'Where can I buy this for a thick door? I have been looking for a laundry bag.'},
          {'cid':'10002','parent':'','text':'I bought it yesterday for my dorm room.'},
          {'cid':'10003','parent':'','text':'Haha that basket is funny 😂'},
          {'cid':'10004','parent':'10001','text':'My old holder falls down. Shipping here is too expensive.'}]
    topics=json.dumps([{'label':'门厚是否影响安装','support':['10001'],'counter':['10002']}],ensure_ascii=False)
    db.execute("INSERT INTO comment_sample_jobs(video,url,origin,state,ai_state,created,updated,finished,topics) VALUES(?,?,'case','ready','ready',?,?,?,?)",
               (video,url,now,now,now,topics))
    db.executemany('INSERT INTO comment_sample_text VALUES(?,?,?,?,?,?,?)',[(video,r['cid'],r['parent'],r['text'],int(now-1200-i),now,i) for i,r in enumerate(rows)])
    if legacy:return
    marks={k:[] for k in SIGNALS}
    for key,label,ids in (('looking','找可挂门的收纳',[1,1]),('bought','自报为宿舍购买',[2]),('people','宿舍住户',[2]),('scene','宿舍收纳',[2]),
                          ('pain','旧架容易掉',[4]),('barrier','运费偏贵',[4]),('barrier','门厚适配疑问',[1]),('question','门厚能否安装',[1]),
                          ('buy_intent','问购买渠道与门厚',[1]),('buy_intent','问适配门厚',[1]),('reaction','觉得有趣',[3])):
        marks[key].append({'label':label,'ids':ids})
    db.execute("INSERT INTO comment_sample_research(video,state,payload,updated) VALUES(?,'ready',?,?)",(video,json.dumps(pack(marks,rows)),now))


def estimate(start,end,units,region='US'):
    return {'provider':'Kalodata','data_type':'third_party_estimate','units':units,'collected':1,
            'gmv':82,'period_start':start,'period_end':end,'region':region,'currency':'USD','period_views':93,'likes':6,'product_count':2}


def evidence_fixture(hub,now):
    with hub.db() as db:
        url=add_case(db,'door-demo','100000001',now,'door_demo','家居收纳 / 脏衣篮 / 创意家居',['门后篮球脏衣篓'],views=40000,age=14,
                     estimate=estimate('2026-02-01','2026-02-09',3),human={'manual_views':'444','manual_metric_basis':'人工复核口径'})
        mark_case(db,'100000001',url,now)
        url=add_case(db,'dorm-demo','100000002',now,'dorm_space',fmt='使用演示',views=10000,age=22,estimate=estimate('2026-02-02','2026-02-10',0))
        mark_case(db,'100000002',url,now,legacy=True)
        add_case(db,'same-listing','100000003',now-3,'market_demo','通用',views=31000,age=50,snap=0)
        db.execute('INSERT INTO intel_goods VALUES(?,?,?,?)',(PRODUCT_ID,'同 ID · 门后脏衣篮','111','案例商店 A'))
        db.executemany('INSERT INTO intel_goods_video VALUES(?,?,?,?)',[(PRODUCT_ID,'100000003','market_demo',s) for s in ('Apify','Kalodata')])
        db.execute('INSERT INTO apify_accounts(id,owner,handle) VALUES(?,?,?)',('trend-public','fixture_a','market_demo'))
        db.execute('INSERT INTO apify_accounts(id,owner,handle) VALUES(?,?,?)',('other-monitor','fixture_b','market_demo'))
        db.executemany('INSERT INTO apify_snapshots(run,account,video,views,collected) VALUES(?,?,?,?,?)',[
            ('old','trend-public','100000003',900,now-8*DAY),('new','trend-public','100000003',1300,now-DAY),('other','other-monitor','100000003',4,now-10*DAY)])
    return 3


class ProductResearchTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{'HUB_ORIGIN':BASE});env.start();self.addCleanup(env.stop)
        self.app=fixture(tmp.name);self.hub=self.app.state.hub
        self.a,self.b,self.anon=[TestClient(self.app,base_url=BASE) for _ in range(3)]
        for c in (self.a,self.b,self.anon):self.addCleanup(c.close)
        for c,u in ((self.a,'fixture_a'),(self.b,'fixture_b')):
            c.post('/api/login',headers=HEADERS,json={'username':u,'password':'isolated-fixture-password'}).raise_for_status()
        self.now=time.time()-180
        self.gid=self.a.post(PREFIX,json=HAMPER,headers=HEADERS).raise_for_status().json()['id']
        self.path=f'{PREFIX}/{self.gid}/research'

    def report(self):return self.a.get(self.path).raise_for_status().json()

    def test_cached_product_listing_fills_missing_case_category(self):
        with self.hub.db() as db:
            add_case(db,'linked','100000041',self.now,category='家居')
            db.execute('INSERT INTO intel_goods VALUES(?,?,?,?)',('9876543','laundry hamper','123','Example'))
            db.execute('INSERT INTO intel_goods_video VALUES(?,?,?,?)',('9876543','100000041','example','Kalodata'))
        case=self.report()['cases'][0]
        self.assertEqual(case['match']['kind'],'category')
        self.assertIn('平台关联的唯一商品名称',case['match']['reason'])
        with self.hub.db() as db:
            db.execute('INSERT INTO intel_goods_video VALUES(?,?,?,?)',('7654321','100000041','example','Apify'))
        self.assertEqual(self.report()['scope']['matched'],0)

    def test_listing_claims_remain_distinct_from_team_facts(self):
        product=product_profile(dict(HAMPER,name='吸烫机',url='https://shop.tiktok.com/us/pdp/vacuum-steamer-for-clothes-1200w-power-30s-heat-up-200ml-tank/'+PRODUCT_ID))
        self.assertEqual(product['category'],'挂烫机')
        self.assertEqual({t['label'] for t in product['tags'] if t['kind']=='商品页标称'},{'标称功率 1200 W','预热时间 30 秒','水箱容量 200 mL'})

    def save_exclusion(self,id,flag,c=None,headers=HEADERS):
        return (c or self.a).post(self.path+'/exclusion',headers=headers,json={'case_id':id,'excluded':flag})

    def test_method_cards_and_cross_category_trace(self):
        tags=product_profile(HAMPER|{'facts':'带提手，不支持可折叠'})['tags']
        self.assertIn('带提手',[t['label'] for t in tags])
        self.assertNotIn('可折叠',[t['label'] for t in tags])
        with self.hub.db() as db:
            add_case(db,'cabinet-demo','100000055',self.now,category='衣柜挂袋',
                human={'opening':'用凌乱到整洁的前后对比开场','audience_scenario':'小空间洗衣房'})
        d=self.report()
        self.assertEqual(d['cases'][0]['match']['kind'],'analogy')
        self.assertEqual(d['coverage']['videos'],0)
        m=next(m for m in d['methods'] if m['label']=='凌乱到整洁')
        self.assertEqual([c['id'] for c in m['cards']],['fit','demand','scene','barrier','performance','shots'])
        shot=m['cards'][-1]['rows'][0]['evidence'][0]
        self.assertEqual(shot['case_id'],'cabinet-demo')
        self.assertIn('凌乱到整洁',shot['text'])
        self.assertEqual(self.save_exclusion('cabinet-demo',True).status_code,200)
        self.assertFalse(self.report()['methods'][0]['cases'])

    def test_hamper_name_and_market_are_not_identity(self):
        self.assertEqual(product_profile(HAMPER)['category'],'脏衣篮')
        self.assertEqual(product_profile(HAMPER|{'name':'保温杯'})['category'],'')
        self.assertEqual(product_profile(HAMPER|{'url':'https://shop.example.test/pdp/hamper/'+PRODUCT_ID})['category'],'篮球架')
        self.assertNotIn('篮球架',[t['label'] for t in product_profile(HAMPER)['tags']])
        self.assertEqual(self.a.get(PREFIX).json()['items'][0]['tag_profile']['category'],'脏衣篮')
        with self.hub.db() as db:
            add_case(db,'same-fine','100000011',self.now,category='家居收纳 / 脏衣篮 / 创意家居',tags=['门后篮球脏衣篓'])
            add_case(db,'broad','100000012',self.now,category='家居收纳 / 创意家居',tags=['收纳'])
            add_case(db,'sports','100000013',self.now,category='篮球架')
            add_case(db,'combo','100000014',self.now,category='Laundry hamper with basketball hoop')
            add_case(db,'uncertain','100000015',self.now,category='可能是脏衣篮')
            add_case(db,'cleared','100000016',self.now,human={'tag_groups':{'product':[]}})
            add_case(db,'not-member','100000017',self.now,member=None)
            add_case(db,'deleted','100000018',self.now,gone=True)
            add_case(db,'wrong-platform','100000019',self.now,platform='Instagram')
            add_case(db,'wrong-market','100000020',self.now,estimate=estimate('2026-02-01','2026-02-09',9,'GB'))
            add_case(db,'manual-not-same','100000021',self.now,category='工具')
            db.execute('INSERT INTO own_goods_links VALUES(?,?,?,?,?,?)',(self.gid,'case','manual-not-same','same','fixture_a',self.now))
            add_case(db,'product-id','100000022',self.now-DAY,category='工具')
            db.execute('INSERT INTO intel_goods VALUES(?,?,?,?)',(PRODUCT_ID,'某商品','111','某店铺'))
            db.executemany('INSERT INTO intel_goods_video VALUES(?,?,?,?)',[(PRODUCT_ID,'100000022','example',s) for s in ('Apify','Kalodata')])
        with patch('httpx.Client.send', wraps=self.a.send) as trap:
            # Only invoke the pure report using the existing DB; any HTTP call here is a fail.
            with self.hub.db() as db:
                d=build(db,dict(db.execute('SELECT * FROM own_goods').fetchone()),self.now+1)
            trap.assert_not_called()
        self.assertEqual([v['match']['kind'] for v in d['cases']],['identity','category','category','category','manual'])
        byid={v['id']:v for v in d['cases']}
        self.assertEqual(d['cases'][0]['id'],'product-id')
        self.assertIn('AI 视频分析',byid['same-fine']['match']['reason'])
        self.assertFalse(byid['wrong-market']['included'])
        self.assertFalse(byid['manual-not-same']['included'])
        self.assertEqual(self.report()['coverage']['videos'],3)
        self.assertIsNone(d['signals']['looking']['comments']['pct'])

    def test_electric_scissors_does_not_match_generic_tools(self):
        scissors=dict(HAMPER,name='电动剪刀',url='https://www.tiktok.com/us/pdp/cordless-electric-scissors-rechargeable-cutter-for-diy/1720000000000123457')
        self.assertEqual(product_profile(scissors)['category'],'电动剪刀')
        self.assertEqual(product_profile(scissors|{'name':'Cordless cutter'})['category'],'电动剪刀')
        goods=self.a.post(PREFIX,headers=HEADERS,json=scissors).raise_for_status().json()['id']
        path=f'{PREFIX}/{goods}/research'
        with self.hub.db() as db:
            add_case(db,'generic-tool','100000051',self.now,category='工具',tags=['五金工具'])
            add_case(db,'other-tool','100000052',self.now,category='吹叶机')
            db.execute('INSERT INTO intel_goods VALUES(?,?,?,?)',(PRODUCT_ID,'无关商品','111','无关商品店铺'))
            db.execute('INSERT INTO intel_goods_video VALUES(?,?,?,?)',(PRODUCT_ID,'100000052','example','Apify'))
        empty=self.a.get(path).raise_for_status().json()
        self.assertEqual(empty['profile']['category'],'电动剪刀')
        self.assertEqual(empty['cases'],[])
        self.assertIsNone(empty['signals']['looking']['comments']['pct'])
        with self.hub.db() as db:
            add_case(db,'scissors-demo','100000053',self.now,category='工具 / Cordless electric scissors')
        cases=self.a.get(path).raise_for_status().json()['cases']
        self.assertEqual([(c['id'],c['match']['kind']) for c in cases],[('scissors-demo','category')])

    def test_observed_counts_dimensions_and_comparability(self):
        evidence_fixture(self.hub,self.now)
        with self.hub.db() as db:
            # Same label from the same handle is NOT another account, and an earlier week must not be combined.
            add_case(db,'early-window','100000025',self.now,'other_week',snap=self.now-8*DAY,views=80000)
            add_case(db,'different-format','100000026',self.now,'creator_three',fmt='开箱',views=8000,age=15)
        d=self.report();c=d['coverage'];s=d['signals']
        self.assertEqual(len(d['dimensions']),8)
        self.assertEqual((c['analysed_videos'],c['sampled_videos']),(1,2))
        self.assertEqual(s['buy_intent']['comments'],{'total':3,'hits':1,'pct':33.3})
        self.assertEqual(s['barrier']['replies']['pct'],100)
        self.assertEqual(s['used']['comments']['pct'],0)
        self.assertEqual(s['question']['groups'][0]['quotes'][0]['case_id'],'door-demo')
        self.assertEqual(c['concentration'][0]['share']['total'],58000)
        self.assertEqual(c['formats'][0]['kind'],'实物 / 使用演示')
        self.assertTrue(c['formats'][0]['repeated']);self.assertEqual(c['formats'][0]['accounts']['total'],2)
        self.assertEqual(len(c['estimate_windows']),2)
        self.assertEqual(c['estimate_windows'][0]['positive'],0)
        byid={v['id']:v for v in d['cases']}
        self.assertEqual(byid['dorm-demo']['comments']['research_state'],'legacy')
        self.assertEqual(byid['same-listing']['trend']['gain'],400)
        self.assertEqual(c['fresh_growth_old']['hits'],1)
        self.assertEqual(byid['door-demo']['metrics'][0]['value'],444)
        self.assertEqual(byid['door-demo']['public'][0]['value'],40000)
        self.assertTrue(byid['door-demo']['faq'][0]['passages'])
        self.assertEqual(byid['door-demo']['comments']['topics'][0]['counter']['comments']['hits'],1)
        detail=self.a.get('/api/intelligence/comment-samples/100000001').raise_for_status().json()
        self.assertEqual(detail['research']['barrier']['replies']['hits'],1)
        self.assertEqual(detail['research']['question']['groups'][0]['ids'],['10001'])
        with self.hub.db() as db:
            db.execute("DELETE FROM comment_sample_text WHERE video='100000001' AND cid='10004'")
        self.assertEqual(self.report()['signals']['looking']['comments']['pct'],None)
        self.assertIsNone(self.a.get('/api/intelligence/comment-samples/100000001').json()['research'])

    def test_manual_control_permissions_and_visibility(self):
        evidence_fixture(self.hub,self.now)
        self.assertEqual(self.anon.get(self.path).status_code,401)
        self.assertFalse(self.b.get(self.path).json()['can_edit'])
        self.assertEqual(self.save_exclusion('door-demo',True,self.b).status_code,403)
        self.assertEqual(self.save_exclusion('door-demo',True,headers={}).status_code,403)
        self.save_exclusion('door-demo',True).raise_for_status()
        self.assertEqual(self.report()['coverage']['analysed_videos'],0)
        self.assertEqual(self.report()['excluded'][0]['id'],'door-demo')
        self.assertEqual(self.a.get('/api/intelligence/comment-samples/100000001').status_code,200)
        self.save_exclusion('door-demo',False).raise_for_status()
        self.assertEqual(self.report()['coverage']['analysed_videos'],1)
        data=dict(HAMPER,id=self.gid,revision=1)
        for invalid in ('家居','脏衣篮、篮球架','脏衣篮 篮球架'):
            self.assertEqual(self.a.post(PREFIX,json=data|{'category':invalid},headers=HEADERS).status_code,400)
        self.a.post(PREFIX,json=data|{'category':'篮球架'},headers=HEADERS).raise_for_status()
        d=self.report();self.assertEqual(d['profile']['category'],'篮球架');self.assertEqual([v['id'] for v in d['cases']],['same-listing'])
        self.a.post(PREFIX,json=data|{'revision':2,'category':''},headers=HEADERS).raise_for_status()
        self.assertEqual(self.report()['coverage']['videos'],3)
        with self.hub.db() as db:db.execute("UPDATE users SET enabled=0 WHERE id='fixture_a'")
        self.assertEqual(self.b.get(self.path).json()['coverage']['videos'],0)


if __name__=='__main__':unittest.main()
