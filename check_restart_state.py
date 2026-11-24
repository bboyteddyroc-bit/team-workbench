"""Read-only aggregate preflight; no secrets, prompts or filenames."""
import json
import sqlite3
from pathlib import Path
root=Path(__file__).resolve().parent
with sqlite3.connect((root/'state'/'hub.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=10) as db:
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    report={}
    for table in ('tasks','edit_exports','voice_jobs'):
        if table in tables:
            report[table]=dict(db.execute('SELECT state,count(*) FROM '+table+' GROUP BY state'))
    print(json.dumps(report,ensure_ascii=False,indent=2))
