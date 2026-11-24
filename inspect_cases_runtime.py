"""Read-only current case-library/runtime facts; never prints credentials."""
from pathlib import Path
import sqlite3,json,psutil
root=Path(__file__).resolve().parent
print('project',str(root),flush=True)
print('database',str((root/'state/hub.sqlite3').resolve()),flush=True)
with sqlite3.connect('file:'+str(root/'state/hub.sqlite3').replace('\\','/')+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    print('cases',json.dumps([dict(r) for r in db.execute('SELECT id,video,handle,platform FROM video_cases')]),flush=True)
    print('kalodata_saved_config_count',db.execute('SELECT count(*) FROM kalodata_config').fetchone()[0],flush=True)
    print('case_jobs',json.dumps([dict(r) for r in db.execute('SELECT kind,state,count(*) count FROM video_case_jobs GROUP BY kind,state')]),flush=True)
for c in psutil.net_connections(kind='tcp'):
    if c.status=='LISTEN' and c.laddr.port in (8765,8443):
        p=psutil.Process(c.pid);print('listener',c.laddr.port,p.pid,p.cwd(),p.cmdline(),flush=True)
