"""Loopback preview of real UI and feedback API, using synthetic state and no workers/vendors."""
from contextlib import ExitStack
from pathlib import Path
import os
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


if __name__=='__main__':
    from argparse import ArgumentParser
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--history-rows', type=int, choices=range(0,201), default=0)
    parser.add_argument('--studio-results',action='store_true',help='Seed synthetic finished videos and allow local frame extraction and draft saves')
    options=parser.parse_args()
    root=Path(__file__).resolve().parent
    app_python=root/'.venv'/'Scripts'/'python.exe'
    if Path(sys.executable).resolve()!=app_python.resolve():
        raise SystemExit(subprocess.call([str(app_python),'-B',str(Path(__file__).resolve()),*sys.argv[1:]],cwd=root))

    import uvicorn
    from fastapi.responses import RedirectResponse, JSONResponse
    from fastapi.testclient import TestClient
    from test_own_goods import fixture
    from test_task_feedback import seed_feedback

    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    listener.bind(('127.0.0.1',0))
    port=listener.getsockname()[1];origin=f'http://localhost:{port}';os.environ['HUB_ORIGIN']=origin
    def blocked(*args,**kwargs):
        raise AssertionError('Outbound traffic is disabled in this preview')

    with TemporaryDirectory(prefix='seedance-feedback-preview-') as state, ExitStack() as stack:
        for path in ('httpx.HTTPTransport.handle_request','httpx.AsyncHTTPTransport.handle_async_request','urllib.request.OpenerDirector.open','libtv_gateway.run_bounded'):
            stack.enter_context(patch(path,side_effect=blocked))
        app=fixture(state)
        seed_feedback(app,extra=options.history_rows)
        allowed_posts={'/api/login','/api/logout'}
        if options.studio_results:
            from test_studio_result_actions import seed_results
            seed_results(app)
            allowed_posts.update(('/api/media/extract','/api/compositions'))

        @app.middleware('http')
        async def read_only_preview(request,call_next):
            if request.method not in ('GET','HEAD','OPTIONS') and request.url.path not in allowed_posts:
                return JSONResponse({'detail':'预览仅供查看，不能提交业务任务'},status_code=403)
            response=await call_next(request)
            if request.url.path=='/':
                response.headers['Content-Security-Policy']="connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:"
            return response

        @app.get('/preview/start')
        def preview_login():
            with TestClient(app,base_url=origin) as client:
                login=client.post('/api/login',headers={'X-Hub-Request':'1','Origin':origin},
                                  json={'username':'fixture_a','password':'isolated-fixture-password'})
                login.raise_for_status()
                response=RedirectResponse('/')
                response.set_cookie('hub_session',login.cookies['hub_session'],httponly=True,samesite='strict',max_age=3600)
                return response

        print('Isolated feedback preview: '+origin+'/preview/start',flush=True)
        try:
            uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,proxy_headers=False,access_log=False)).run(sockets=[listener])
        finally:
            listener.close()
