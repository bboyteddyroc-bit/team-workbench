"""One synthetic image request and one synthetic video request; no retries."""
import sqlite3, json, base64, urllib.request, urllib.error
from pathlib import Path
from cryptography.fernet import Fernet
from a6_provider import build_request
root=Path(__file__).resolve().parent
state=root/'state';workspace=root.parents[2]
with sqlite3.connect('file:'+str(state/'hub.sqlite3')+'?mode=ro',uri=True) as db: row=db.execute('SELECT secret FROM a6_settings WHERE id=1').fetchone()
if not row: raise SystemExit('Missing A6 key')
key=Fernet((state/'vault.key').read_bytes()).decrypt(row[0]).decode()
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
opener=urllib.request.build_opener(NoRedirect)
def run(label,req):
 print(label,'START',flush=True)
 try:
  with opener.open(req,timeout=120) as response:
   d=json.loads(response.read(1000000)); print(label,'HTTP',response.status,'BODY',json.dumps(d,ensure_ascii=False)[:5000],flush=True)
 except urllib.error.HTTPError as e:
  try:
   raw=e.read(8192).decode('utf-8','replace'); obj=json.loads(raw); error=obj.get('error',{}); message=error.get('message','') if isinstance(error,dict) else ''
  except Exception: message=''
  print(label,'HTTP_ERROR',e.code,'MESSAGE',message[:500].replace(key,'[REDACTED]'),'REQUEST_ID',(e.headers.get('X-Oneapi-Request-Id') or '')[:100],flush=True)
 except Exception as e: print(label,'UNKNOWN',type(e).__name__,'NO RETRY',flush=True)
img=base64.b64encode((workspace/'a6_test_frames/frame_0000.png').read_bytes()).decode()
req=build_request(key,{'messages':[{'role':'user','content':[{'type':'text','text':'描述图片白色背景上的图形颜色、形状和位置。不要猜测。'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+img}}]}],'max_tokens':512,'stream':False})
run('IMAGE_OPENAI',req)
video=base64.b64encode((workspace/'a6_synthetic_test.mp4').read_bytes()).decode()
payload={'contents':[{'role':'user','parts':[{'text':'请描述视频中前后出现的图形、颜色、位置变化，按时间顺序回答。没有声音则说明没有声音。'}, {'inline_data':{'mime_type':'video/mp4','data':video}}]}], 'generationConfig':{'maxOutputTokens':512}}
req=urllib.request.Request('https://api.a6api.vip/v1beta/models/gemini-3.8-flash:generateContent',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key},method='POST')
run('VIDEO_GEMINI_NATIVE',req)
