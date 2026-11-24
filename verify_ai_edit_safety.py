"""Read-only production activity check; never changes job state or credentials."""
import sqlite3,json
from pathlib import Path
root=Path(__file__).resolve().parent
checks={}
with sqlite3.connect((root/'state/hub.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    for table,field,states in [('tasks','state',['submitting','running']),('libtv_jobs','state',['submitting','running','importing']),('ai_turns','status',['pending']),('edit_exports','state',['rendering']),('voice_jobs','state',['running','submitting']),('asset_classification','status',['running']),('apify_runs','state',['running','submitting'])]:
        cols={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
        if field in cols:checks[table]=db.execute('SELECT count(*) FROM '+table+' WHERE '+field+' IN ('+','.join('?' for _ in states)+')',states).fetchone()[0]
print(json.dumps(checks))
print('SAFE_TO_RESTART' if not any(checks.values()) else 'DEFER_RESTART')
