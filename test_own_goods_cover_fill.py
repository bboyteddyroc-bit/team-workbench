"""Automatic listing thumbnails with isolated Hub, exact IDs, and no provider traffic."""
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from PIL import Image

import own_goods_cover_tasks as cover
import own_goods_erp_cover as erp
from own_goods import PREFIX
from own_goods_lookup import link_key
from safe_cover import CoverFetchError, image_url
from test_own_goods import BASE, HEADERS, PROFILE, fixture
from test_own_goods_lookup import DIRECT, IMAGE_URL, OTHER, PID, REPLY, SHORT, fixture_image
from tiktok_shop_link import LinkError

KEY = 'fixture-only-read-key'
ALT_IMAGE = 'https://p16-oec-general-useast5.ttcdn-us.com/fixture.webp'
SOURCE = PREFIX + '/cover-source'


class CoverFillTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for guard in (patch.dict(os.environ, {'HUB_ORIGIN':BASE}),
                      patch('safe_cover.fetch', side_effect=AssertionError('unexpected CDN request')),
                      patch('own_goods_cover_tasks.fetch_image', side_effect=AssertionError('unexpected ERP read')),
                      patch('own_goods_cover_tasks.resolve', side_effect=AssertionError('unexpected redirect'))):
            guard.start()
            self.addCleanup(guard.stop)
        self.app = fixture(tmp.name)
        self.hub = self.app.state.hub
        self.worker = self.app.state.own_goods_covers
        self.lookup = self.app.state.own_goods_lookup
        self.lookup.kalodata = Mock()
        self.lookup.kalodata.secret.return_value = 'mock-kalodata-only'
        self.lookup.kalodata.post.side_effect = AssertionError('unexpected Kalodata transport')
        self.a, self.admin, self.anon = [TestClient(self.app,base_url=BASE) for _ in range(3)]
        for client in (self.a,self.admin,self.anon):
            self.addCleanup(client.close)
        for client,name in ((self.a,'fixture_a'),(self.admin,'fixture_admin')):
            client.post('/api/login',headers=HEADERS,json={'username':name,'password':'isolated-fixture-password'}).raise_for_status()

    def dossier(self, url=DIRECT, **fields):
        return self.a.post(PREFIX,headers=HEADERS,json=PROFILE|{'url':url}|fields).raise_for_status().json()['id']

    def projection(self, gid):
        return self.a.get(f'{PREFIX}/{gid}/lookup').raise_for_status().json()

    def job(self, gid):
        with self.hub.db() as db:
            return dict(db.execute('SELECT * FROM own_goods_cover_jobs WHERE goods=?',(gid,)).fetchone())

    def due(self, gid):
        with self.hub.db() as db:
            db.execute('UPDATE own_goods_cover_jobs SET next_at=0 WHERE goods=?',(gid,))

    def configure(self, **opts):
        data = {'expected_updated':None, 'enabled':True,'key':KEY}|opts
        return self.admin.post(SOURCE,headers=HEADERS,json=data).raise_for_status().json()

    def cache(self, pid=PID, **data):
        end = (datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat()
        with self.hub.db() as db:
            db.execute('INSERT OR REPLACE INTO goods_details VALUES(?,?,?)',
                       ('shop',pid,json.dumps(dict(end=end,master_image_url=IMAGE_URL)|data)))

    def assert_no_kalodata(self):
        self.lookup.kalodata.secret.assert_not_called()
        self.lookup.kalodata.post.assert_not_called()
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM own_goods_lookup').fetchone()[0],0)

    def assert_cover(self, gid, basis):
        result = self.projection(gid)
        self.assertEqual((result['cover_fill']['state'],result['cover_source'],result['cover_basis']),('ready','listing',basis))
        url = result['cover_url']
        self.assertEqual(self.anon.get(url).status_code,401)
        pic = self.a.get(url).raise_for_status()
        self.assertEqual(pic.headers['content-type'],'image/webp')
        with Image.open(BytesIO(pic.content)) as image:
            self.assertEqual((image.format,image.size),('WEBP',(560,420)))
            image.load()
        return url

    def test_new_erp_after_save_and_exact_cache_reuse(self):
        self.configure()
        with patch('own_goods_cover_tasks.fetch_image',return_value=ALT_IMAGE) as source, \
             patch('safe_cover.fetch',return_value=fixture_image()) as cdn:
            gid = self.dossier(facts='人工水箱容量 200 mL',category='收纳架')
            before = self.a.get(f'{PREFIX}/{gid}/research/stamp').json()['stamp']
            self.assertEqual(self.projection(gid)['cover_fill']['state'],'queued')
            source.assert_not_called(); cdn.assert_not_called()
            self.assertTrue(self.worker.tick())
            second = self.dossier(DIRECT.replace('www.','shop.'))
            self.assertTrue(self.worker.tick())
            self.assertFalse(self.worker.tick())
        source.assert_called_once_with(KEY,'US',PID)
        cdn.assert_called_once_with(ALT_IMAGE,product=True)
        a,b = [self.assert_cover(x,'lingxing') for x in (gid,second)]
        self.assertEqual(a.split('?v=')[-1],b.split('?v=')[-1])
        detail = self.a.get(f'{PREFIX}/{gid}').raise_for_status().json()
        self.assertEqual(detail['facts'],'人工水箱容量 200 mL')
        self.assertEqual(detail['tag_profile']['override'],'收纳架')
        self.assertEqual(detail['lookup']['state'],'idle')
        self.assertEqual(self.a.get(f'{PREFIX}/{gid}/research/stamp').json()['stamp'],before+1)  # second dossier only
        slim = self.a.get(PREFIX,params={'covers':'true'}).raise_for_status().json()['items']
        self.assertEqual({r['id'] for r in slim},{gid,second})
        self.assertEqual(slim[0]['cover_fill'],'ready')
        self.assertNotIn('tag_profile',slim[0]); self.assertNotIn('url',slim[0])
        self.assert_no_kalodata()

    def test_historical_rows_and_later_cache_without_replaying_legacy_share(self):
        with self.hub.db() as db:
            for gid,url in (('a-legacy',DIRECT),('b-blocked',SHORT),('c-mismatched',DIRECT+'?region=GB')):
                db.execute('INSERT INTO own_goods(id,name,shop,url,market,sku,facts,owner,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                           (gid,'历史样例','隔离店',url,'US','','不改人工字段','fixture_a',time.time()))
        self.assertTrue(self.worker.tick())
        self.assertEqual(self.job('a-legacy')['reason'],'source_not_enabled')
        self.assertEqual(self.job('b-blocked')['reason'],'short_link')
        self.assertEqual(self.job('c-mismatched')['reason'],'unsupported')
        self.cache()
        with patch('safe_cover.fetch',return_value=fixture_image()) as cdn:
            self.assertTrue(self.worker.tick())
            self.assertFalse(self.worker.tick())
        cdn.assert_called_once_with(IMAGE_URL,product=True)
        self.assert_cover('a-legacy','kalodata_cache')
        self.assertIn('完整',self.projection('b-blocked')['cover_fill']['message'])
        self.assertEqual(self.a.get(PREFIX+'/a-legacy').json()['facts'],'不改人工字段')
        self.assert_no_kalodata()

    def test_new_short_resolution_flows_into_existing_report_and_recovery(self):
        gid = self.dossier(SHORT)
        stamp = f'{PREFIX}/{gid}/research/stamp'
        before = self.a.get(stamp).json()['stamp']
        self.cache()
        resolved = DIRECT.replace('/view/product/','/shop/pdp/hand-garden-cultivator/')
        with patch('own_goods_cover_tasks.resolve',return_value=(resolved,PID)) as expand, \
             patch('safe_cover.fetch',return_value=fixture_image()):
            self.assertTrue(self.worker.tick())
        expand.assert_called_once_with(SHORT,'US')
        d = self.a.get(f'{PREFIX}/{gid}').raise_for_status().json()
        self.assertEqual(d['lookup']['cover_fill']['product_id'],PID)
        self.assertEqual(d['tag_profile']['product_id'],PID)
        self.assertEqual(self.a.get(stamp).json()['stamp'],before+1)
        self.assert_cover(gid,'kalodata_cache')
        unknown = self.dossier('https://vm.tiktok.com/UnknownFixture/')
        with self.hub.db() as db:
            db.execute("UPDATE own_goods_cover_jobs SET state='running',attempts=1 WHERE goods=?",(unknown,))
        cover.CoverWorker(self.hub).recover()
        self.assertEqual(self.job(unknown)['reason'],'short_link')
        self.assertFalse(self.worker.tick())
        self.assert_no_kalodata()

    def test_only_transient_cdn_failures_are_retried_and_source_claim_survives(self):
        self.configure()
        gid = self.dossier()
        error = CoverFetchError('CdnTimeout','synthetic-only')
        with patch('own_goods_cover_tasks.fetch_image',return_value=ALT_IMAGE) as source, \
             patch('safe_cover.fetch',side_effect=error) as cdn:
            self.assertTrue(self.worker.tick())
            self.assertEqual(self.job(gid)['attempts'],1)
            saved = self.projection(gid)['cover_fill']
            self.assertEqual(saved['state'],'retry'); self.assertGreater(saved['next_at'],time.time())
            self.assertFalse(self.worker.tick())
            with self.hub.db() as db:
                token = db.execute('SELECT sealed_url FROM own_goods_cover_candidates').fetchone()[0]
                self.assertNotIn(ALT_IMAGE.encode(),token)
                self.assertEqual(self.hub.cipher.decrypt(token).decode(),ALT_IMAGE)
                db.execute("UPDATE own_goods_cover_jobs SET state='running' WHERE goods=?",(gid,))
            new = cover.CoverWorker(self.hub)
            new.recover()
            self.assertTrue(new.tick())
            self.due(gid)
            self.assertTrue(new.tick())
            self.assertEqual((self.job(gid)['state'],self.job(gid)['attempts']),('blocked',3))
            self.assertFalse(new.tick())
            self.assertNotIn(ALT_IMAGE,json.dumps(self.projection(gid)))
        source.assert_called_once_with(KEY,'US',PID)
        self.assertEqual(cdn.call_count,3)
        self.assert_no_kalodata()

    def test_unknown_read_is_never_replayed_by_recovery_duplicate_or_pause(self):
        c = self.configure()
        gid = self.dossier()
        with patch('own_goods_cover_tasks.fetch_image',side_effect=erp.SourceError('erp_unavailable')) as source:
            self.assertTrue(self.worker.tick())
            self.assertEqual(self.job(gid)['reason'],'erp_unavailable')
            other = self.dossier(DIRECT.replace('www.','shop.'))
            paused = self.configure(enabled=False,key='',expected_updated=c['updated'])
            self.assertFalse(paused['enabled'])
            self.assertTrue(self.worker.tick())
            self.assertEqual(self.job(other)['reason'],'source_not_enabled')
            resumed = self.configure(enabled=True,key='',expected_updated=paused['updated'])
            self.assertEqual(self.configure(expected_updated=resumed['updated']),resumed)
            new = cover.CoverWorker(self.hub); new.recover()
            while new.tick():
                pass
        source.assert_called_once_with(KEY,'US',PID)
        self.assertEqual(self.job(other)['reason'],'erp_unavailable')
        self.assert_no_kalodata()

    def test_manual_picture_wins_and_link_change_cannot_apply_stale_result(self):
        self.cache()
        gid = self.dossier()
        def manually_upload(*_a, **_k):
            res = self.a.post(f'{PREFIX}/{gid}/cover',headers=HEADERS,content=fixture_image('#282f39')).raise_for_status()
            self.assertEqual(res.json()['cover_source'],'manual')
            return fixture_image()
        with patch('safe_cover.fetch',side_effect=manually_upload):
            self.assertTrue(self.worker.tick())
        self.assertEqual(self.projection(gid)['cover_source'],'manual')
        second = self.dossier(DIRECT.replace('www.','shop.'))
        def edit_url(*_a, **_k):
            self.a.post(PREFIX,headers=HEADERS,json=PROFILE|dict(id=second,revision=1,url=DIRECT.replace(PID,OTHER))).raise_for_status()
            return fixture_image()
        with patch('safe_cover.fetch',side_effect=edit_url):
            self.assertTrue(self.worker.tick())
        self.assertEqual(self.job(second)['link_key'],link_key(DIRECT.replace(PID,OTHER)))
        self.assertEqual(self.job(second)['state'],'queued')
        self.assertFalse(self.projection(second)['cover_url'])
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM own_goods_listing_images').fetchone()[0],0)
        self.assert_no_kalodata()

    def test_unsupported_market_and_rejected_image_leave_existing_content(self):
        self.configure()
        blank = self.dossier(DIRECT+'?region=GB',market='GB')
        self.assertTrue(self.worker.tick())
        self.assertEqual(self.job(blank)['reason'],'market_not_supported')
        gid = self.dossier(facts='人工确认尺寸 20 cm')
        self.cache()
        with patch('own_goods_cover_tasks.fetch_image',return_value=IMAGE_URL) as source, \
             patch('safe_cover.fetch',return_value=b'<html>Not a picture</html>') as cdn:
            self.assertTrue(self.worker.tick())
            self.assertFalse(self.worker.tick())
        source.assert_called_once(); cdn.assert_called_once()
        self.assertEqual(self.job(gid)['reason'],'image_rejected')
        self.assertFalse(self.projection(gid)['cover_url'])
        self.assertEqual(self.a.get(f'{PREFIX}/{gid}').json()['facts'],'人工确认尺寸 20 cm')
        self.assert_no_kalodata()

    def test_paid_result_is_not_repeated_when_only_the_picture_needs_a_retry(self):
        gid = self.dossier()
        self.lookup.kalodata.post.side_effect = None
        self.lookup.kalodata.post.return_value = dict(REPLY,master_image_url=IMAGE_URL)
        response = self.a.post(f'{PREFIX}/{gid}/lookup',headers=HEADERS,json={'confirmed':True,'revision':1})
        self.assertEqual(response.status_code,200)
        self.assertFalse(self.worker.tick())  # respect an already queued explicit lookup
        with patch('safe_cover.fetch',side_effect=CoverFetchError('CdnTimeout','synthetic-only')):
            self.assertTrue(self.lookup.tick())
        old = self.projection(gid)
        self.assertEqual((old['state'],old['image_state']),('ready','unavailable'))
        self.assertTrue(old['source']['name'])
        with patch('safe_cover.fetch',return_value=fixture_image()) as cdn:
            self.assertTrue(self.worker.tick())
        self.lookup.kalodata.post.assert_called_once()
        cdn.assert_called_once_with(IMAGE_URL,product=True)
        self.assert_cover(gid,'kalodata')
        new = self.projection(gid)
        for key in ('id','state','source','observed'):
            self.assertEqual(old[key],new[key])

    def test_config_admin_only_encrypted_idempotent_and_no_write_on_stale(self):
        self.assertEqual(self.anon.get(SOURCE).status_code,401)
        self.assertEqual(self.a.get(SOURCE).status_code,403)
        self.assertEqual(self.a.post(SOURCE,headers=HEADERS,json={'key':KEY,'enabled':True}).status_code,403)
        self.assertEqual(self.admin.post(SOURCE,json={'key':KEY,'enabled':True,'expected_updated':None}).status_code,403)
        self.assertEqual(self.admin.get(SOURCE).json(),{'configured':False,'enabled':False,'updated':None})
        cfg = self.configure()
        self.assertEqual(self.configure(expected_updated=cfg['updated']),cfg)
        self.assertEqual(self.admin.post(SOURCE,headers=HEADERS,json={'enabled':False,'expected_updated':None}).status_code,409)
        self.assertEqual(self.admin.get(SOURCE).json(),cfg)
        self.assertIn('can_configure_cover_source',self.admin.get(PREFIX).json())
        self.assertFalse(self.a.get(PREFIX).json()['can_configure_cover_source'])
        with self.hub.db() as db:
            key = db.execute('SELECT secret FROM own_goods_cover_config').fetchone()[0]
            self.assertNotIn(KEY.encode(),key)
            self.assertEqual(self.hub.cipher.decrypt(key),KEY.encode())
            self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE action='own_goods_cover_source_updated'").fetchone()[0],1)
            self.assertNotIn(KEY,'\n'.join(db.iterdump()))
        self.assert_no_kalodata()

    def test_failed_new_short_stops_and_correction_queues_exact_id(self):
        gid = self.dossier(SHORT)
        with patch('own_goods_cover_tasks.resolve',side_effect=LinkError('blocked')) as source:
            self.assertTrue(self.worker.tick())
            self.assertFalse(self.worker.tick())
        source.assert_called_once_with(SHORT,'US')
        self.assertEqual(self.job(gid)['reason'],'short_link')
        self.cache()
        self.a.post(PREFIX,headers=HEADERS,json=PROFILE|dict(id=gid,revision=1,url=DIRECT)).raise_for_status()
        with patch('safe_cover.fetch',return_value=fixture_image()):
            self.assertTrue(self.worker.tick())
        self.assert_cover(gid,'kalodata_cache')
        self.assert_no_kalodata()


class ERPContractTests(unittest.TestCase):
    def row(self, **fields):
        return {'site_code':'10011-US','platform_product_id':PID,'image_url':ALT_IMAGE}|fields

    def test_exact_rows_only_and_shop_hosts_are_product_only(self):
        self.assertEqual(erp.exact_image([self.row(site_code='10011-GB'),self.row(platform_product_id=OTHER),self.row()],'US',PID),ALT_IMAGE)
        for rows in ([],[self.row(site_code='10011-GB')], [self.row(platform_product_id=float(PID))],
                     [self.row(image_url='https://example.test/photo')], [self.row(),self.row(image_url=IMAGE_URL)],
                     [{'data':[self.row()]}]):
            with self.subTest(rows=rows), self.assertRaisesRegex(erp.SourceError,'no_exact_image'):
                erp.exact_image(rows,'US',PID)
        with self.assertRaises(CoverFetchError):
            image_url(ALT_IMAGE)

    def run_server(self, *, wrapper=False, sse=False, auth=200, business_code=1, count=1):
        calls = []
        real_client = httpx.Client
        def server(req):
            self.assertEqual(str(req.url),erp.URL)
            self.assertEqual(req.headers['X-Mcp-Key'],KEY)
            self.assertEqual(req.headers['Accept-Encoding'],'identity')
            self.assertNotIn('cookie',req.headers)
            msg = json.loads(req.content)
            method, data = msg['method'],msg['params']
            calls.append((method,data))
            if auth!=200:
                return httpx.Response(auth,headers={'Location':'https://example.test/unused'})
            h={}
            if method=='initialize':
                result = {'protocolVersion':'2025-03-26','capabilities':{}}
                h={'Mcp-Session-Id':'synthetic-session'}
            else:
                self.assertEqual(req.headers['Mcp-Session-Id'],'synthetic-session')
                self.assertEqual(req.headers['MCP-Protocol-Version'],'2025-03-26')
                if method=='notifications/initialized':
                    self.assertNotIn('id',msg)
                    return httpx.Response(202)
                if method=='tools/list':
                    result = {'tools':[{'name':i} for i in ('search','action') if wrapper] or [{'name':erp.TOOL}]}
                elif data['name']=='search':
                    self.assertEqual(data['arguments'],{'toolId':erp.TOOL})
                    result={'structuredContent':{'data':{'toolId':erp.TOOL,'toolType':'read'}}}
                else:
                    params=data['arguments']
                    if wrapper:
                        self.assertEqual((data['name'],params['toolId']),('action',erp.TOOL))
                        params=params['params']
                    else:
                        self.assertEqual(data['name'],erp.TOOL)
                    self.assertEqual(params['search_value'],[PID]); self.assertEqual(params['site_codes'],['10011-US'])
                    self.assertEqual(params['dimension_type'],2); self.assertEqual(params['search_field'],1)
                    self.assertGreater(params['end_date'],params['start_date'])
                    reply={'code':business_code,'data':{'count':count,'data':[self.row()]}}
                    if wrapper:
                        reply={'code':1,'success':True,'data':reply}
                    result={'content':[{'type':'text','text':json.dumps(reply)}]}
            event={'jsonrpc':'2.0','id':msg['id'],'result':result}
            if sse:
                body=': heartbeat\r\n\r\ndata: '+json.dumps(event)+'\r\n\r\n: more'
                return httpx.Response(200,content=body,headers=h|{'Content-Type':'text/event-stream'})
            return httpx.Response(200,json=event,headers=h)
        with patch('own_goods_erp_cover.httpx.Client', side_effect=lambda **kw:real_client(transport=httpx.MockTransport(server),**kw)):
            # Run wire parsing directly to keep protocol assertion failures legible.
            try:
                result = erp._read_image(KEY,'US',PID,time.monotonic()+2)
            except erp.SourceError as exc:
                result = exc.reason
        return result,calls

    def test_native_json_and_wrapped_sse_wire_contract(self):
        for kwargs in ({}, {'wrapper':True,'sse':True}):
            with self.subTest(kwargs=kwargs):
                value,calls=self.run_server(**kwargs)
                self.assertEqual(value,ALT_IMAGE)
                self.assertEqual([method for method,_ in calls],['initialize','notifications/initialized','tools/list']+['tools/call']*(2 if kwargs else 1))

    def test_auth_refusal_no_redirect_error_envelope_and_truncated_rows(self):
        for kwargs,result in (({'auth':403},'erp_forbidden'),({'auth':302},'erp_unavailable'),
                              ({'business_code':500},'erp_unavailable'),({'count':2},'no_exact_image')):
            with self.subTest(kwargs=kwargs):
                observed,calls=self.run_server(**kwargs)
                self.assertEqual(observed,result)
                if 'auth' in kwargs:
                    self.assertEqual(len(calls),1)

    def test_deadline_does_not_wait_for_stuck_os_dns_or_spawn_multiple_calls(self):
        release = threading.Event()
        expired = threading.Event()
        def blocked(*_a):
            try:
                release.wait(2)
            finally:
                expired.set()
        with patch.object(erp,'MAX_SECONDS',0.04),patch.object(erp,'_read_image',side_effect=blocked) as read:
            try:
                with self.assertRaisesRegex(erp.SourceError,'erp_unavailable'):
                    erp.fetch_image(KEY,'US',PID)
                with self.assertRaisesRegex(erp.SourceError,'erp_unavailable'):
                    erp.fetch_image(KEY,'US',OTHER)
                read.assert_called_once()
            finally:
                release.set(); self.assertTrue(expired.wait(2))
