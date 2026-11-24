import psutil, sqlite3
from pathlib import Path
root=Path(__file__).resolve().parent
checks=[('tasks',"state='submitting' OR (state='running' AND (remote_id IS NULL OR remote_id=''))"),('voice_jobs',"state IN ('queued','running')"),('edit_exports',"state IN ('queued','rendering')"),('libtv_jobs',"state IN ('running','importing')"),('asset_classification',"status='running'"),('ai_turns',"status='pending'")]
with sqlite3.connect(root/'state/hub.sqlite3',timeout=10) as db:
    db.execute('BEGIN IMMEDIATE')
    for table,cond in checks:
        if db.execute('SELECT count(*) FROM '+table+' WHERE '+cond).fetchone()[0]: raise RuntimeError('Active work in '+table+'; restart cancelled')
    ports={c.pid for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port in (8765,8443)}
    processes=[]
    for pid in ports:
        p=psutil.Process(pid)
        if Path(p.cwd()).resolve()!=root or 'run_service.py' not in p.cmdline(): raise RuntimeError('Unexpected listener; restart cancelled')
        processes.append(p)
    if len(processes)!=2: raise RuntimeError('Expected both services; restart cancelled')
    for p in processes: p.terminate()
    gone,alive=psutil.wait_procs(processes,timeout=10)
    if alive: raise RuntimeError('Could not stop services: '+str([p.pid for p in alive]))
    db.rollback()
    print('Stopped verified listeners:',[p.pid for p in gone])
