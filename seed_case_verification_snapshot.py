"""Copy only the two shared case records into isolated worker-disabled UI verification state.
No production users, sessions, keys, private jobs or settings are read or copied.
"""
from pathlib import Path
import json,sqlite3,shutil,time
root=Path(__file__).resolve().parent;target=root/'verification/cases-preview-state'
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as prod:
    prod.row_factory=sqlite3.Row
    cases=[dict(prod.execute('SELECT * FROM video_cases WHERE id=?',(cid,)).fetchone()) for cid in ('430532be99864aae9e0ef6ec35279a85','8fafffdff2984e2c937aace19a8aba5d')]
with sqlite3.connect(target/'hub.sqlite3') as db:
    for row in cases:
        row.update(created_by='case-preview',updated_by='case-preview',library_id=None)
        columns=list(row)
        db.execute('INSERT INTO video_cases('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+') ON CONFLICT(id) DO UPDATE SET source=excluded.source,ai=excluded.ai,human=excluded.human,transcript=excluded.transcript,transcript_source=excluded.transcript_source,updated=excluded.updated',tuple(row[k] for k in columns))
        db.execute('INSERT OR IGNORE INTO video_case_members VALUES(?,?,?)',(row['id'],'case-preview',time.time()))
        covers=target/'case-covers';covers.mkdir(exist_ok=True);shutil.copyfile(root/'state/case-covers'/(row['id']+'.img'),covers/(row['id']+'.img'))
    db.execute("UPDATE video_cases SET ai=? WHERE id='demo-b'",(json.dumps({'fields':{'summary':'界面功能验收用AI初稿','replication_actions':'仅演示保存/审核，不是真实分析','tags':['隔离验收']},'evidence':{},'uncertainties':['隔离界面样例，不用于业务决策'],'basis':'隔离功能样例','generated_at':time.time()},ensure_ascii=False),))
print('Isolated real-shared-case snapshot prepared; production untouched; no secrets copied',flush=True)
