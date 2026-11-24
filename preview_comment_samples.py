"""Temporary, loopback-only UI fixture; never opens production state or vendors."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

root=Path(__file__).resolve().parent
app_python=root/'.venv'/'Scripts'/'python.exe'
if __name__=='__main__' and Path(sys.executable).resolve()!=app_python.resolve():
    raise SystemExit(subprocess.call([str(app_python),'-B',str(Path(__file__).resolve())],cwd=root))

import uvicorn
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from test_own_goods import fixture

if __name__=='__main__':
    port=8798;origin=f'http://localhost:{port}';os.environ['HUB_ORIGIN']=origin
    with TemporaryDirectory(prefix='seedance-comments-preview-') as state:
        app=fixture(state)
        # A completed synthetic sample, including a reply and AI citations; no outbound requests.
        with app.state.hub.db() as db:
            db.execute("INSERT INTO comment_sample_jobs(video,url,origin,state,ai_state,created,updated,pages,reply_pages,topics,finished) VALUES(?,?,'backfill','ready','ready',1,1,1,1,?,1)",('123456789','https://www.tiktok.com/@fixture/video/123456789','[{"label":"部分用户希望底座更窄","support":["101010","202020"],"counter":["303030"]}]'))
            db.executemany('INSERT INTO comment_sample_text VALUES(?,?,?,?,?,?,?)',[
                ('123456789','101010','','能不能再窄一点？',1,1,0),
                ('123456789','202020','101010','我家水槽边上也放不下。',1,1,0),
                ('123456789','303030','','我家的宽度刚好。',1,1,1)])

        @app.get('/preview/start')
        def preview_login():
            with TestClient(app,base_url=origin) as client:
                r=client.post('/api/login',headers={'X-Hub-Request':'1','Origin':origin},json={'username':'fixture_admin','password':'isolated-fixture-password'})
                r.raise_for_status();cookie=r.cookies['hub_session']
            response=RedirectResponse('/')
            response.set_cookie('hub_session',cookie,httponly=True,samesite='strict',max_age=3600)
            return response

        print('Isolated fixture, no workers: '+origin+'/preview/start',flush=True)
        uvicorn.run(app,host='127.0.0.1',port=port,proxy_headers=False,access_log=False)
