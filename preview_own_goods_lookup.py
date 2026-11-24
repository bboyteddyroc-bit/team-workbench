"""Isolated loopback acceptance for the product link-to-report UI; no real provider calls."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT/'.venv'/'Scripts'/'python.exe'
if __name__ == '__main__' and Path(sys.executable).resolve() != RUNTIME.resolve():
    raise SystemExit(subprocess.call([str(RUNTIME), '-B', '-X', 'utf8', str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT))

import contextlib
import tempfile
import threading
import time
from unittest.mock import Mock, patch

import uvicorn
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from own_goods import PREFIX
from test_own_goods import PROFILE, fixture
from test_own_goods_lookup import DIRECT, IMAGE_URL, PID, REPLY, SHORT, fixture_image
from test_own_goods_research import add_case

PORT = int(sys.argv[1]) if __name__ == '__main__' and len(sys.argv) == 2 else 8803
ORIGIN = f'http://127.0.0.1:{PORT}'
HEADERS = {'X-Hub-Request': '1', 'Origin': ORIGIN}


def no_network(*args, **kwargs):
    raise AssertionError('Outbound network is forbidden in the lookup acceptance fixture')


def demo_redirect(p, _deadline):
    if p.path=='/t/BrokenFixture/':
        return 'https://www.tiktok.com/@fixture/video/101000010'
    if p.path==('/t/ExampleFixture/'):
        return DIRECT+'?opaque_tracking=demo-not-persisted'
    return no_network()


def login(client):
    return client.post('/api/login', headers=HEADERS,
                       json={'username': 'fixture_admin', 'password': 'isolated-fixture-password'}).raise_for_status()


def main():
    os.environ['HUB_ORIGIN'] = ORIGIN
    with contextlib.ExitStack() as resources:
        directory=resources.enter_context(tempfile.TemporaryDirectory(prefix='hub-own-lookup-'))
        resources.enter_context(patch('httpx.HTTPTransport.handle_request', side_effect=no_network))
        resources.enter_context(patch('httpx.AsyncHTTPTransport.handle_async_request', side_effect=no_network))
        resources.enter_context(patch('urllib.request.OpenerDirector.open', side_effect=no_network))
        resources.enter_context(patch('tiktok_shop_link._redirect', side_effect=demo_redirect))
        resources.enter_context(patch('voice_catalog.browse', return_value={'voices':[], 'page':1, 'has_more':False}))
        app=fixture(directory); hub=app.state.hub; lookup=app.state.own_goods_lookup
        def product_detail(endpoint, payload, *, secret):
            assert endpoint=='/product/detail' and payload['product_id']==PID and payload['region']=='US' and payload['need_image']==1
            return dict(REPLY,master_image_url=IMAGE_URL)
        def download(url, *, product=False):
            assert url==IMAGE_URL and product
            time.sleep(3)  # Exercise the intermediate text-ready/image-checking phase in the UI.
            return fixture_image()
        resources.enter_context(patch('safe_cover.fetch',side_effect=download))
        lookup.kalodata=Mock()
        lookup.kalodata.secret.return_value='isolated-fixture-only'
        lookup.kalodata.post.side_effect=product_detail
        now=time.time()
        with hub.db() as db:
            add_case(db,'lookup-demo-case','101000011',now,handle='fixture_garden',category='Garden Tiller',
                     transcript='This hand tool loosens compacted garden soil.',
                     human={'title':'验收案例 · 花坛松土演示','category':'松土器','summary':'手持工具在花坛松土。'})
            db.execute('INSERT INTO intel_goods VALUES(?,?,?,?)',(PID,'Fixture listing','',''))
            db.execute('INSERT INTO intel_goods_video VALUES(?,?,?,?)',(PID,'101000011','fixture_garden','Kalodata'))
        # This TestClient must not run the app lifespan; its shutdown sets hub.stop.
        with contextlib.closing(TestClient(app,base_url=ORIGIN)) as client:
            login(client)
            for data in (dict(name='园艺商品（验收样例）',url=SHORT,sku='DEMO-1',facts='已核实规格：20 cm。'),
                         dict(name='失效短链（验收样例）',url='https://www.tiktok.com/t/BrokenFixture/')):
                client.post(PREFIX,headers=HEADERS,json=PROFILE|data).raise_for_status()

        @app.get('/preview/lookup')
        def start():
            with contextlib.closing(TestClient(app,base_url=ORIGIN)) as client:
                cookie=login(client).cookies['hub_session']
            response=RedirectResponse('/')
            response.set_cookie('hub_session',cookie,httponly=True,samesite='strict',max_age=1800)
            return response

        thread=threading.Thread(target=lookup.loop,daemon=True)
        thread.start()
        print(f'Isolated product-link acceptance (mocked TikTok and Kalodata): {ORIGIN}/preview/lookup',flush=True)
        try:
            uvicorn.run(app,host='127.0.0.1',port=PORT,proxy_headers=False,access_log=False)
        finally:
            hub.stop.set();thread.join(5)

if __name__=='__main__':
    main()
