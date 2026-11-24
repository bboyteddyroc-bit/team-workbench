"""Local read-only diagnosis; never submits generation or writes account state."""
import json,os,sqlite3,urllib.request,re
from pathlib import Path
from cryptography.fernet import Fernet
from provider import TikTok,QUERY
root=Path(__file__).resolve().parent
report={'checks':[]}
try:
 db=sqlite3.connect((root/'state/hub.sqlite3').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 task=db.execute("SELECT id,account_id,state,remote_id FROM tasks WHERE error LIKE '%1001200%' ORDER BY created DESC LIMIT 1").fetchone()
 report['task_found']=bool(task)
 if task:report['task']=dict(task)
 rows=db.execute("SELECT id,secret,status FROM accounts WHERE scope='shared' AND enabled=1").fetchall()
 report['account_count']=len(rows)
 cipher=Fernet((root/'state/vault.key').read_bytes())
 for row in rows:
  headers=json.loads(cipher.decrypt(row['secret']))
  client=TikTok(os.getenv('HUB_PROXY','http://127.0.0.1:7890'))
  checks=[('account','https://ads.tiktok.com/CreativeOne/Client/ClientGetAccountInfo'+QUERY,None),('history','https://ads.tiktok.com/creative_bff_i18n/api/cue/history/tasks'+QUERY,dict(pageOffset=0,pageLimit=1,edited=False,sorted=2,mini_app_type=[2,3,11,13,18,19],parseSettings=True,showPlayInfo=True))]
  for name,url,payload in checks:
   result={'endpoint':name,'account_id':row['id'],'saved_status':row['status']}
   try:
    req=urllib.request.Request(url,headers=headers,data=json.dumps(payload).encode() if payload else None)
    with client.opener.open(req,timeout=30) as r:
     data=json.loads(r.read(2000000));result['http']=r.status
    base=data.get('BaseResp') or {}
    result['code']=data.get('code',base.get('StatusCode'))
    msg=str(data.get('message') or data.get('msg') or base.get('StatusMessage') or '')
    # Error text only: redact request credentials if echoed, plus links and token-like strings.
    for key in ('cookie','x-csrftoken','x-fp-id'):
     if headers.get(key):msg=msg.replace(headers[key],'[redacted]')
    result['message']=re.sub(r'https?://\S+|[A-Za-z0-9_=/+-]{40,}','[redacted]',msg)[:400]
   except Exception as exc:result['failure_type']=type(exc).__name__
   report['checks'].append(result)

except Exception as exc:report['failure_type']=type(exc).__name__
output=root/'account-diagnostic-result.json';output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Diagnostic saved:',output)
