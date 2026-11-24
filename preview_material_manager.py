"""Temporary isolated browser regression server. No production state or provider calls."""
from pathlib import Path
import subprocess,sys,tempfile,io,time
root=Path(__file__).resolve().parent
python=root/'.venv/Scripts/python.exe'
if Path(sys.executable).resolve()!=python.resolve():raise SystemExit(subprocess.call([str(python),'-B',str(Path(__file__).resolve())]))
import os
os.environ['HUB_ORIGIN']='http://127.0.0.1:8766'
import uvicorn
from app import create_app
from fastapi.testclient import TestClient
from fastapi.responses import RedirectResponse
from PIL import Image,ImageDraw
with tempfile.TemporaryDirectory(prefix='material-ui-regression-') as state:
 app=create_app(state,worker=False)
 hub=app.state.hub
 headers={'X-Hub-Request':'1','Origin':'http://127.0.0.1:8766'}
 client=TestClient(app,base_url='http://127.0.0.1:8766')
 auth={'username':'preview','password':'isolated-browser-test-only-123456'}
 client.post('/api/setup',json=auth,headers=headers).raise_for_status()
 login=client.post('/api/login',json=auth,headers=headers);login.raise_for_status()
 cookie=login.headers['set-cookie']
 for i,name in enumerate(['回归测试-产品正面.png','回归测试-人物参考.png','回归测试-场景远景.png','回归测试-历史素材.png']):
  image=Image.new('RGB',(640,480),(28+i*8,40+i*5,45+i*6));draw=ImageDraw.Draw(image)
  draw.rounded_rectangle((180,100,460,380),radius=35,fill=(80+i*30,125+i*10,140+i*10));draw.text((24,24),'ISOLATED UI TEST '+str(i+1),fill='white')
  stream=io.BytesIO();image.save(stream,format='PNG')
  import urllib.parse
  r=client.post('/api/assets',content=stream.getvalue(),headers={**headers,'Content-Type':'image/png','X-File-Name':urllib.parse.quote(name)});r.raise_for_status();aid=r.json()['id']
  client.post('/api/workspace/materials/'+aid,json={'category':['product','person','scene','other'][i]},headers=headers).raise_for_status()
  if i==3:
   with hub.db() as db:db.execute('UPDATE assets SET created=? WHERE id=?',(time.time()-10*86400,aid))
 @app.get('/__fixture')
 def fixture():
  response=RedirectResponse('/');response.headers['set-cookie']=cookie;return response
 print('Isolated material regression preview: http://127.0.0.1:8766/__fixture',flush=True)
 uvicorn.run(app,host='127.0.0.1',port=8766,log_level='warning')
 client.close()
