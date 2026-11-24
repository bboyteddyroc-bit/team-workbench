"""Loopback-only isolated preview; do not use this runner for the team service."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

# Native desktop jobs use the workspace venv; this app already has its own dependencies.
root=Path(__file__).resolve().parent
app_python=root/'.venv'/'Scripts'/'python.exe'
if __name__=='__main__' and Path(sys.executable).resolve()!=app_python.resolve():
    raise SystemExit(subprocess.call([str(app_python),'-B',str(Path(__file__).resolve())],cwd=root))

import uvicorn
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from test_own_goods import fixture


def main():
    origin='http://localhost:8797'
    os.environ['HUB_ORIGIN']=origin
    with TemporaryDirectory(prefix='seedance-own-goods-preview-') as state:
        app=fixture(state)

        @app.get('/preview/start')
        def preview_login():
            # Only signs in to the ephemeral fixture's sample user, not the workstation's real DB.
            with TestClient(app,base_url=origin) as client:
                r=client.post('/api/login',headers={'X-Hub-Request':'1','Origin':origin},
                              json={'username':'fixture_a','password':'isolated-fixture-password'})
                r.raise_for_status()
                cookie=r.cookies['hub_session']
            response=RedirectResponse('/')
            response.set_cookie('hub_session',cookie,httponly=True,samesite='strict',max_age=3600)
            return response

        print('Isolated preview: '+origin+'/preview/start',flush=True)
        uvicorn.run(app,host='127.0.0.1',port=8797,proxy_headers=False,access_log=False)


if __name__=='__main__':main()
