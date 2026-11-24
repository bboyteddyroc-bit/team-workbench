"""One-off explicitly requested restart; preserves default safe restart policy elsewhere."""
from pathlib import Path
import subprocess,sqlite3,psutil,uuid

def main():
    root=Path(__file__).resolve().parent
    runtime=root/'.venv/Scripts/python.exe'
    if not runtime.is_file():raise RuntimeError('Missing project runtime')
    services=[]
    for pid in {c.pid for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port in (8765,8443)}:
        p=psutil.Process(pid)
        entries=[Path(a) for a in p.cmdline() if a.endswith('.py')]
        if Path(p.cwd()).resolve()!=root or not any((e if e.is_absolute() else root/e).resolve()==root/'run_service.py' for e in entries):
            raise RuntimeError('Unexpected process on service port; nothing stopped')
        services.append(p)
    print('Verified service PIDs:',sorted(p.pid for p in services),flush=True)
    with sqlite3.connect('file:'+str(root/'state/hub.sqlite3')+'?mode=ro',uri=True,timeout=10) as db:
        active=db.execute("SELECT count(*) FROM libtv_jobs WHERE state IN ('running','importing')").fetchone()[0]
    print('Active LibTV jobs:',active,'; restarting as explicitly requested. No manual job-state edits.',flush=True)
    for directory in ('edits','edit_footage','assets','media-cache','libtv','libtv-profiles','voice/audio','voice/samples'):
        probe=root/'state'/directory/('startup-check-'+uuid.uuid4().hex)
        try:
            probe.mkdir();(probe/'write-check').write_bytes(b'ok')
        finally:
            if probe.exists():
                (probe/'write-check').unlink(missing_ok=True);probe.rmdir()
    for p in services:p.terminate()
    _,alive=psutil.wait_procs(services,timeout=10)
    if alive:raise RuntimeError('Service did not stop; no duplicate started')
    for mode in ('local','lan'):
        with (root/f'state/restart-{mode}.out.log').open('ab') as out,(root/f'state/restart-{mode}.err.log').open('ab') as err:
            p=subprocess.Popen([str(runtime),'-B','run_service.py',mode],cwd=root,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        print('Started',mode,'PID',p.pid,flush=True)
    print('Launch completed; independently verify both HTTP endpoints next.',flush=True)

if __name__=='__main__':main()
