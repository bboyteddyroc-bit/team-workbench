"""Explicit one-shot diagnosis. Fixed receipt prevents accidental repeated paid calls.
No credentials, raw URLs, signatures, headers or private manual-query history emitted.
"""
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit
import json,re,sys,httpx
from app import create_app

root=Path(__file__).resolve().parent
receipt=root/'verification/kalodata-case-diagnosis-20261116.json'
if receipt.exists():
    print('Existing diagnostic receipt; no requests repeated. '+str(receipt),flush=True)
    raise SystemExit(0)
app=create_app(root/'state',worker=False);service=app.state.kalodata
with app.state.hub.db() as db:
    case=db.execute("SELECT id,video,handle FROM video_cases WHERE video='7704642505480129822'").fetchone()
    job=db.execute("SELECT options FROM video_case_jobs WHERE case_id=? AND kind='kalodata' ORDER BY created DESC LIMIT 1",(case['id'],)).fetchone()
    if db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE case_id=? AND state IN ('queued','submitting','running')",(case['id'],)).fetchone()[0]:raise RuntimeError('Case already processing; diagnostic not sent')
options=json.loads(job['options']);secret=service.secret()
if not secret:raise RuntimeError('No configured credential; no request sent')
result={'created':datetime.now(timezone.utc).isoformat(),'video':case['video'],'results':[]}
receipt.parent.mkdir(exist_ok=True)
with receipt.open('x',encoding='utf-8') as f:json.dump(result,f)
def save():receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
def safe_message(value):
    text=str(value or '')[:4000].replace(secret,'[REDACTED]')
    text=re.sub(r'https?://\S+','[URL]',text)
    text=re.sub(r'(?i)(token|secret|password|signature|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+',r'\1=[REDACTED]',text)
    return ''.join(c for c in text if c in '\n\t' or ord(c)>=32)[:600]
requests=[('/video/detail',dict(region='US',language='en-US',currency='USD',date_range=options['period_start']+'~'+options['period_end'],video_id=case['video'],need_extra=False)),('/video/url',{'video_id':case['video']})]
for endpoint,payload in requests:
    row={'endpoint':endpoint,'request':payload,'state':'attempted_no_replay'};result['results'].append(row);save()
    try:
        with httpx.Client(timeout=30,trust_env=False,follow_redirects=False) as client:
            response=client.post('https://www.kalodata.com/openapi/v1/tiktok'+endpoint,json=payload,headers={'secret-key':secret})
        row['http_status']=response.status_code
        try:raw=response.json()
        except ValueError:row['state']='non_json';save();continue
        if not isinstance(raw,dict):row['state']='non_object';save();continue
        row.update(state='response_received',success=raw.get('success') if isinstance(raw.get('success'),(bool,int,str)) else None,code=safe_message(raw.get('code')),message=safe_message(raw.get('message')),top_level_fields=list(raw)[:30])
        data=raw.get('data');row['data_type']=type(data).__name__
        if isinstance(data,dict):
            row['data_fields']=list(data)[:60]
            row['returned_id_matches']=str(data.get('video_id',''))==case['video']
            if endpoint=='/video/detail':
                row['returned_region']=safe_message(data.get('video_region'))
                row['returned_handle_matches']=str(data.get('belonged_creator_handle','')).lower().lstrip('@')==case['handle'].lower()
                row['nonempty_fields']=[k for k,v in data.items() if v is not None and v!=''][:60]
            else:
                url=data.get('video_url');row['video_url_type']=type(url).__name__
                if isinstance(url,str):
                    parsed=urlsplit(url);row['url_scheme']=parsed.scheme;row['url_hostname']=parsed.hostname;row['url_length']=len(url);row['has_query']=bool(parsed.query)
        save()
    except Exception as exc:
        row['state']='outcome_unknown';row['exception_type']=type(exc).__name__;save()
print(json.dumps(result,ensure_ascii=True,indent=2),flush=True)
