"""Isolated self-operated goods API tests (no real account, worker or provider traffic)."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app, password_hash
from own_goods import PREFIX

BASE = 'http://127.0.0.1:8765'
HEADERS = {'X-Hub-Request':'1','Origin':BASE}
PROFILE = dict(name='样例窄水槽收纳架',shop='隔离测试店',market='US',url='https://shop.example.test/products/rack',sku='S-1')
CASE = 'fixture-case'
VIDEO = 'https://www.tiktok.com/@fixture/video/123456789'


def fixture(directory):
    app=create_app(directory,worker=False)
    hub=app.state.hub
    # Use the real registration path, so this suite fails if app wiring is removed.
    hashed=password_hash('isolated-fixture-password')
    with hub.db() as db:
        db.executemany('INSERT INTO users(id,username,password,role,must_change,enabled) VALUES(?,?,?,?,?,?)',
                       [(n,n,hashed,r,c,e) for n,r,c,e in [('fixture_a','member',0,1),('fixture_b','member',0,1),('fixture_admin','admin',0,1),('fixture_initial','member',1,1)]])
        db.execute('''INSERT INTO video_cases(id,canonical,platform,video,handle,url,source,created_by,updated_by,created,updated)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(CASE,'tiktok:123456789','TikTok','123456789','fixture',VIDEO,
                      json.dumps({'title':'窄水槽空间案例','views':0,'collected':1}), 'fixture_a','fixture_a',1,1))
        db.execute('INSERT INTO video_case_members VALUES(?,?,?)',(CASE,'fixture_a',1))
        db.execute('INSERT INTO intel_goods VALUES(?,?,?,?)',('fixture_comp','同场景竞品','shop_comp','竞品测试店'))
    return app


class OwnGoodsTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{'HUB_ORIGIN':BASE});env.start();self.addCleanup(env.stop)
        self.app=fixture(tmp.name)
        self.a,self.b,self.admin,self.anon,self.initial=[TestClient(self.app,base_url=BASE) for _ in range(5)]
        for client in (self.a,self.b,self.admin,self.anon,self.initial):self.addCleanup(client.close)
        for client,name in [(self.a,'fixture_a'),(self.b,'fixture_b'),(self.admin,'fixture_admin'),(self.initial,'fixture_initial')]:
            r=client.post('/api/login',headers=HEADERS,json={'username':name,'password':'isolated-fixture-password'})
            self.assertEqual(r.status_code,200,r.text)

    def post(self,p='',client=None,status=200,**data):
        r=(client or self.a).post(PREFIX+p,headers=HEADERS,json=data)
        self.assertEqual(r.status_code,status,r.text)
        return r.json()

    def dossier(self):return '/'+self.post(**PROFILE)['id']

    def test_team_auth_csrf_and_edit_revision(self):
        self.assertEqual(self.anon.get(PREFIX+'/available').json(),{'available':True,'listing_cover_lookup':True})
        self.assertEqual(self.anon.get(PREFIX).status_code,401)
        self.assertEqual(self.initial.get(PREFIX).status_code,403)
        self.assertEqual(self.a.post(PREFIX,json=PROFILE).status_code,403)
        p=self.dossier();gid=p[1:]
        self.post(status=409,**PROFILE)
        self.post(client=self.b,status=403,id=gid,revision=1,**PROFILE)
        self.post(client=self.admin,id=gid,revision=1,**{**PROFILE,'sku':'S-2'})
        self.post(status=409,id=gid,revision=1,**PROFILE)
        self.assertEqual(self.b.get(PREFIX+p).json()['sku'],'S-2')
        self.assertFalse(self.b.get(PREFIX+p).json()['can_edit'])
        self.assertEqual(self.a.get(PREFIX,params={'q':'%'}).json()['total'],0)
        self.assertEqual(self.a.get(PREFIX,params={'q':'S-2'}).json()['total'],1)

    def test_cover_and_report_change_notifications(self):
        from io import BytesIO
        from PIL import Image
        path=PREFIX+self.dossier()
        cover=path+'/cover'
        stamp=path+'/research/stamp'
        self.assertEqual(self.anon.get(stamp).status_code,401)
        before=self.a.get(stamp).raise_for_status().json()['stamp']
        with self.app.state.hub.db() as db:
            db.execute("UPDATE video_cases SET updated=updated+1 WHERE id=?",(CASE,))
        after=self.a.get(stamp).raise_for_status().json()['stamp']
        self.assertGreater(after,before)
        self.assertEqual(self.b.get(stamp).json()['stamp'],after)
        self.assertEqual(self.b.post(cover,headers=HEADERS,content=b'bad').status_code,403)
        self.assertEqual(self.a.post(cover,headers=HEADERS,content=b'bad').status_code,400)
        img=BytesIO()
        Image.new('RGB',(800,400)).save(img,'PNG')
        saved=self.a.post(cover,headers=HEADERS,content=img.getvalue()).raise_for_status().json()
        self.assertEqual(self.a.get(path).json()['cover_url'],saved['cover_url'])
        self.assertEqual(self.anon.get(cover).status_code,401)
        received=self.b.get(saved['cover_url']).raise_for_status()
        self.assertEqual(received.headers['content-type'],'image/webp')
        with Image.open(BytesIO(received.content)) as result:
            self.assertEqual(result.size,(560,280))

    def test_tag_review_preserves_decisions_and_checks_object(self):
        path=self.dossier()
        target='/tag-review/goods'+path
        row=self.a.get(PREFIX+target).json()['tags'][0]
        review=dict(kind=row['kind'],label=row['label'],decision='rejected')
        self.post(target,client=self.b,status=403,**review)
        self.post(target,status=409,**{**review,'label':'不存在'})
        self.post(target,**review)
        self.assertEqual(self.a.get(PREFIX+path).json()['tag_profile']['tags'][0]['decision'],'rejected')
        self.post(target,**{**review,'decision':'pending'})
        self.assertEqual(self.a.get(PREFIX+target).json()['tags'][0]['decision'],'pending')
        with self.app.state.hub.db() as db:
            db.execute('UPDATE video_cases SET human=? WHERE id=?',(json.dumps({'tag_groups':{'format':['前后对比']}}), CASE))
        casepath='/tag-review/case/'+CASE
        result=self.post(casepath,client=self.b,kind='内容玩法',label='前后对比',decision='confirmed')
        self.assertEqual(result['tags'][0]['decision'],'confirmed')
        self.assertIn('人工',result['tags'][0]['source'])
        with self.app.state.hub.db() as db:
            db.execute('UPDATE video_cases SET removed_at=2 WHERE id=?',(CASE,))
        self.assertEqual(self.a.get(PREFIX+casepath).status_code,404)

    def test_reference_integrity_and_zero_case_views(self):
        p=self.dossier(); lp=p+'/links'
        matches=self.b.get(PREFIX+'/references',params={'kind':'case','q':'窄水槽'}).json()['items']
        self.assertEqual([m['id'] for m in matches],[CASE])
        self.post(lp,kind='case',ref='not-found',relation='analogy',status=404)
        self.post(lp,kind='case',ref=CASE,relation='analogy')
        self.post(lp,kind='case',ref=CASE,relation='analogy')
        self.post(lp,kind='competitor',ref='fixture_comp',relation='similar')
        self.post(lp,client=self.b,kind='case',ref=CASE,remove=True,status=403)
        d=self.a.get(PREFIX+p).json();self.assertEqual(len(d['links']),2);self.assertEqual(d['topics'],[])
        case=next(x for x in d['links'] if x['kind']=='case')
        self.assertEqual(next(m for m in case['metrics'] if m['key']=='views')['value'],0)
        self.assertTrue(next(m for m in case['metrics'] if m['key']=='gmv')['missing'])
        with self.app.state.hub.db() as db:
            db.execute('UPDATE video_cases SET removed_at=2 WHERE id=?',(CASE,))
            self.assertEqual(db.execute('SELECT count(*) FROM video_case_jobs').fetchone()[0],0)
        self.assertEqual(self.a.get(PREFIX+'/references',params={'kind':'case','q':'窄水槽'}).json()['items'],[])
        self.assertFalse(next(x for x in self.a.get(PREFIX+p).json()['links'] if x['kind']=='case')['available'])

    def test_evidence_progress_provenance_and_removal(self):
        p=self.dossier(); claim='部分用户关心安装尺寸'
        tid=self.post(p+'/topics',claim=claim)['id'];self.assertEqual(self.post(p+'/topics',claim=claim)['id'],tid)
        ep=p+'/topics/'+tid+'/evidence'
        def topic():return self.a.get(PREFIX+p).json()['topics'][0]
        self.assertEqual(topic()['status'],'证据不足')
        e=dict(kind='comment',side='support',relation='analogy',quote='我的水槽只有 28 厘米',observed='2026-10-19',sample='US，公开评论前两页，按最新排序，非全量',source_group='@fixture',source_url=VIDEO+'?tracking=1')
        one=self.post(ep,**e)
        self.assertEqual(one,self.post(ep,**{**e,'source_url':'https://m.tiktok.com/@other/video/123456789?tracking=2'}) )
        self.assertEqual(topic()['status'],'初步线索')
        self.post(ep,**{**e,'kind':'video','source_group':'聚合工具镜像','quote':'视频中显示尺寸说明'})
        self.assertEqual(topic()['status'],'初步线索')
        second=dict(e,kind='review',quote='希望写清楚宽度',source_url='https://shop.example.test/reviews/42',source_group='店铺评价 #42',sample_hits=1,sample_total=20)
        self.post(ep,**second)
        self.assertEqual(topic()['status'],'多角度支持');self.assertNotIn('evidence',topic())
        counter=self.post(ep,client=self.b,**dict(second,side='counter',quote='这批已查评价没有提及尺寸',sample_hits=0))['id']
        self.assertEqual(topic()['status'],'证据有分歧')
        items=self.b.get(PREFIX+ep).json()['items']; by_id={x['id']:x for x in items}
        self.assertEqual(by_id[one['id']]['sample_total'],None)
        self.assertEqual(by_id[counter]['sample_hits'],0)
        self.assertEqual(by_id[counter]['sample_total'],20)
        self.assertFalse(by_id[one['id']]['can_edit'])
        self.post(ep,id=counter,remove=True,status=403)
        self.post(ep,id=counter,remove=True,client=self.b)
        self.assertEqual(topic()['status'],'多角度支持')
        self.assertEqual(self.b.get(PREFIX+'/missing/topics/'+tid+'/evidence').status_code,404)

    def test_validation_of_evidence(self):
        p=self.dossier();tid=self.post(p+'/topics',claim='判断')['id'];ep=p+'/topics/'+tid+'/evidence'
        e=dict(kind='comment',side='support',relation='same',quote='原话',observed='2026-10-19',sample='指定范围',source_group='测试来源',source_url=VIDEO)
        for change in ({'sample_hits':0},{'sample_hits':True,'sample_total':3},{'sample_hits':6,'sample_total':5},
                       {'sample_hits':0,'sample_total':0},{'source_url':'https://name:secret@example.test'},{'observed':'2026-02-29'},
                       {'kind':'own','relation':'self','source_url':''},{'kind':'search','sample_total':10,'sample_hits':2}):
            with self.subTest(change=change):self.post(ep,status=400,**{**e,**change})
        self.post(ep,**dict(e,kind='own',relation='self',side='context',source_url=''))
        self.assertEqual(self.a.get(PREFIX+p).json()['topics'][0]['status'],'证据不足')
