"""Migration into a fresh destination; preserves originals and skips four approved exports."""
import hashlib, os, shutil, sqlite3, subprocess
from pathlib import Path
import psutil
root=Path(__file__).resolve().parent; state=root/'state'; target=Path(r'D:\SeedanceHubData-migrated')
names=('media','assets','edits','edit_footage','voice','libtv')
skip={Path('edits')/(x+'.mp4') for x in ('248c764f09667e19b192280a','2731192f97d75558ebef4234','ba441fd9109676b0a6cb9f6c','ff2746ce007ed849e7699a58')}
checks=[('tasks',"state='submitting' OR (state='running' AND (remote_id IS NULL OR remote_id=''))"),('voice_jobs',"state IN ('queued','running')"),('edit_exports',"state IN ('queued','rendering')"),('libtv_jobs',"state IN ('running','importing')"),('asset_classification',"status='running'"),('ai_turns',"status='pending'")]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.digest()
def launch():
 for mode in ('local','lan'):
  subprocess.Popen([str(root/'.venv/Scripts/python.exe'),'-B','run_service.py',mode],cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
 print('Start requested',flush=True)
if target.exists():raise SystemExit('Destination exists; no changes')
for n in names:
 p=state/n
 if not p.is_dir() or p.resolve()!=p.absolute() or (state/(n+'.before-d-migration')).exists():raise SystemExit('Unexpected source or backup '+str(p))
 for d,ds,fs in os.walk(p):
  if any((Path(d)/x).is_symlink() for x in ds+fs):raise SystemExit('Unexpected link '+d)
if shutil.disk_usage(target.anchor).free < sum(q.stat().st_size for n in names for q in (state/n).rglob('*') if q.is_file())+2*1024**3:raise SystemExit('Insufficient space')
with sqlite3.connect(state/'hub.sqlite3',timeout=10) as db:
 db.execute('BEGIN IMMEDIATE')
 for t,c in checks:
  if db.execute('SELECT count(*) FROM '+t+' WHERE '+c).fetchone()[0]:raise SystemExit('Active work: '+t)
 pids={c.pid for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port in (8765,8443)}
 procs=[]
 for pid in pids:
  p=psutil.Process(pid)
  if Path(p.cwd()).resolve()!=root or 'run_service.py' not in p.cmdline():raise SystemExit('Unexpected listener')
  procs.append(p)
 if len(procs)!=2:raise SystemExit('Expected two listeners')
 for p in procs:p.terminate()
 _,alive=psutil.wait_procs(procs,timeout=15)
 if alive:raise SystemExit('Unable to stop all listeners; inspect')
 db.rollback()
print('Stopped services, copying',flush=True)
switched=[]
try:
 target.mkdir()
 for n in names:
  src=state/n;dst=target/n
  def ignore(folder, entries):
   return [x for x in entries if (Path(folder)/x).relative_to(state) in skip]
  shutil.copytree(src,dst,ignore=ignore,copy_function=shutil.copy2)
  a={q.relative_to(src):q for q in src.rglob('*') if q.is_file() and q.relative_to(state) not in skip}
  b={q.relative_to(dst):q for q in dst.rglob('*') if q.is_file()}
  if a.keys()!=b.keys():raise RuntimeError('File list mismatch '+n)
  for k in a:
   if sha(a[k])!=sha(b[k]):raise RuntimeError('Hash mismatch '+str(a[k]))
  print('Verified',n,len(a),'files',flush=True)
 for n in names:
  src=state/n;backup=state/(n+'.before-d-migration');dst=target/n
  src.rename(backup)
  try:
   subprocess.run(['cmd','/c','mklink','/J',str(src),str(dst)],check=True,capture_output=True,text=True)
   if src.resolve()!=dst.resolve():raise RuntimeError('Junction target mismatch '+n)
   switched.append(n)
  except BaseException:
   if src.exists() or src.is_symlink():os.rmdir(src)
   backup.rename(src);raise
 print('SWITCHED',target,flush=True)
except BaseException:
 for n in reversed(switched):os.rmdir(state/n);(state/(n+'.before-d-migration')).rename(state/n)
 print('Restored original paths; partial destination retained',flush=True)
 raise
finally:launch()
