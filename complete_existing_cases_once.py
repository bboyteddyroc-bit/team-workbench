"""User-requested completion of existing cases after the diagnosed CDN fix.
Queues analysis only, never repeats already failed detail lookups. Idempotent per case.
"""
from pathlib import Path
import json,time,uuid
from app import create_app
import asr
root=Path(__file__).resolve().parent
app=create_app(root/'state',worker=False);hub=app.state.hub
if not asr.configured_key(hub):raise RuntimeError('Agnes not configured; no paid jobs queued')
with hub.db() as db:
    db.execute('BEGIN IMMEDIATE')
    result=[]
    for video in ('7704642505480129822','7708328890967608590'):
        row=db.execute('SELECT * FROM video_cases WHERE video=?',(video,)).fetchone()
        if not row:continue
        key='user-complete-cases-20261116-v1:'+row['id']
        old=db.execute('SELECT id,state FROM video_case_jobs WHERE request_key=?',(key,)).fetchone()
        if old:result.append({'video':video,'existing':dict(old)});continue
        if db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND state IN ('queued','submitting','running')",(row['id'],)).fetchone():
            result.append({'video':video,'skipped':'already active'});continue
        ai=json.loads(row['ai'])
        if any(v for k,v in ai.get('fields',{}).items() if k not in ('notes','tags','basis')):
            result.append({'video':video,'skipped':'substantive analysis already exists'});continue
        now=time.time();jid=uuid.uuid4().hex
        db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'analysis','queued',?,?,?,?)",(jid,row['id'],row['created_by'],key,now,now,json.dumps({'consent':'user: 全部做完 并且把界面做一下调整','release':'CDN domain fix verified','metadata_retry':False},ensure_ascii=False)))
        hub.log(db,row['created_by'],'video_case_processing','analysis:'+row['id'])
        result.append({'video':video,'id':jid,'state':'queued'})
print(json.dumps(result,ensure_ascii=True),flush=True)
