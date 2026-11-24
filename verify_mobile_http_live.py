"""Read-only deployed health, route-isolation and exact live code checks."""
from pathlib import Path
import urllib.request,urllib.error,ssl,json,psutil
root=Path(__file__).resolve().parent
op=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(root/'seedance-hub-ca.crt'))))
for base in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    with op.open(base+'/',timeout=8) as response:assert response.status==200
    with op.open(base+'/static/editor-mobile.js',timeout=8) as response:assert response.read()==(root/'static/editor-mobile.js').read_bytes()
    print(base,'Hub OK; newest phone QR UI',flush=True)
base='http://192.168.100.10:8000'
with op.open(base+'/health',timeout=8) as response:
    d=json.load(response);assert d['service']=='hub-mobile-transfer' and not d['encrypted']
for path in ('/mobile/','/static/mobile-receiver.js','/static/mobile-transfer.css'):
    with op.open(base+path,timeout=8) as response:
        data=response.read();assert response.status==200
        if path.startswith('/static/'):assert data==(root/path.lstrip('/')).read_bytes()
        if path=='/mobile/':assert '不加密'.encode() in data
    print(base+path,'200',flush=True)
for path in ('/api/login','/api/me','/api/editor/library','/api/users','/api/mobile/transfers','/static/app.js'):
    try:op.open(base+path,timeout=8);raise AssertionError('Exposed Hub route: '+path)
    except urllib.error.HTTPError as e:assert e.code==404,(path,e.code)
for headers,expected in [({},410),({'Host':'evil.invalid'},400),({'Origin':'https://evil.invalid'},403)]:
    try:op.open(urllib.request.Request(base+'/api/mobile/session',headers=headers),timeout=8);raise AssertionError('Guard did not reject request')
    except urllib.error.HTTPError as e:assert e.code==expected,(e.code,expected)
listeners={c.laddr.port:c.pid for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port in (8000,8443,8765)}
assert listeners[8000]==listeners[8443],'Phone listener must live in the Hub LAN process'
print('Listeners',listeners,flush=True)
print('PASS HTTP phone-only port; API isolation, token/Host/Origin guards; same LAN PID as HTTPS Hub.',flush=True)
