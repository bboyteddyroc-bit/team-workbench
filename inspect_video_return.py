"""Read-only operational checks; no credentials/prompts."""
import json,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parent
with sqlite3.connect((root/'state'/'hub.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    result={}
    for table,column in [('tasks','state'),('libtv_jobs','state'),('ai_turns','status'),('edit_exports','state'),('voice_jobs','state')]:
        result[table]=dict(db.execute(f'SELECT {column},count(*) FROM {table} GROUP BY {column}'))
    result['libtv_details']=[dict(r) for r in db.execute('SELECT id,state,stage,project,asset_id,error,runner FROM libtv_jobs')]
    for row in result['libtv_details']:
        folder=root/'state'/'libtv'/row['id']/'download'
        row['cached_videos']=[{'bytes':p.stat().st_size} for p in folder.glob('*.mp4')]
    result['accounts']=[dict(r) for r in db.execute('SELECT id,status,enabled FROM accounts')]
print(json.dumps(result,ensure_ascii=False,indent=2))
