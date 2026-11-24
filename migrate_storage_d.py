"""One-time storage migration. Keeps original directories as backups; aborts on active work."""
import hashlib, os, shutil, sqlite3, subprocess, sys
from pathlib import Path
import psutil

root=Path(__file__).resolve().parent
state=root/'state'
target=Path(r'D:\SeedanceHubData')
names=('media','assets','edits','edit_footage','voice','libtv')
checks=[('tasks',"state='submitting' OR (state='running' AND (remote_id IS NULL OR remote_id=''))"),('voice_jobs',"state IN ('queued','running')"),('edit_exports',"state IN ('queued','rendering')"),('libtv_jobs',"state IN ('running','importing')"),('asset_classification',"status='running'"),('ai_turns',"status='pending'")]
python=root/'.venv/Scripts/python.exe'

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.digest()
def manifest(p):
    return {q.relative_to(p):q for q in p.rglob('*') if q.is_file()}
def launch():
    for mode in ('local','lan'):
        subprocess.Popen([str(python),'-B','run_service.py',mode],cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    print('Service start requested',flush=True)

if target.exists(): raise SystemExit('Target already exists; refusing to overwrite: '+str(target))
for n in names:
    p=state/n
    if not p.is_dir() or p.is_symlink() or (state/(n+'.before-d-migration')).exists(): raise SystemExit('Unexpected source or backup exists: '+str(p))
    for d,ds,fs in os.walk(p):
        if any((Path(d)/x).is_symlink() for x in ds+fs): raise SystemExit('Unexpected link inside source: '+d)
if shutil.disk_usage(target.anchor).free < sum(q.stat().st_size for n in names for q in (state/n).rglob('*') if q.is_file()) + 2*1024**3: raise SystemExit('Insufficient destination space')
with sqlite3.connect(state/'hub.sqlite3',timeout=10) as db:
    db.execute('BEGIN IMMEDIATE')
    for table,condition in checks:
        if db.execute('SELECT count(*) FROM '+table+' WHERE '+condition).fetchone()[0]: raise SystemExit('Active work in '+table+'; nothing changed')
    pids={c.pid for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port in (8765,8443)}
    services=[]
    for pid in pids:
        p=psutil.Process(pid)
        if Path(p.cwd()).resolve()!=root or 'run_service.py' not in p.cmdline(): raise SystemExit('Unexpected service identity; nothing changed')
        services.append(p)
    if len(services)!=2: raise SystemExit('Expected two service processes; nothing changed')
    for p in services:p.terminate()
    _,alive=psutil.wait_procs(services,timeout=15)
    if alive: raise SystemExit('Could not stop services; inspect before restarting: '+str([p.pid for p in alive]))
    db.rollback()
print('Services stopped safely; copying',flush=True)
switched=[]
try:
    target.mkdir()
    for n in names:
        src=state/n;dst=target/n
        shutil.copytree(src,dst,copy_function=shutil.copy2)
        a,b=manifest(src),manifest(dst)
        if a.keys()!=b.keys(): raise RuntimeError('File list mismatch: '+n)
        for k in a:
            if digest(a[k])!=digest(b[k]): raise RuntimeError('File hash mismatch: '+n+'/'+str(k))
        print('Verified',n,len(a),'files',flush=True)
    for n in names:
        src=state/n;backup=state/(n+'.before-d-migration');dst=target/n
        src.rename(backup)
        try:
            subprocess.run(['cmd','/c','mklink','/J',str(src),str(dst)],check=True,capture_output=True,text=True)
            if src.resolve()!=dst.resolve(): raise RuntimeError('Junction target mismatch: '+n)
            switched.append(n)
        except BaseException:
            if src.exists() or src.is_symlink(): os.rmdir(src)
            backup.rename(src)
            raise
    print('All paths switched to',target,flush=True)
except BaseException:
    for n in reversed(switched):
        os.rmdir(state/n);(state/(n+'.before-d-migration')).rename(state/n)
    print('Migration aborted; original paths restored. Destination copy retained for inspection.',flush=True)
    raise
finally:
    launch()
