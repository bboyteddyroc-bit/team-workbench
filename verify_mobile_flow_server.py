"""Isolated browser acceptance server. Never uses production state or paid providers."""
import os,sys,tempfile,shutil,json,time,secrets
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ['HUB_ORIGIN']='http://127.0.0.1:8872'
os.environ['HUB_MOBILE_ORIGIN']='http://127.0.0.1:8873'
binpath=ROOT/'tools/ffmpeg-7.1.1/ffmpeg-7.1.1-essentials_build/bin'
if binpath.is_dir():os.environ['PATH']=str(binpath)+os.pathsep+os.environ['PATH']
from app import create_app
from editor import run
from fastapi.testclient import TestClient
from test_hub import FakeProvider
import uvicorn

def main():
 with tempfile.TemporaryDirectory(prefix='mobile-browser-') as tmp:
  app=create_app(tmp,FakeProvider(),worker=False)
  client=TestClient(app,base_url=os.environ['HUB_ORIGIN'])
  headers={'X-Hub-Request':'1','Origin':os.environ['HUB_ORIGIN']}
  pw='Browser-test-only-12345'
  assert client.post('/api/setup',json={'username':'mobiletest','password':pw},headers=headers).status_code==200
  assert client.post('/api/login',json={'username':'mobiletest','password':pw},headers=headers).status_code==200
  owner=client.get('/api/me').json()['id']
  source=Path(tmp)/'phone-sample.mp4'
  run([shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=s=160x240:r=30:d=1','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)])
  # Upload input is an intermediate file inside the authorized project.
  staging=ROOT/'mobile-flow-test-input.mp4';shutil.copyfile(source,staging)
  with app.state.hub.db() as db:
   for n in range(20):
    eid='browser_export_'+str(n);shutil.copyfile(source,app.state.editor.root/(eid+'.mp4'))
    db.execute('INSERT INTO edit_exports(id,owner,project_id,body,state,created,updated,request_key) VALUES(?,?,?,?,?,?,?,?)',(eid,owner,'fixture',json.dumps({'export_name':'验收成品 '+str(n)}),'ready',time.time(),time.time(),secrets.token_hex(12)))
  from mobile_http import create_phone_app
  import threading
  phone=uvicorn.Server(uvicorn.Config(create_phone_app(app,origin='http://127.0.0.1:8873'),host='127.0.0.1',port=8873,proxy_headers=False,access_log=False))
  thread=threading.Thread(target=phone.run,daemon=True);thread.start()
  print('MOBILE_TEST_READY http://127.0.0.1:8872/ ; phone-only HTTP http://127.0.0.1:8873/ (isolated state, no EXE)',flush=True)
  try:uvicorn.run(app,host='127.0.0.1',port=8872,access_log=False)
  finally:phone.should_exit=True;thread.join(timeout=5);client.close();staging.unlink(missing_ok=True)
if __name__=='__main__':main()
