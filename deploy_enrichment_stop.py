"""Guarded stop only. Managed jobs start the services separately after this succeeds."""
import sqlite3
from pathlib import Path
import psutil
root=Path(__file__).resolve().parent
checks={'tasks':"state IN ('queued','submitting','running')",'voice_jobs':"state IN ('queued','running')",'edit_exports':"state IN ('queued','rendering')",'libtv_jobs':"state IN ('queued','running','importing')",'asset_classification':"status='running'",'ai_turns':"status='pending'",'feishu_uploads':"state IN ('queued','uploading')",'kalodata_jobs':"state IN ('queued','running')",'apify_runs':"state IN ('queued','submitting','running')",'video_enrichment_jobs':"state='running'"}
with sqlite3.connect(root/'state/hub.sqlite3',timeout=10) as db:
    db.execute('BEGIN IMMEDIATE')
    for table,condition in checks.items():
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
            if db.execute('SELECT COUNT(*) FROM '+table+' WHERE '+condition).fetchone()[0]:
                raise RuntimeError('Active work; no restart: '+table)
    for table, condition in [('script_creative_tasks', "state='generating'"), ('script_enrichment', "state='running'"), ('script_transcriptions', "state='running'"), ('video_case_jobs', "state IN ('queued','submitting','running')"), ('ai_edit_jobs', "state IN ('queued','planning','running','rendering')"), ('grouped_runs', "state IN ('queued','submitting','running')")]:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() and db.execute('SELECT COUNT(*) FROM '+table+' WHERE '+condition).fetchone()[0]:
            raise RuntimeError('Active work; no restart: '+table)
    services=[]
    for c in psutil.net_connections(kind='tcp'):
        if c.status=='LISTEN' and c.laddr.port in (8765,8443):
            p=psutil.Process(c.pid)
            if Path(p.cwd()).resolve()!=root or not any(Path(arg).name == 'run_service.py' for arg in p.cmdline()):
                raise RuntimeError('Unexpected listener; no restart')
            services.append(p)
    for p in services:p.terminate()
    gone,alive=psutil.wait_procs(services,timeout=15)
    if alive:raise RuntimeError('Services did not stop; do not start duplicates')
print('Verified idle services stopped:',len(gone),flush=True)
