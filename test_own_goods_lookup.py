"""Authenticated product-link workflow with isolated SQLite and no provider traffic."""
import json
import os
import socket
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import Mock, patch

from PIL import Image

import httpx
from fastapi.testclient import TestClient

import tiktok_shop_link as shop
from kalodata_integration import QueryError
from own_goods import PREFIX
from test_own_goods import BASE, HEADERS, PROFILE, fixture
from test_own_goods_research import add_case

PID = '1720000000000000101'
OTHER = '1720000000000000102'
DIRECT = f'https://www.tiktok.com/view/product/{PID}'
SHORT = 'https://www.tiktok.com/t/ExampleFixture/'
REPLY = {'product_id': PID, 'region': 'US', 'product_name': 'Hand Garden Cultivator',
         'product_description': [{'sub': [{'t': 'Outdoor soils.'}, {'t': '<b>Carrying handle</b> https://example.test/?token=fixture'}]}],
         'product_shop_name': 'Fixture listing seller', 'master_image_url': 'https://example.test/not-downloaded'}
IMAGE_URL = 'https://p16-oec-ttp.tiktokcdn-us.com/fixture-product.png?sig=synthetic-only'


def fixture_image(color='#3d606e'):
    buffer = BytesIO()
    Image.new('RGB', (840, 630), color).save(buffer, 'PNG')
    return buffer.getvalue()


class RedirectTests(unittest.TestCase):
    def test_full_links_are_local_and_preserve_exact_id(self):
        with patch.object(shop, '_redirect') as redirect:
            for path in (f'/us/pdp/hand-garden-cultivator/{PID}', f'/shop/pdp/{PID}', f'/view/product/{PID}'):
                canonical = f'https://www.tiktok.com{path}?region=US'
                self.assertEqual(shop.resolve(canonical+'&campaign=fixture#suffix', 'US'), (canonical, PID))
            self.assertEqual(shop.listing_parts(f'https://shop.tiktok.com/us/pdp/松土器/{PID}', 'US'), ('松土器', PID))
            redirect.assert_not_called()

    def test_short_links_follow_only_validated_redirects(self):
        values = ['/t/StillFixture/', f'//shop.tiktok.com/us/pdp/{PID}?tracking=fixture']
        with patch.object(shop, '_redirect', side_effect=values) as redirect:
            self.assertEqual(shop.resolve('https://vm.tiktok.com/OneFixture/?tracking=discard', 'US'),
                             (f'https://shop.tiktok.com/us/pdp/{PID}', PID))
            self.assertEqual([c.args[0].geturl() for c in redirect.call_args_list],
                             ['https://vm.tiktok.com/OneFixture/', 'https://vm.tiktok.com/t/StillFixture/'])

    def test_refuses_non_product_and_other_market(self):
        urls = ['http://www.tiktok.com/t/Test/', 'https://www.tiktok.com:444/t/Test/',
                'https://example.test/t/Test/', 'https://www.tiktok.com/@seller/video/123456789?product_id='+PID,
                'https://www.tiktok.com/shop?product_id='+PID, DIRECT+'?region=GB', DIRECT+'?region=US&region=GB',
                f'https://www.tiktok.com/uk/pdp/{PID}']
        with patch.object(shop, '_redirect') as redirect:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(shop.LinkError):
                    shop.resolve(url, 'US')
            redirect.assert_not_called()
        for url in (urls[2], urls[3], urls[-1], 'https://www.tiktok.com/captcha'):
            with patch.object(shop, '_redirect', return_value=url) as redirect, self.assertRaises(shop.LinkError):
                shop.resolve(SHORT, 'US')
            redirect.assert_called_once()
        with patch.object(shop, '_redirect', return_value=SHORT) as redirect, self.assertRaises(shop.LinkError):
            shop.resolve(SHORT, 'US')
        redirect.assert_called_once()

    def test_short_dns_mixed_addresses_do_not_connect(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in ('1.1.1.1', '192.168.10.1')]
        with patch.object(shop.socket, 'getaddrinfo', return_value=addresses), patch.object(shop.http.client, 'HTTPSConnection') as conn:
            with self.assertRaisesRegex(shop.LinkError, '没有解析到公开'):
                shop.resolve(SHORT, 'US')
            conn.assert_not_called()

    def test_limits_and_challenges_do_not_parse_html(self):
        from email.message import Message
        response = Mock(status=200, headers=Message())
        with patch.object(shop, '_public_addresses', return_value=('1.1.1.1',)), patch.object(shop.http.client, 'HTTPSConnection') as factory:
            conn=factory.return_value
            conn.getresponse.return_value.__enter__.return_value=response
            with self.assertRaisesRegex(shop.LinkError, '未跳转到公开商品页'):
                shop.resolve(SHORT, 'US')
            self.assertEqual(conn.request.call_args.args, ('GET','/t/ExampleFixture/'))
            self.assertFalse({'Cookie','Authorization'} & conn.request.call_args.kwargs['headers'].keys())
            response.read.assert_not_called()
        hops = iter(f'/t/Fixture{n}/' for n in range(100))
        with patch.object(shop, '_redirect', side_effect=lambda *_: next(hops)) as redirect, self.assertRaisesRegex(shop.LinkError, '次数超限'):
            shop.resolve(SHORT, 'US')
        self.assertEqual(redirect.call_count, shop.MAX_HOPS)


class LookupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {'HUB_ORIGIN': BASE}); env.start(); self.addCleanup(env.stop)
        self.app = fixture(tmp.name)
        self.hub, self.worker = self.app.state.hub, self.app.state.own_goods_lookup
        self.a,self.b,self.admin,self.anon = [TestClient(self.app, base_url=BASE) for _ in range(4)]
        for client in (self.a,self.b,self.admin,self.anon): self.addCleanup(client.close)
        for client,name in ((self.a,'fixture_a'),(self.b,'fixture_b'),(self.admin,'fixture_admin')):
            client.post('/api/login', headers=HEADERS, json={'username':name,'password':'isolated-fixture-password'}).raise_for_status()
        self.stub = Mock()
        self.stub.secret.return_value = 'isolated-test-value'
        self.stub.post.return_value = REPLY
        service = patch.object(self.worker, 'kalodata', self.stub); service.start(); self.addCleanup(service.stop)

    def dossier(self, **fields):
        return self.a.post(PREFIX, headers=HEADERS, json=PROFILE|dict(name='样例 A', url=SHORT, facts='')|fields).raise_for_status().json()['id']

    def path(self, gid, suffix=''):
        return f'{PREFIX}/{gid}'+suffix

    def submit(self, gid, client=None, **fields):
        return (client or self.a).post(self.path(gid,'/lookup'), headers=HEADERS,
                                     json=dict(confirmed=True,revision=1,last_lookup_id='')|fields)

    def detail(self, gid, client=None):
        return (client or self.a).get(self.path(gid)).raise_for_status().json()

    def lookup(self, gid):
        return self.a.get(self.path(gid,'/lookup')).raise_for_status().json()

    def run_short(self):
        with patch.object(shop, '_redirect', return_value=DIRECT+'?opaque_tracking=fixture') as redirect:
            self.assertTrue(self.worker.tick())
        redirect.assert_called_once()

    def test_save_and_read_do_not_lookup_and_auth_is_enforced(self):
        with patch('own_goods_lookup.resolve') as resolver:
            gid = self.dossier()
            self.assertEqual(self.detail(gid)['lookup']['state'], 'idle')
            self.assertEqual(self.a.get(self.path(gid,'/research')).raise_for_status().json()['scope']['matched'],0)
            self.assertEqual(self.anon.get(self.path(gid,'/lookup')).status_code,401)
            self.assertEqual(self.submit(gid, self.b).status_code,403)
            self.assertEqual(self.submit(gid, confirmed=False).status_code,400)
            self.assertEqual(self.submit(gid, revision=2).status_code,409)
            self.assertEqual(self.a.post(self.path(gid,'/lookup'),json={'confirmed':True}).status_code,403)
            self.assertFalse(self.worker.tick())
            resolver.assert_not_called(); self.stub.post.assert_not_called()
        self.assertEqual(self.submit(self.dossier(url='https://example.test/products/'+PID)).status_code,400)
        self.assertEqual(self.submit(self.dossier(market='GB')).status_code,400)
        self.assertEqual(self.submit(self.dossier(url=DIRECT+'?region=GB')).status_code,400)

    def test_short_end_to_end_exact_identity_tags_and_matching(self):
        gid = self.dossier(sku='VERSION-X', facts='已核实尺寸 20 cm；无提手')
        stamp = self.path(gid,'/research/stamp')
        now = time.time()
        with self.hub.db() as db:
            add_case(db,'identity-sample','101000001',now,category='工具')
            add_case(db,'same-category','101000002',now,category='Garden Tiller')
            add_case(db,'other-tool','101000003',now,category='工具')
            add_case(db,'no-longer-visible','101000004',now,category='松土器',member=None)
            db.execute('INSERT INTO intel_goods VALUES(?,?,?,?)',(PID,'fixture','',''))
            db.execute('INSERT INTO intel_goods_video VALUES(?,?,?,?)',(PID,'101000001','example','Kalodata'))
        before = self.a.get(stamp).json()['stamp']
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(self.submit, gid, self.admin)
            first=self.submit(gid).raise_for_status().json()
            self.assertEqual(first['id'],future.result().raise_for_status().json()['id'])
        self.assertEqual(first['state'],'queued')
        self.assertEqual(self.a.get(stamp).json()['stamp'],before)
        self.run_short()
        self.stub.post.assert_called_once()
        endpoint, args = self.stub.post.call_args.args
        self.assertEqual(endpoint,'/product/detail')
        self.assertEqual(set(args),{'region','language','currency','date_range','product_id','need_extra','need_image'})
        self.assertEqual((args['region'],args['product_id'],args['need_image']),('US',PID,1))
        self.assertGreater(self.a.get(stamp).json()['stamp'],before)
        result = self.detail(gid)
        self.assertEqual(result['lookup']['resolved_url'], DIRECT)
        self.assertEqual(result['lookup']['source']['description'], 'Outdoor soils. Carrying handle')
        self.assertEqual(result['lookup']['state'], 'ready')
        self.assertEqual((result['sku'],result['facts'],result['revision']),('VERSION-X','已核实尺寸 20 cm；无提手',1))
        self.assertFalse(result['cover_url'])
        self.assertNotIn('带提手', [x['label'] for x in result['tag_profile']['tags']])
        fine = result['tag_profile']['tags'][0]
        self.assertEqual(fine['label'],'松土器')
        self.assertIn('Kalodata 商品名称',fine['source']); self.assertIn(PID,fine['source'])
        listed = self.a.get(PREFIX).json()['items'][0]
        self.assertEqual(listed['tag_profile']['category'],'松土器')
        report = self.a.get(self.path(gid,'/research')).raise_for_status().json()
        self.assertEqual([(x['id'],x['match']['kind']) for x in report['cases']],
                         [('identity-sample','identity'),('same-category','category')])
        self.assertIn('不等于同款',report['cases'][1]['match']['label'])
        self.assertIn('Kalodata 商品名称',report['cases'][1]['match']['reason'])
        self.a.post(PREFIX+'/tag-review/goods/'+gid,headers=HEADERS,json={'kind':'细品类','label':'松土器','decision':'rejected'}).raise_for_status()
        self.assertEqual([x['id'] for x in self.a.get(self.path(gid,'/research')).json()['cases']],['identity-sample'])
        self.assertEqual(self.submit(gid,last_lookup_id=first['id']).json()['id'],first['id'])
        self.assertFalse(self.worker.tick()); self.stub.post.assert_called_once()

    def test_exact_market_cache_reuses_without_credential_or_transport(self):
        gid = self.dossier(url=DIRECT)
        end = (datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat()
        with self.hub.db() as db:
            db.execute('INSERT INTO goods_details VALUES(?,?,?)',('shop',PID,json.dumps(dict(REPLY,end=end))))
        self.stub.secret.return_value = ''
        self.submit(gid).raise_for_status()
        self.assertTrue(self.worker.tick())
        d = self.lookup(gid)
        self.assertEqual((d['state'],d['reused'],d['source']['basis']),('ready',1,'existing_detail_cache'))
        self.assertNotIn('master_image_url',d['source'])
        self.stub.post.assert_not_called()

    def test_listing_cover_commit_auth_and_reuse(self):
        gid = self.dossier(url=DIRECT)
        self.stub.post.return_value = dict(REPLY, master_image_url=IMAGE_URL)
        first = self.submit(gid).raise_for_status().json()

        def download(url, *, product=False):
            self.assertEqual((url,product),(IMAGE_URL,True))
            current = self.lookup(gid)
            self.assertEqual((current['state'],current['image_state']),('ready','checking'))
            self.assertEqual(self.detail(gid)['tag_profile']['category'],'松土器')
            self.assertFalse(current['cover_url'])
            self.assertFalse(current['can_lookup'])
            return fixture_image()

        with patch('safe_cover.fetch', side_effect=download) as fetch:
            self.assertTrue(self.worker.tick())
            gid2 = self.dossier()
            self.submit(gid2).raise_for_status()
            self.run_short()
        fetch.assert_called_once_with(IMAGE_URL,product=True)
        self.stub.post.assert_called_once()
        d = self.detail(gid)
        cover = d['cover_url']
        self.assertEqual((d['lookup']['image_state'],d['cover_source']),('ready','listing'))
        self.assertTrue(d['cover_observed'] >= d['lookup']['observed'])
        self.assertEqual(d['lookup']['cover_url'],cover)
        self.assertNotIn('synthetic-only',json.dumps(d))
        self.assertEqual(self.anon.get(cover).status_code,401)
        response = self.b.get(cover).raise_for_status()
        self.assertEqual(response.headers['content-type'],'image/webp')
        self.assertEqual(response.headers['cache-control'],'no-store')
        with Image.open(BytesIO(response.content)) as image:
            self.assertEqual((image.format,image.size),('WEBP',(560,420)))
        self.assertEqual(self.a.get(self.detail(gid2)['cover_url']).content,response.content)
        for entry in self.a.get(PREFIX).json()['items']:
            self.assertEqual(entry['cover_source'],'listing')
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM own_goods_listing_images').fetchone()[0],1)
            self.assertNotIn('synthetic-only',db.execute('SELECT metadata FROM own_goods_lookup WHERE id=?',(first['id'],)).fetchone()[0])
        self.assertEqual(self.submit(gid,last_lookup_id=first['id']).json()['id'],first['id'])
        self.assertFalse(self.worker.tick())

    def test_image_transport_diagnostics_preserve_text_without_storing_addresses(self):
        from safe_cover import CoverFetchError
        gid = self.dossier(url=DIRECT)
        self.stub.post.return_value = dict(REPLY, master_image_url=IMAGE_URL)
        first = self.submit(gid).raise_for_status().json()
        with patch('safe_cover.fetch',side_effect=CoverFetchError('CdnHttpStatus',IMAGE_URL,403)) as fetch:
            self.assertTrue(self.worker.tick())
        fetch.assert_called_once_with(IMAGE_URL,product=True)
        d = self.lookup(gid)
        self.assertEqual((d['state'],d['image_state'],d['source']['name']),('ready','unavailable','Hand Garden Cultivator'))
        with self.hub.db() as db:
            recorded=db.execute("SELECT outcome,error_type,http_status FROM task_feedback WHERE task=? AND stage='shop_listing_image'",(first['id'],)).fetchall()
            self.assertEqual([tuple(r) for r in recorded],[('attention','CdnHttpStatus',403)])
            self.assertNotIn('synthetic-only', '\n'.join(db.iterdump()))
        self.assertFalse(self.worker.tick())
        self.stub.post.assert_called_once()

    def test_image_only_exact_reply_and_fresh_competitor_cache(self):
        gid = self.dossier(url=DIRECT)
        end = (datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat()
        self.stub.secret.return_value = ''
        shop_url = IMAGE_URL.replace('p16-oec-ttp.tiktokcdn-us.com','p16-oec-sg.ibyteimg.com')
        with self.hub.db() as db:
            db.execute('INSERT INTO goods_details VALUES(?,?,?)',('shop',PID,json.dumps({'end':end,'master_image_url':shop_url})))
        self.submit(gid).raise_for_status()
        with patch('safe_cover.fetch',return_value=fixture_image()) as fetch:
            self.assertTrue(self.worker.tick())
        fetch.assert_called_once_with(shop_url,product=True)
        self.assertEqual((self.lookup(gid)['reused'],self.lookup(gid)['cover_source']),(1,'listing'))
        self.stub.post.assert_not_called()
        other = self.dossier(url=DIRECT.replace(PID,OTHER))
        self.stub.secret.return_value = 'isolated-test-value'
        self.stub.post.return_value = {'product_id':OTHER,'region':'US','master_image_url':IMAGE_URL}
        self.submit(other).raise_for_status()
        with patch('safe_cover.fetch',return_value=fixture_image()):
            self.assertTrue(self.worker.tick())
        self.assertEqual(self.lookup(other)['cover_source'],'listing')
        self.assertFalse(self.detail(other)['tag_profile']['category'])
        self.stub.post.assert_called_once()

    def test_image_failure_is_partial_not_a_second_paid_call(self):
        gid = self.dossier(url=DIRECT)
        self.stub.post.return_value = dict(REPLY, master_image_url=IMAGE_URL)
        first = self.submit(gid).raise_for_status().json()
        with patch('safe_cover.fetch',return_value=b'not an image') as fetch:
            self.assertTrue(self.worker.tick())
        fetch.assert_called_once()
        d = self.lookup(gid)
        self.assertEqual((d['state'],d['image_state'],d['cover_source']),('ready','unavailable',''))
        self.assertEqual(d['source']['name'],'Hand Garden Cultivator')
        self.assertEqual(self.a.get(self.path(gid,'/cover')).status_code,404)
        self.assertEqual(self.submit(gid,last_lookup_id=first['id']).json()['id'],first['id'])
        other = self.dossier()
        self.submit(other).raise_for_status()
        with patch('safe_cover.fetch') as fetch:
            self.run_short()
            fetch.assert_not_called()
        self.assertEqual(self.lookup(other)['image_state'],'unavailable')
        self.stub.post.assert_called_once()

    def test_manual_cover_wins_and_follows_dossier_not_listing(self):
        gid = self.dossier(url=DIRECT)
        manual = self.a.post(self.path(gid,'/cover'),headers=HEADERS,content=fixture_image('#ad7026')).raise_for_status().json()
        before = self.a.get(manual['cover_url']).content
        self.stub.post.return_value = dict(REPLY,master_image_url=IMAGE_URL)
        self.submit(gid).raise_for_status()
        with patch('safe_cover.fetch',return_value=fixture_image()):
            self.assertTrue(self.worker.tick())
        d = self.lookup(gid)
        self.assertEqual((d['image_state'],d['cover_source']),('ready','manual'))
        linked = self.dossier()
        self.submit(linked).raise_for_status(); self.run_short()
        old = self.detail(linked)['cover_url']
        self.assertNotEqual(self.a.get(old).content,before)
        for current,target in ((linked,OTHER),(gid,'1720000000000000103')):
            self.a.post(PREFIX,headers=HEADERS,json=PROFILE|{'id':current,'revision':1,'url':DIRECT.replace(PID,target)}).raise_for_status()
        self.assertFalse(self.detail(linked)['cover_url'])
        self.assertEqual(self.a.get(old).status_code,404)
        self.assertEqual(self.detail(gid)['cover_source'],'manual')
        self.assertEqual(self.a.get(manual['cover_url']).content,before)
        self.stub.post.assert_called_once()

    def test_cover_is_not_committed_after_link_change_during_download(self):
        gid = self.dossier(url=DIRECT)
        first = self.submit(gid).raise_for_status().json()
        self.stub.post.return_value = dict(REPLY,master_image_url=IMAGE_URL)
        def download(*args, **kwargs):
            self.a.post(PREFIX,headers=HEADERS,json=PROFILE|{'id':gid,'revision':1,'url':DIRECT.replace(PID,OTHER)}).raise_for_status()
            return fixture_image()
        with patch('safe_cover.fetch',side_effect=download):
            self.assertTrue(self.worker.tick())
        self.assertEqual(self.lookup(gid)['state'],'idle')
        self.assertFalse(self.detail(gid)['cover_url'])
        with self.hub.db() as db:
            self.assertEqual(tuple(db.execute('SELECT state,image_state FROM own_goods_lookup WHERE id=?',(first['id'],)).fetchone()),('ready','unavailable'))
            self.assertEqual(db.execute('SELECT count(*) FROM own_goods_listing_images').fetchone()[0],0)
        self.stub.post.assert_called_once()

    def test_recover_image_phase_without_replay_or_release_during_download(self):
        from inspect_cases_deploy import work
        gid = self.dossier(url=DIRECT)
        first = self.submit(gid).raise_for_status().json()
        with self.hub.db() as db:
            db.execute("UPDATE own_goods_lookup SET state='ready',image_state='checking',product_id=?,resolved_url=? WHERE id=?",(PID,DIRECT,first['id']))
            self.assertEqual(work(db,'local')['own_goods_lookup'],1)
        with patch('safe_cover.fetch') as fetch:
            self.worker.recover()
            self.assertFalse(self.worker.tick())
            fetch.assert_not_called()
        self.assertEqual((self.lookup(gid)['state'],self.lookup(gid)['image_state']),('ready','unavailable'))
        self.stub.post.assert_not_called()
        with self.hub.db() as db:
            self.assertEqual(work(db,'local')['own_goods_lookup'],0)

    def test_saved_exact_details_are_reused_across_two_links(self):
        gid = self.dossier(url=DIRECT)
        self.submit(gid).raise_for_status()
        self.assertTrue(self.worker.tick())
        gid2 = self.dossier()
        self.submit(gid2).raise_for_status()
        self.run_short()
        self.assertEqual(self.lookup(gid2)['state'],'ready')
        self.assertEqual(self.lookup(gid)['observed'],self.lookup(gid2)['observed'])
        self.stub.post.assert_called_once()

    def test_stale_cache_or_other_market_is_not_reused(self):
        gid = self.dossier(url=DIRECT)
        with self.hub.db() as db:
            db.execute('INSERT INTO goods_details VALUES(?,?,?)',('shop',PID,'{"end":"2000-01-01","product_name":"Laundry Hamper"}'))
        self.submit(gid).raise_for_status()
        self.assertTrue(self.worker.tick())
        self.stub.post.assert_called_once()
        self.assertEqual(self.detail(gid)['tag_profile']['category'],'松土器')

    def test_bad_short_link_never_calls_provider(self):
        gid = self.dossier()
        first = self.submit(gid).raise_for_status().json()
        with patch.object(shop,'_redirect',return_value='https://www.tiktok.com/@fixture/video/101000010'):
            self.assertTrue(self.worker.tick())
        d = self.lookup(gid)
        self.assertEqual(d['state'],'failed'); self.assertIn('未发起 Kalodata',d['error'])
        self.stub.secret.assert_not_called();self.stub.post.assert_not_called()
        e = '/api/intelligence/exceptions'
        self.assertIn(first['id'],[r['id'] for r in self.a.get(e).json()['items']])
        self.assertNotIn(first['id'],[r['id'] for r in self.b.get(e).json()['items']])
        self.assertEqual(self.b.get(f'{e}/own_goods_lookup/{first["id"]}/feedback').status_code,404)
        timeline=self.admin.get(f'{e}/own_goods_lookup/{first["id"]}/feedback').raise_for_status().json()['items']
        self.assertEqual(timeline[0]['stage'],'识别 TikTok Shop 商品链接')

    def test_mismatches_or_missing_metadata_do_not_adopt_provider_tags(self):
        for i, reply in enumerate(({'product_name':'Garden Tiller','master_image_url':IMAGE_URL},
                                    dict(REPLY,product_id=OTHER,master_image_url=IMAGE_URL),
                                    dict(REPLY,region='GB',master_image_url=IMAGE_URL),None,{'product_id':PID})):
            pid=f'17200000000000009{i}0'
            # Use a distinct ID for each case; do not resubmit already-unusable results.
            if isinstance(reply,dict) and reply.get('product_id')==PID:
                reply=reply|{'product_id':pid}
            gid=self.dossier(url=f'https://www.tiktok.com/view/product/{pid}')
            self.stub.post.return_value=reply
            self.submit(gid).raise_for_status()
            self.assertTrue(self.worker.tick())
            d=self.detail(gid)
            self.assertEqual(d['lookup']['state'],'attention')
            self.assertFalse(d['lookup']['source']);self.assertFalse(d['tag_profile']['category'])
        self.assertEqual(self.stub.post.call_count,5)

    def test_unknown_not_replayed_even_via_another_dossier(self):
        gid=self.dossier(url=DIRECT)
        self.stub.post.side_effect=QueryError('raw provider body may contain fixture-private text')
        first=self.submit(gid).raise_for_status().json()
        self.assertTrue(self.worker.tick())
        self.assertEqual(self.lookup(gid)['state'],'unknown')
        self.assertNotIn('fixture-private',self.lookup(gid)['error'])
        self.assertEqual(self.submit(gid,last_lookup_id=first['id']).json()['id'],first['id'])
        other=self.dossier()
        self.submit(other).raise_for_status()
        self.run_short()
        self.assertEqual(self.lookup(other)['state'],'attention')
        self.assertFalse(self.lookup(other)['can_lookup'])
        self.assertFalse(self.worker.tick());self.stub.post.assert_called_once()

    def test_recovery_never_replays_a_claimed_charge(self):
        gid=self.dossier(url=DIRECT)
        first=self.submit(gid).raise_for_status().json()
        with self.hub.db() as db:
            db.execute("UPDATE own_goods_lookup SET state='fetching',product_id=?,resolved_url=? WHERE id=?",(PID,DIRECT,first['id']))
        self.worker.recover()
        self.assertEqual(self.lookup(gid)['state'],'unknown')
        self.assertFalse(self.worker.tick());self.stub.post.assert_not_called()

    def test_credit_rejection_retry_requires_new_confirmation_and_seen_attempt(self):
        gid=self.dossier(url=DIRECT)
        first=self.submit(gid).raise_for_status().json()
        self.stub.post.side_effect=QueryError('never show upstream text',code=2016)
        self.assertTrue(self.worker.tick())
        d=self.lookup(gid)
        self.assertEqual((d['state'],d['error_code']),('failed','2016'))
        self.assertIn('余额不足',d['error'])
        self.assertEqual(self.submit(gid).json()['id'],first['id'])
        self.assertFalse(self.worker.tick())
        second=self.submit(gid,last_lookup_id=first['id']).raise_for_status().json()
        self.assertNotEqual(first['id'],second['id'])
        self.stub.post.side_effect=None
        self.assertTrue(self.worker.tick());self.assertEqual(self.lookup(gid)['state'],'ready')
        self.assertEqual(self.stub.post.call_count,2)

    def test_human_override_and_confirmed_tag_are_not_replaced(self):
        gid=self.dossier(name='样例脏衣篮',facts='已核实宽度 35 cm')
        path=PREFIX+'/tag-review/goods/'+gid
        self.a.post(path,headers=HEADERS,json={'kind':'细品类','label':'脏衣篮','decision':'confirmed'}).raise_for_status()
        self.submit(gid).raise_for_status();self.run_short()
        d=self.detail(gid)
        self.assertEqual(d['tag_profile']['category'],'脏衣篮')
        self.assertEqual(d['tag_profile']['tags'][0]['decision'],'confirmed')
        self.assertIn('保留人工结论',d['tag_profile']['notice'])
        self.a.post(PREFIX,headers=HEADERS,json=PROFILE|{'id':gid,'revision':1,'name':d['name'],'facts':d['facts'],
                                                        'url':SHORT,'category':'门后收纳袋'}).raise_for_status()
        self.assertEqual(self.detail(gid)['tag_profile']['category'],'门后收纳袋')
        self.stub.post.assert_called_once()

    def test_unreviewed_conflict_and_link_changes_are_safe(self):
        gid=self.dossier(url=DIRECT,name='样例脏衣篮')
        self.submit(gid).raise_for_status()
        self.assertTrue(self.worker.tick())
        d=self.detail(gid)
        self.assertFalse(d['tag_profile']['category']);self.assertIn('核对',d['tag_profile']['notice'])
        url=DIRECT.replace(PID,OTHER)
        self.a.post(PREFIX,headers=HEADERS,json=PROFILE|{'id':gid,'revision':1,'url':url}).raise_for_status()
        self.assertEqual(self.lookup(gid)['state'],'idle')
        self.assertEqual(self.detail(gid)['tag_profile']['product_id'],OTHER)
        self.submit(gid,revision=2).raise_for_status()
        self.a.post(PREFIX,headers=HEADERS,json=PROFILE|{'id':gid,'revision':2,'url':DIRECT}).raise_for_status()
        self.assertTrue(self.worker.tick())
        self.stub.post.assert_called_once()
        self.assertEqual(self.lookup(gid)['state'],'ready')

    def test_valid_product_identity_does_not_invent_a_category(self):
        gid=self.dossier(url=DIRECT)
        self.stub.post.return_value={'product_id':PID,'product_name':'Premium model X','category_name':'家居园艺',
                                     'product_description':'Compare to a laundry hamper.'}
        self.submit(gid).raise_for_status()
        self.assertTrue(self.worker.tick())
        d=self.detail(gid)
        self.assertEqual((d['lookup']['state'],d['tag_profile']['product_id']),('ready',PID))
        self.assertFalse(d['tag_profile']['category'])
        self.stub.post.assert_called_once()

    def test_missing_key_keeps_parsed_identity_without_paid_call(self):
        gid=self.dossier(url=DIRECT)
        self.stub.secret.return_value=''
        self.submit(gid).raise_for_status()
        self.assertTrue(self.worker.tick())
        d=self.detail(gid)
        self.assertEqual((d['lookup']['state'],d['tag_profile']['product_id']),('failed',PID))
        self.assertTrue(d['lookup']['can_lookup'])
        self.assertIn('未发起查询',d['lookup']['error'])
        self.stub.post.assert_not_called()

    def test_not_found_does_not_retry_or_substitute(self):
        gid=self.dossier(url=DIRECT)
        self.stub.post.side_effect=QueryError('provider fixture',http_status=404)
        self.submit(gid).raise_for_status()
        self.assertTrue(self.worker.tick())
        d=self.lookup(gid)
        self.assertEqual(d['state'],'attention'); self.assertIn('未替换为相似商品',d['error'])
        self.assertFalse(d['can_lookup'])
        self.assertFalse(self.worker.tick());self.stub.post.assert_called_once()

    def test_real_transport_contract_with_mocked_http(self):
        gid=self.dossier(url=DIRECT)
        service=self.app.state.kalodata
        sent=[]
        def respond(request):
            sent.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200,json={'success':True,'data':{'data':[REPLY]}})
        synthetic=httpx.Client(transport=httpx.MockTransport(respond))
        self.submit(gid).raise_for_status()
        with patch.object(self.worker,'kalodata',service), patch.object(service,'secret',return_value='isolated-test-value'), \
                patch('kalodata_integration.httpx.Client',return_value=synthetic) as client:
            self.assertTrue(self.worker.tick())
        client.assert_called_once()
        self.assertFalse(client.call_args.kwargs['follow_redirects'])
        self.assertEqual(len(sent),1)
        self.assertTrue(sent[0][0].endswith('/tiktok/product/detail'))
        self.assertEqual(sent[0][1]['product_id'],PID)
        self.assertEqual(self.lookup(gid)['state'],'ready')
