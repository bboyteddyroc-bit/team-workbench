import sys,json,urllib.request,urllib.error
from pathlib import Path
import sqlite3
from cryptography.fernet import Fernet
from a6_provider import build_request
root=Path(__file__).resolve().parent
state=root/'state'
with sqlite3.connect('file:'+str(state/'hub.sqlite3')+'?mode=ro',uri=True) as db: row=db.execute('SELECT secret FROM a6_settings WHERE id=1').fetchone()
if not row: print('RESULT: key not configured');sys.exit(1)
key=Fernet((state/'vault.key').read_bytes()).decrypt(row[0]).decode()
req=build_request(key,{'messages':[{'role':'user','content':'请只回复：测试成功'}],'max_tokens':128,'stream':False})
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
try:
 with urllib.request.build_opener(NoRedirect).open(req,timeout=90) as resp:
  status=resp.status; data=json.loads(resp.read(1000000))
  choice=(data.get('choices') or [{}])[0];msg=choice.get('message') or {}
  print('HTTP:',status,'RESPONSE_MODEL:',str(data.get('model','unknown'))[:120],'FINISH:',str(choice.get('finish_reason','unknown')),'ANSWER:',str(msg.get('content',''))[:300])
except urllib.error.HTTPError as e: print('HTTP_ERROR:',e.code,'REQUEST_ID:',(e.headers.get('X-Oneapi-Request-Id') or '')[:100])
except Exception as e: print('RESULT_UNKNOWN:',type(e).__name__,'No automatic retry')
