"""Isolated UI fixture: responses are visibly simulated, never paid model requests."""
import os,sys,time,hashlib,shutil,threading
from pathlib import Path
root=Path(__file__).resolve().parent
runtime=root/'.venv/Scripts/python.exe'
if sys.version_info[:2]!=(3,11):os.execv(str(runtime),[str(runtime),'-B',str(Path(__file__).resolve())])
os.chdir(root)
ffmpeg=root/'tools/ffmpeg-7.1.1/ffmpeg-7.1.1-essentials_build/bin'
os.environ['PATH']=str(ffmpeg)+os.pathsep+os.environ.get('PATH','')
os.environ['HUB_ORIGIN']='http://127.0.0.1:8881'
from app import create_app,password_hash
import uvicorn
import ai_edit_conversation
import asr
state=root/'verification/general-conversation-state'
app=create_app(state,worker=False);hub=app.state.hub;service=app.state.ai_editing
owner='conversation-ui-fixture';sid='footage_conversation_fixture'
with hub.db() as db:
    db.execute('INSERT OR IGNORE INTO users(id,username,password,role,must_change) VALUES(?,?,?,?,0)',(owner,'对话剪辑验收',password_hash('fixture-unused-password'),'admin'))
    token='isolated-conversation-browser-fixture'
    db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),owner,time.time()+86400))
    source=root/'verification/ai-edit-state/edit_footage/footage_ai_acceptance'
    target=app.state.editor.footage/sid
    if source.is_file() and not target.exists():shutil.copyfile(source,target)
    from editor import probe
    duration,_=probe(target)
    db.execute('INSERT OR IGNORE INTO edit_footage VALUES(?,?,?,?,?,?)',(sid,owner,'验收素材 · 挂烫机',target.stat().st_size,duration,time.time()))
asr.configured_key=lambda hub:'isolated-fake-key-never-sent'
def response(hub,system,context):
    from test_ai_edit_general import CONTRACT
    return {'reply':'【模拟回复 / 无真实模型调用】已经理解：自然生活记录，不要广告感；3秒竖屏，保留原声，不加字幕标题。最终确认后才分析。','brief':{'product':'','audience':'','reason':'','facts':'','avoid':'广告感','target':3,'ratio':'9:16','language':'zh','sound':'original'},'instructions':'自然生活记录；保留关键过程、不添加广告标题字幕。','contract':CONTRACT,'missing':[],'ready':True}
ai_edit_conversation.request_json=response
def analyze(snap,owner,admin,jid):
    return [{**s,'language':'en','segments':[],'frames':[],'warning':'界面验收模拟分析，不代表真实识别'} for s in snap['source_info']]
def plan(snap,owner,admin,jid):
    return service.validate_plan({'summary':'界面验收模拟方案（没有调用真实模型）','shots':[{'source_id':sid,'start':0,'end':3,'purpose':'演示','reason':'固定验收片段，非 AI 分析','title':''}],'risks':['模拟数据，仅用于验证交互']},snap)
service.analyze=analyze;service.plan=plan
import ai_edit_vision
from test_ai_edit_general import REVIEW
def visual_response(service,jid,system,context,images):
    if 'required_checks' in context:return REVIEW
    return {'understanding':'【模拟素材理解】自然生活记录，不默认带货；采样不保证完整动作。','observations':[{'source_id':sid,'start':0,'end':3,'fact':'测试样片，用于验证交互','inference':'','uncertainty':'非真实模型判断'}],'inspect':[],'limitations':['模型响应全部模拟，未产生真实费用']}
ai_edit_vision.request=visual_response
@app.middleware('http')
async def auth(request,call_next):
    response=await call_next(request)
    if request.url.path=='/':response.set_cookie('hub_session',token,httponly=True,samesite='strict')
    return response
service.recover()
threading.Thread(target=service.loop,daemon=True).start()
threading.Thread(target=app.state.editor.loop,daemon=True).start()
print('Conversation UI fixture: http://127.0.0.1:8881 / isolated and model responses MOCKED',flush=True)
uvicorn.run(app,host='127.0.0.1',port=8881,access_log=False)
