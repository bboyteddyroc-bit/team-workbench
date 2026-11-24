"""Loopback browser acceptance fixture. Uses an isolated DB and never starts workers."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

root=Path(__file__).resolve().parent
app_python=root/'.venv'/'Scripts'/'python.exe'
if __name__=='__main__' and Path(sys.executable).resolve()!=app_python.resolve():
    raise SystemExit(subprocess.call([str(app_python),'-B',str(Path(__file__).resolve())],cwd=root))

import uvicorn
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from test_own_goods import fixture
from test_own_goods_research import HAMPER, evidence_fixture
from own_goods import PREFIX

if __name__=='__main__':
    port=8799;origin=f'http://127.0.0.1:{port}';os.environ['HUB_ORIGIN']=origin
    headers={'X-Hub-Request':'1','Origin':origin}
    with TemporaryDirectory(prefix='seedance-own-goods-browser-') as state:
        app=fixture(state);hub=app.state.hub
        evidence_fixture(hub,time.time()-120)
        def login(client):
            r=client.post('/api/login',headers=headers,json={'username':'fixture_admin','password':'isolated-fixture-password'})
            r.raise_for_status();return r
        with TestClient(app,base_url=origin) as client:
            login(client)
            for goods in (HAMPER,dict(HAMPER,name='样例未知类目',url='https://example.test/product/special'),
                          dict(HAMPER,name='窗帘圈（空报告示例）',url='https://example.test/product/ring',category='窗帘挂环')):
                client.post(PREFIX,headers=headers,json=goods).raise_for_status()

        @app.get('/preview/research')
        def isolated_page():
            with TestClient(app,base_url=origin) as client:session=login(client).cookies['hub_session']
            response=RedirectResponse('/')
            response.set_cookie('hub_session',session,httponly=True,samesite='strict',max_age=1800)
            return response

        print('Isolated fixture (workers off, synthetic evidence): '+origin+'/preview/research',flush=True)
        uvicorn.run(app,host='127.0.0.1',port=port,proxy_headers=False,access_log=False)
