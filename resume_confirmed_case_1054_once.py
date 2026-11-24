"""One-time repair of the single explicitly diagnosed historical 1054 job.
Does not call any provider. Re-arms the SAME job, transactionally, with a durable receipt.
Unknown historical failures and video/detail not-found records are not changed.
"""
import json,time,sqlite3
from pathlib import Path
from video_case_recovery import defer
root=Path(__file__).resolve().parent
jid='a57bca742d2c436fa8a6747bb4be1f39';cid='2d9151c8a5844d73905644031f330ee7'
with sqlite3.connect(root/'state/hub.sqlite3',timeout=15) as db:
    db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE')
    db.execute('CREATE TABLE IF NOT EXISTS video_case_recovery_repairs(job TEXT PRIMARY KEY,created REAL NOT NULL,reason TEXT NOT NULL)')
    if db.execute('SELECT 1 FROM video_case_recovery_repairs WHERE job=?',(jid,)).fetchone():
        print('Repair already recorded; not re-armed');raise SystemExit(0)
    case=db.execute('SELECT video,human,ai FROM video_cases WHERE id=?',(cid,)).fetchone()
    job=db.execute('SELECT * FROM video_case_jobs WHERE id=? AND case_id=?',(jid,cid)).fetchone()
    stage=db.execute('SELECT stage FROM video_case_checkpoints WHERE job=?',(jid,)).fetchone()
    assert case and case['video']=='7693645068875418901'
    assert job and job['state']=='attention' and job['kind']=='analysis'
    assert stage and stage[0]=='获取 Kalodata 视频地址'
    assert '错误码 1054' in job['error'] and '视频尚未缓存' in job['error']
    assert not db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND kind='analysis' AND state IN ('queued','submitting','running','waiting')",(cid,)).fetchone()
    # Known provider cache waiting was confirmed previously; first new check is due now.
    now=time.time();defer(db,jid,now)
    db.execute('UPDATE video_case_jobs SET next_attempt=? WHERE id=?',(now,jid))
    db.execute('INSERT OR REPLACE INTO video_case_checkpoints(job,stage,updated) VALUES(?,?,?)',(jid,'等待供应商视频缓存',now))
    db.execute('INSERT INTO video_case_recovery_repairs(job,created,reason) VALUES(?,?,?)',(jid,now,'Current user requested recovery; exact historical /video/url 1054 verified. Same job, no metadata replay.'))
print(json.dumps({'job':jid,'state':'waiting','same_job':True,'detail_job_replayed':False,'provider_called_by_repair':False}),flush=True)
