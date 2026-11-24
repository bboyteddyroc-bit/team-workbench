"""Regression tests for first-round review fixes; fake providers only."""
from io import BytesIO
import json
import os
import socket
import time
import unittest
from unittest.mock import patch, MagicMock
import safe_cover
from color_adjust import validate
import test_hub as fixtures


class CoverSecurityTests(unittest.TestCase):
    def addresses(self, ip='8.8.8.8'):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]

    def connection(self, chunks, status=200, headers=None):
        conn=MagicMock();response=conn.getresponse.return_value
        response.status=status;response.getheader.side_effect=lambda k,d=None:(headers or {}).get(k,d)
        response.read1.side_effect=chunks
        return conn,response

    def test_reject_untrusted_urls_before_connect(self):
        urls=['http://a.tiktokcdn.com/a','https://127.0.0.1/a','https://a.tiktokcdn.com.evil.test/a',
              'https://u:p@a.tiktokcdn.com/a','https://a.tiktokcdn.com:444/a','file:///tmp/a',
              'https://a.tiktokcdn.com/a#fragment']
        for url in urls:
            with self.subTest(url=url),patch('safe_cover.http.client.HTTPSConnection') as client:
                with self.assertRaises(ValueError):safe_cover.fetch(url)
                client.assert_not_called()

    def test_reject_private_and_mixed_dns(self):
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','fd00::1']:
            with patch('safe_cover.socket.getaddrinfo',return_value=self.addresses(ip)),patch('safe_cover.http.client.HTTPSConnection') as client:
                with self.assertRaises(ValueError):safe_cover.fetch('https://a.tiktokcdn.com/a')
                client.assert_not_called()
        with patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()+self.addresses('10.1.1.1')):
            with self.assertRaises(ValueError):safe_cover.fetch('https://a.tiktokcdn.com/a')

    def test_public_stream_is_pinned_and_keeps_tls_hostname(self):
        conn,response=self.connection([b'\x89PNG\r\n\x1a\n',b'pixels',b''])
        with patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()) as dns,patch('safe_cover.http.client.HTTPSConnection',return_value=conn) as cls,patch('safe_cover.socket.create_connection') as connect:
            self.assertTrue(safe_cover.fetch('https://a.tiktokcdn.com/image?sig=x').startswith(b'\x89PNG'))
            conn._create_connection(('a.tiktokcdn.com',443))
            self.assertEqual(connect.call_args.args[0],('8.8.8.8',443))
            self.assertEqual(cls.call_args.args[0],'a.tiktokcdn.com')
            self.assertEqual(dns.call_count,1)
            self.assertEqual(conn.request.call_args.args[1],'/image?sig=x')
            self.assertEqual(conn.request.call_args.kwargs['headers']['Accept-Encoding'],'identity')
        conn.close.assert_called_once()

    def test_redirect_and_compression_are_not_followed(self):
        for status,headers in [(302,{'Location':'http://127.0.0.1/'}),(200,{'Content-Encoding':'gzip'})]:
            conn,response=self.connection([],status,headers)
            with patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()),patch('safe_cover.http.client.HTTPSConnection',return_value=conn):
                with self.assertRaises(ValueError):safe_cover.fetch('https://a.tiktokcdn.com/a')
                response.read1.assert_not_called()
                conn.request.assert_called_once()

    def test_shop_cdn_default_or_bypassed_route_stays_pinned_direct(self):
        url='https://p16-oec-sg.ibyteimg.com/fixture.png?sig=fixture'
        for bypass,config in ((True,{'https':'http://127.0.0.1:7890'}),(False,{})):
            with self.subTest(bypass=bypass):
                conn,response=self.connection([b'fixture',b''])
                with patch('safe_cover.proxy_bypass',return_value=bypass),patch('safe_cover.getproxies',return_value=config) as proxies,patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()) as dns,patch('safe_cover.http.client.HTTPSConnection',return_value=conn) as cls,patch('safe_cover.socket.create_connection') as connect:
                    with self.assertRaises(ValueError):safe_cover.fetch(url)
                    self.assertEqual(safe_cover.fetch(url,product=True),b'fixture')
                    dns.assert_called_once()
                    if bypass:proxies.assert_not_called()
                    conn._create_connection(('p16-oec-sg.ibyteimg.com',443))
                    self.assertEqual(connect.call_args.args[0],('8.8.8.8',443))
                    self.assertEqual(cls.call_args.args[0],'p16-oec-sg.ibyteimg.com')
                    self.assertFalse({'Cookie','Authorization'} & conn.request.call_args.kwargs['headers'].keys())
                    response.close.assert_called_once()
        for bad in (url.replace('.ibyteimg.com','.ibyteimg.com.example.test'),url.replace('p16-oec-sg','p17-unverified')):
            with patch('safe_cover.socket.getaddrinfo') as dns,self.assertRaises(ValueError):
                safe_cover.fetch(bad,product=True)
            dns.assert_not_called()

    def test_shop_proxy_pins_connect_address_and_keeps_tls_and_host(self):
        host='p16-oec-ttp.tiktokcdn-us.com'
        for status in (200,302):
            with self.subTest(status=status):
                proxy_sock,tls_sock,context=MagicMock(),MagicMock(),MagicMock()
                proxy_sock.makefile.return_value=BytesIO(b'HTTP/1.1 200 Connection established\r\n\r\n')
                tls_sock.makefile.return_value=BytesIO(f'HTTP/1.1 {status} Fixture\r\n'.encode()+
                    b'Location: https://example.invalid/not-followed\r\nContent-Length: 7\r\nConnection: close\r\n\r\nfixture')
                context.wrap_socket.return_value=tls_sock
                with patch('safe_cover.proxy_bypass',return_value=False),patch('safe_cover.getproxies',return_value={'https':'http://127.0.0.1:7890'}),patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()) as dns,patch('safe_cover.ssl.create_default_context',return_value=context),patch('safe_cover.socket.create_connection',return_value=proxy_sock) as dial:
                    url=f'https://{host}/fixture.png?sig=fixture'
                    if status==200:
                        self.assertEqual(safe_cover.fetch(url,product=True),b'fixture')
                    else:
                        with self.assertRaises(safe_cover.CoverFetchError) as e:safe_cover.fetch(url,product=True)
                        self.assertEqual((e.exception.reason,e.exception.status),('CdnHttpStatus',302))
                        self.assertNotIn('sig=',str(e.exception))
                dns.assert_called_once_with(host,443,type=socket.SOCK_STREAM)
                self.assertEqual(dial.call_args.args[0],('127.0.0.1',7890))
                dial.assert_called_once()
                tunnel=b''.join(c.args[0] for c in proxy_sock.sendall.call_args_list)
                self.assertTrue(tunnel.startswith(b'CONNECT 8.8.8.8:443 HTTP/1.'))
                self.assertNotIn(b'fixture.png',tunnel)
                context.wrap_socket.assert_called_once_with(proxy_sock,server_hostname=host)
                request=b''.join(c.args[0] for c in tls_sock.sendall.call_args_list)
                self.assertTrue(request.startswith(b'GET /fixture.png?sig=fixture HTTP/1.1\r\n'))
                self.assertIn(f'\r\nHost: {host}\r\n'.encode(),request)
                for header in (b'cookie:',b'authorization:',b'proxy-authorization:'):
                    self.assertNotIn(header,request.lower()+tunnel.lower())

    def test_shop_proxy_rejects_mixed_dns_and_unapproved_proxy_origins(self):
        host='p16-oec-ttp.tiktokcdn-us.com'
        with patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()+self.addresses('10.1.1.1')),patch('safe_cover._PinnedShopTunnel') as tunnel,patch('safe_cover.getproxies') as proxies:
            with self.assertRaises(safe_cover.CoverFetchError) as e:
                safe_cover.fetch(f'https://{host}/photo',product=True)
            self.assertEqual(e.exception.reason,'CdnAddressRejected')
            tunnel.assert_not_called();proxies.assert_not_called()
        for candidate in ('http://192.168.0.1:7890','http://user:pw@127.0.0.1:7890',
                          'https://127.0.0.1:7890','http://127.0.0.1:99999','http://127.0.0.1:7890?query=1'):
            with patch('safe_cover.proxy_bypass',return_value=False),patch('safe_cover.getproxies',return_value={'https':candidate}):
                self.assertIsNone(safe_cover._shop_proxy(host,('8.8.8.8',)))
        with patch('safe_cover.getproxies') as proxies:
            self.assertIsNone(safe_cover._shop_proxy('other.tiktokcdn-us.com',('8.8.8.8',)))
            proxies.assert_not_called()

    def test_product_truncated_response_is_not_saved(self):
        conn,response=self.connection([b'fixture',b''],headers={'Content-Length':'32768'})
        with patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()),patch('safe_cover.http.client.HTTPSConnection',return_value=conn):
            with self.assertRaises(safe_cover.CoverFetchError) as e:
                safe_cover.fetch('https://other.tiktokcdn-us.com/fixture.png',product=True)
        self.assertEqual((e.exception.reason,e.exception.status),('CdnTruncated',200))
        response.close.assert_called_once()

    def test_product_deadline_does_not_wait_for_dns_or_leave_a_success_result(self):
        import threading
        release=threading.Event();finished=threading.Event()
        def delayed(*args, **kwargs):
            try:
                release.wait(3)
                raise OSError('isolated DNS failure')
            finally:
                finished.set()
        with patch('safe_cover.destination',side_effect=delayed),patch('safe_cover.MAX_SECONDS',0.03):
            try:
                with self.assertRaisesRegex(ValueError,'下载超时'):
                    safe_cover.fetch('https://p16-oec-sg.ibyteimg.com/fixture.png',product=True)
                self.assertFalse(finished.is_set())
            finally:
                release.set()
                self.assertTrue(finished.wait(2))

    def test_length_and_stream_limit_stop_early(self):
        for headers,chunks in [({'Content-Length':'4000001'},[]),({},[b'12345',b'6789',b'should-not-read'])]:
            conn,response=self.connection(chunks,headers=headers)
            with patch('safe_cover.MAX_BYTES',8),patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()),patch('safe_cover.http.client.HTTPSConnection',return_value=conn):
                with self.assertRaises(ValueError):safe_cover.fetch('https://a.tiktokcdn.com/a')
                self.assertLessEqual(response.read1.call_count,2)
            conn.close.assert_called_once()

    def test_detached_response_closed_on_overflow(self):
        conn,response=self.connection([b'123456789'])
        conn.sock=None
        with patch('safe_cover.MAX_BYTES',8),patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()),patch('safe_cover.http.client.HTTPSConnection',return_value=conn):
            with self.assertRaises(ValueError):safe_cover.fetch('https://a.tiktokcdn.com/a')
        response.fp.raw._sock.settimeout.assert_called()
        response.close.assert_called_once()
        conn.close.assert_called_once()

    def test_detached_socket_is_not_touched_after_exact_length(self):
        # Exercise the real HTTPResponse close-on-final-byte behavior. Windows
        # rejects settimeout() on the detached socket once its file is closed.
        from http.client import HTTPConnection
        from types import SimpleNamespace
        body=b'complete-image'
        fp=BytesIO(f'HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
        sock=MagicMock()
        fp.raw=SimpleNamespace(_sock=sock)
        sock.makefile.return_value=fp

        def on_timeout(_seconds):
            if fp.closed:
                raise OSError('fixture detached socket already closed')

        sock.settimeout.side_effect=on_timeout
        host='other.tiktokcdn-us.com'
        conn=HTTPConnection(host,443)
        with patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()),patch('safe_cover.http.client.HTTPSConnection',return_value=conn),patch('safe_cover.socket.create_connection',return_value=sock):
            self.assertEqual(safe_cover.fetch(f'https://{host}/fixture.png',product=True),body)
        self.assertTrue(fp.closed)

    def test_total_deadline_and_busy_limit(self):
        conn,response=self.connection([b'a',b'b'])
        with patch('safe_cover.socket.getaddrinfo',return_value=self.addresses()),patch('safe_cover.http.client.HTTPSConnection',return_value=conn),patch('safe_cover.time.monotonic',side_effect=[0,0,0,0,21]):
            with self.assertRaises(ValueError):safe_cover.fetch('https://a.tiktokcdn.com/a')
        slots=[]
        try:
            for _ in range(4):self.assertTrue(safe_cover._slots.acquire(False));slots.append(True)
            with self.assertRaises(ValueError):safe_cover.fetch('https://a.tiktokcdn.com/a')
        finally:
            for _ in slots:safe_cover._slots.release()


class InterfaceTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login

    def owner(self):return self.member.get('/api/me').json()['id']
    def post(self,path,data):return self.member.post(path,json=data,headers=fixtures.H)

    def project(self,pid,version=1):
        body={'clips':[{'task_id':'fixture','start':0,'end':10,'speed':2}], 'captions':[], 'audio_clips':[], 'audio':None}
        with self.hub.db() as db:
            db.execute('INSERT INTO edit_projects VALUES(?,?,?,?,?,?)',(pid,self.owner(),pid,json.dumps(body),version,time.time()))
            db.execute('INSERT INTO edit_versions VALUES(?,?,?,?,?)',(pid,version,pid,json.dumps(body),time.time()))
        return body

    def test_export_idempotency_conflicts_and_exact_retry_after_edit(self):
        self.project('one');self.project('two');url='/api/editor/projects/one/export'
        request={'request_key':'audit-export-key-00001','version':1,'name':'video'}
        first=self.post(url,request);self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.post(url,request).json(),first.json())
        for changed in ({**request,'name':'other'},{**request,'version':2},{**request,'selection':None}):
            self.assertEqual(self.post(url,changed).status_code,409)
        self.assertEqual(self.post('/api/editor/projects/two/export',request).status_code,409)
        with self.hub.db() as db:db.execute("UPDATE edit_projects SET version=2 WHERE id='one'")
        self.assertEqual(self.post(url,request).json(),first.json())
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM edit_exports').fetchone()[0],1)
        self.assertEqual(self.admin.post(url,json=request,headers=fixtures.H).status_code,404)

    def test_legacy_export_key_does_not_silently_match(self):
        body=self.project('one')
        with self.hub.db() as db:
            db.execute('INSERT INTO edit_exports(id,owner,project_id,body,state,created,updated,request_key) VALUES(?,?,?,?,?,?,?,?)',('old',self.owner(),'one',json.dumps(body),'ready',time.time(),time.time(),'audit-legacy-key-0001'))
        self.assertEqual(self.post('/api/editor/projects/one/export',{'request_key':'audit-legacy-key-0001','version':1}).status_code,409)

    def test_versions_use_timeline_duration(self):
        self.project('one')
        result=self.member.get('/api/editor/projects/one/versions')
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()[0]['duration'],5)
        from editor import timeline_duration
        for body in [{'clips':[],'captions':[{'start':0,'end':12}]}, {'clips':[],'audio_clips':[{'at':3,'start':1,'end':5}]}]:
            with self.hub.db() as db:db.execute('UPDATE edit_versions SET body=? WHERE project_id=?',(json.dumps(body),'one'))
            self.assertEqual(self.member.get('/api/editor/projects/one/versions').json()[0]['duration'],timeline_duration(body))

    def pending_image(self,pid=99999999,stamp='dead',age=86400):
        tid=self.post('/api/assistant/threads',{}).json()['id'];uid=self.owner();turn='auditturn'
        generation=json.dumps({'provider':'libtv','model':'lib-image-2.5-f','size':'1K','ratio':'9:16','project':'b'*32})
        with self.hub.db() as db:
            db.execute("INSERT INTO ai_turns(id,owner,thread,request_key,prompt,status,created,generation,runner_pid,runner_stamp) VALUES(?,?,?,?,?,'pending',?,?,?,?)",(turn,uid,tid,'audit-old-image-key','draw',time.time()-age,generation,pid,stamp))
        return tid,turn

    def test_dead_image_worker_becomes_recoverable_without_generation(self):
        tid,turn=self.pending_image()
        # Reconstruct application as after a restart; all state here is temporary.
        from app import create_app
        app=create_app(self.tmp.name,fixtures.FakeProvider(),worker=False)
        from fastapi.testclient import TestClient
        with TestClient(app,base_url=fixtures.BASE) as client:
            client.cookies.update(self.member.cookies)
            rows=client.get('/api/assistant/threads/'+tid).json();self.assertEqual(rows[0]['status'],'failed')
            def finish(hub,uid,t,turn,project,work):
                with hub.db() as db:db.execute("UPDATE ai_turns SET status='complete' WHERE id=?",(turn,))
                return {'id':turn,'status':'complete','result_asset':'fixture'}
            with patch('assistant_images.import_libtv_result',side_effect=finish) as importer,patch('assistant_images.generate_libtv') as generator:
                response=client.post('/api/assistant/threads/'+tid+'/turns/'+turn+'/recover',json={},headers=fixtures.H)
                self.assertEqual(response.status_code,200,response.text);importer.assert_called_once();generator.assert_not_called()

    def test_live_worker_not_stolen_and_cross_owner_rejected(self):
        from assistant_runtime import process_stamp
        tid,turn=self.pending_image(os.getpid(),process_stamp(os.getpid()))
        self.assertEqual(self.member.get('/api/assistant/threads/'+tid).json()[0]['status'],'pending')
        path='/api/assistant/threads/'+tid+'/turns/'+turn+'/recover'
        self.assertEqual(self.post(path,{}).status_code,409)
        self.assertEqual(self.admin.post(path,json={},headers=fixtures.H).status_code,404)

    def test_old_legacy_pending_unblocks_account_but_not_live_legacy(self):
        tid,turn=self.pending_image(0,'')
        self.assertEqual(self.member.get('/api/assistant/threads/'+tid).json()[0]['status'],'failed')
        with self.hub.db() as db:db.execute("UPDATE ai_turns SET status='pending',created=? WHERE id=?",(time.time(),turn))
        self.assertEqual(self.member.get('/api/assistant/threads/'+tid).json()[0]['status'],'pending')

    def test_cover_endpoint_rejects_private_before_network(self):
        uid=self.owner();now=time.time()
        with self.hub.db() as db:
            db.execute('INSERT INTO apify_accounts(id,owner,handle) VALUES(?,?,?)',('aa',uid,'audit'))
            db.execute('INSERT INTO apify_runs(id,account,state,created,updated) VALUES(?,?,?,?,?)',('rr','aa','ready',now,now))
            db.execute('INSERT INTO apify_snapshots(run,account,video,cover,collected) VALUES(?,?,?,?,?)',('rr','aa','123','http://127.0.0.1/internal',now))
        with patch('safe_cover.http.client.HTTPSConnection') as conn:
            self.assertEqual(self.member.get('/api/intelligence/apify/accounts/aa/cover/123').status_code,404);conn.assert_not_called()
        with patch('safe_cover.fetch',return_value=b'\x89PNG\r\n\x1a\nfixture') as fetch:
            self.assertEqual(self.member.get('/api/intelligence/apify/accounts/aa/cover/123').status_code,200)
            self.assertEqual(self.member.get('/api/intelligence/apify/accounts/aa/cover/123').status_code,200)
            fetch.assert_called_once()


class ColorIdempotencyTests(unittest.TestCase):
    def test_empty_and_nonempty_roundtrip(self):
        for raw in [None,{}, {'brightness':0}, {'brightness':12.34}, {'hsl':{'red':{'h':20}}}]:
            clean=validate(raw);self.assertEqual(validate(clean),clean)
        self.assertEqual(validate({}),{})
        for raw in [[],False,{'brightness':float('nan')},{'hsl':[]}]:
            with self.assertRaises(ValueError):validate(raw)
