"""Read-only health/route probe after user-requested service restart."""
from pathlib import Path
import urllib.request,urllib.error,ssl,json,psutil
root=Path(__file__).resolve().parent
op=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(root/'seedance-hub-ca.crt'))))
for base in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    for path in ('/','/mobile/','/static/mobile-receiver.js','/static/editor-mobile.js'):
        with op.open(base+path,timeout=8) as r:
            data=r.read()
            assert r.status==200
            if path.startswith('/static/'):
                assert data==(root/path.lstrip('/')).read_bytes(),'Stale live script: '+path
            print(base+path,'200',flush=True)
    # Intentional anonymous request verifies the new route reaches its login guard, not old 404.
    request=urllib.request.Request(base+'/api/mobile/transfers/restart-probe/selection',data=b'{"exports":[]}',headers={'X-Hub-Request':'1','Content-Type':'application/json','Origin':base},method='POST')
    try:op.open(request,timeout=8);raise AssertionError('Anonymous mutation unexpectedly allowed')
    except urllib.error.HTTPError as error:
        assert error.code==401,('New route not loaded',base,error.code,error.read().decode())
        print('New same-QR selection route loaded; anonymous correctly rejected 401',flush=True)
print('LISTENERS',[(c.laddr.port,c.pid) for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port in (8765,8443)],flush=True)
print('PASS both services healthy; latest phone scripts and new authenticated route loaded.',flush=True)
