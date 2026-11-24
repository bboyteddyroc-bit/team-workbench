"""One explicitly requested existing case. Idempotent queue insertion; never repeats a call."""
from pathlib import Path
import json,time,uuid
from app import create_app
from video_case_kalodata import period
root=Path(__file__).resolve().parent
app=create_app(root/'state',worker=False);hub=app.state.hub
with hub.db() as db:
    db.execute('BEGIN IMMEDIATE')
    row=db.execute("SELECT * FROM video_cases WHERE video='7704642505480129822'").fetchone()
    if not row:raise RuntimeError('Requested existing case no longer present; no job queued')
    key='user-case-video-analysis-20261116:'+row['id']
    existing=db.execute('SELECT id,state FROM video_case_jobs WHERE request_key=?',(key,)).fetchone()
    if existing:print(json.dumps({'existing':True,**dict(existing)}),flush=True)
    elif db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND state IN ('queued','submitting','running')",(row['id'],)).fetchone():
        print('Existing active case work; no duplicate queued',flush=True)
    else:
        jid=uuid.uuid4().hex;now=time.time()
        db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'analysis','queued',?,?,?,?)",(jid,row['id'],row['created_by'],key,now,now,json.dumps({'consent':'current user requested video analysis; separate from failed metadata query'})))
        hub.log(db,row['created_by'],'video_case_processing','kalodata:'+row['id'])
        print(json.dumps({'id':jid,'state':'queued','video':row['video'],'automatic_analysis_after_data':True}),flush=True)
