"""Locally reparse a completed AI response; no upstream calls. Fixed completed job only."""
from pathlib import Path
import json,time
from app import create_app
from video_case_analysis import parse_json_answer,clean,save_answer
root=Path(__file__).resolve().parent
app=create_app(root/'state',worker=False);hub=app.state.hub
jid='f045c3e166fe4fa3b2a1e199436604d8'
with hub.db() as db:
    job=db.execute('SELECT * FROM video_case_jobs WHERE id=?',(jid,)).fetchone()
    case=db.execute('SELECT * FROM video_cases WHERE id=?',(job['case_id'],)).fetchone()
    if job['state']=='ready':print('Already recovered; no mutation');raise SystemExit(0)
    if job['state']!='attention':raise RuntimeError('Unexpected job state')
p=root/'state/case-analysis'/case['id']/(jid+'-answer.txt')
raw=parse_json_answer(p.read_text(encoding='utf-8'));save_answer(hub,case['id'],jid,raw)
transcript=json.loads(case['human']).get('transcript') or case['transcript']
fields,evidence,uncertain=clean(raw,transcript,True)
packed={'fields':fields,'evidence':evidence,'uncertainties':uncertain+['原回答含未转义引号，已仅做本地JSON转义修复；未重新调用AI'],'generated_at':time.time(),'basis':'Kalodata视频9帧采样 + 本地ASR','policy':'case-review-v2'}
with hub.db() as db:
    db.execute('BEGIN IMMEDIATE');now=time.time()
    db.execute('UPDATE video_cases SET ai=?,updated=? WHERE id=?',(json.dumps(packed,ensure_ascii=False),now,case['id']))
    db.execute("UPDATE video_case_jobs SET state='ready',updated=?,error='' WHERE id=? AND state='attention'",(now,jid))
app.state.video_cases.checkpoint(jid,'已从保留原稿本地恢复并初填，待人工审核')
print(json.dumps({'video':case['video'],'filled_fields':[k for k,v in fields.items() if v],'local_recovery_only':True},ensure_ascii=True),flush=True)
