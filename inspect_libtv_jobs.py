"""Read-only listing of LibTV jobs for diagnosis."""
import sqlite3, sys
from pathlib import Path

db = Path(__file__).resolve().parent / 'state' / 'hub.sqlite3'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
con.row_factory = sqlite3.Row
rows = con.execute("SELECT id,owner,state,stage,project,asset_id,error,created,updated FROM libtv_jobs ORDER BY created DESC LIMIT 12").fetchall()
for r in rows:
    d = dict(r)
    print(d['id'], '|', d['owner'], '|', d['state'], '|', d['project'], '|', d['asset_id'] or '-', '|', d['stage'])
    if d['error']:
        print('   error:', d['error'][:300])
print('total', len(rows))
