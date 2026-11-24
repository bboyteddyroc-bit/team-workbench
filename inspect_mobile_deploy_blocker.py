"""Read only aggregate running-job status, without member names, credentials or content."""
from pathlib import Path
import sqlite3,time,psutil,json
root=Path(__file__).resolve().parent
with sqlite3.connect('file:'+str(root/'state/hub.sqlite3')+'?mode=ro',uri=True,timeout=10) as db:
    db.row_factory=sqlite3.Row
    rows=db.execute("SELECT state,stage,runner,created,updated FROM libtv_jobs WHERE state IN ('running','importing')").fetchall()
    print(json.dumps([{'state':r['state'],'stage':r['stage'],'runner_alive':psutil.pid_exists(r['runner'] or -1),'age_seconds':round(time.time()-r['created']),'idle_seconds':round(time.time()-r['updated'])} for r in rows],ensure_ascii=False),flush=True)
