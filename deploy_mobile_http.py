"""One-off deploy with active-work and exact process-identity checks; no blind force/retry."""
from pathlib import Path
import psutil,sqlite3,subprocess,uuid
root=Path(__file__).resolve().parent
runtime=root/'.venv/Scripts/python.exe'
if not runtime.is_file():raise RuntimeError('Missing project Python')
for directory in ('edits','edit_footage','assets','media-cache','libtv','libtv-profiles','voice/audio','voice/samples'):
    p=root/'state'/directory/('startup-check-'+uuid.uuid4().hex)
    try:p.mkdir();(p/'check').write_bytes(b'ok')
    finally:
        if p.exists():(p/'check').unlink(missing_ok=True);p.rmdir()
with sqlite3.connect(root/'state/hub.sqlite3',timeout=10) as db:
    db.execute('BEGIN IMMEDIATE')
    conditions={
      'tasks':"state='submitting' OR (state='running' AND (remote_id IS NULL OR remote_id=''))",
      'voice_jobs':"state IN ('queued','running')",
      'edit_exports':"state IN ('queued','rendering')",
      'libtv_jobs':"state IN ('running','importing')",
      'asset_classification':"status='running'",
      'ai_turns':"status='pending'",
      'feishu_uploads':"state='uploading'",
      'kalodata_jobs':"state='running'",
    }
    for table,condition in conditions.items():
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
            count=db.execute('SELECT COUNT(*) FROM '+table+' WHERE '+condition).fetchone()[0]
            if count:raise RuntimeError('Active work in '+table+'; no service stopped')
    services=[]
    for pid in {c.pid for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port in (8765,8443,8000)}:
        p=psutil.Process(pid);entries=[Path(a) for a in p.cmdline() if a.endswith('.py')]
        if Path(p.cwd()).resolve()!=root or not any((e if e.is_absolute() else root/e).resolve()==root/'run_service.py' for e in entries):
            raise RuntimeError('Unexpected listener; no service stopped')
        services.append(p)
    print('No critical active jobs. Verified service PIDs:',[p.pid for p in services],flush=True)
    for p in services:p.terminate()
    _,alive=psutil.wait_procs(services,timeout=10)
    if alive:raise RuntimeError('Service did not stop; no duplicate launched')
    db.rollback()
for mode in ('local','lan'):
    with (root/f'state/restart-{mode}.out.log').open('ab') as out,(root/f'state/restart-{mode}.err.log').open('ab') as err:
        p=subprocess.Popen([str(runtime),'-B','run_service.py',mode],cwd=root,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    print('Started',mode,'PID',p.pid,flush=True)
print('Deployment launched; verify HTTP8000 and HTTPS8443 independently next.',flush=True)
