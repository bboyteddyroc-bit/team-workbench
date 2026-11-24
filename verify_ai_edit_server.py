"""Isolated browser acceptance fixture. Never points at production state or APIs."""
import os,sys,hashlib,time,shutil
from pathlib import Path
root=Path(__file__).resolve().parent
runtime=root/'.venv/Scripts/python.exe'
if Path(sys.executable).resolve()!=runtime.resolve() and sys.version_info[:2]!=(3,11):
    os.execv(str(runtime),[str(runtime),'-B',str(Path(__file__).resolve())])
os.chdir(root)
os.environ['HUB_ORIGIN']='http://127.0.0.1:8879'
from app import create_app,password_hash
import uvicorn
state=root/'verification/ai-edit-state'
app=create_app(state,worker=False)
hub=app.state.hub
owner='ai-edit-acceptance'
with hub.db() as db:
    db.execute('INSERT OR IGNORE INTO users(id,username,password,role,must_change) VALUES(?,?,?,?,0)',(owner,'AI剪辑验收',password_hash('local-fixture-unused-password'),'admin'))
    token='isolated-ai-edit-browser-fixture'
    db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),owner,time.time()+86400))
    path=Path(r'C:\Users\111\Downloads\视频节点 2 - 副本.mp4')
    if path.is_file():
        sid='footage_ai_acceptance';target=app.state.editor.footage/sid
        if not target.exists():shutil.copyfile(path,target)
        from editor import probe
        duration,_=probe(target)
        db.execute('INSERT OR IGNORE INTO edit_footage VALUES(?,?,?,?,?,?)',(sid,owner,'挂烫机 · 本地验收素材',target.stat().st_size,duration,time.time()))
@app.middleware('http')
async def isolated_fixture(request,call_next):
    response=await call_next(request)
    if request.url.path=='/':response.set_cookie('hub_session',token,httponly=True,samesite='strict')
    return response
# Only the AI queue is run: no collectors, no image classification, no external automations.
import threading
app.state.ai_editing.recover()
threading.Thread(target=app.state.ai_editing.loop,daemon=True).start()
print('AI editing acceptance: http://127.0.0.1:8879 (isolated data; no production writes)',flush=True)
uvicorn.run(app,host='127.0.0.1',port=8879,access_log=False)
