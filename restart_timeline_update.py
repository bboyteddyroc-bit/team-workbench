"""User-run restart: refuse active jobs and verify service identity before stopping."""
import sqlite3
import subprocess
import time
from pathlib import Path
import psutil


def main():
    root = Path(__file__).resolve().parent
    runtime = root / '.venv/Scripts/python.exe'
    if not runtime.is_file():
        raise RuntimeError('Missing project Python runtime')
    # Check inherited sandbox permissions before stopping a healthy service.
    import uuid
    import sys
    enable_proxy = sys.argv[1:] == ['--enable-preview-proxy']
    preserve_remote = sys.argv[1:] == ['--preserve-remote-tasks']
    if sys.argv[1:] and not (enable_proxy or preserve_remote):
        raise ValueError('Unexpected restart option')
    for name in ('edits','edit_footage','assets','media-cache','libtv','libtv-profiles','voice/audio','voice/samples'):
        probe = root / 'state' / name / ('startup-check-' + uuid.uuid4().hex)
        try:
            probe.mkdir()
            (probe / 'write-check').write_bytes(b'ok')
        except OSError as exc:
            raise RuntimeError('Restart cancelled: service needs write access to state/' + name) from exc
        finally:
            if probe.exists():
                (probe / 'write-check').unlink(missing_ok=True)
                probe.rmdir()
    with sqlite3.connect(root / 'state/hub.sqlite3', timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        checks = [
            ('tasks', "state IN ('queued','submitting','running')"),
            ('ai_edit_jobs', "state IN ('queued','running','submitting')"),
            ('video_case_jobs', "state IN ('queued','running')"),
            ('voice_jobs', "state IN ('queued','running')"),
            ('edit_exports', "state IN ('queued','rendering')"),
            ('libtv_jobs', "state IN ('queued','submitting','running','importing')"),
            ('asset_classification', "status='running'"),
            ('ai_turns', "status='pending'"),
        ]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feishu_uploads'").fetchone():
            checks.append(('feishu_uploads', "state='uploading'"))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kalodata_jobs'").fetchone():
            checks.append(('kalodata_jobs', "state='running'"))
        if preserve_remote:
            # Submitted remote jobs are polled by their persisted ID on startup.
            checks[0]=('tasks', "state IN ('queued','submitting') OR (state='running' AND COALESCE(remote_id,'')='')")
            checks.extend([('comment_sample_jobs', "state='running' OR ai_state='running'"),
                           ('comment_sample_research', "state='running'")])
        for table, condition in checks:
            if db.execute('SELECT count(*) FROM ' + table + ' WHERE ' + condition).fetchone()[0]:
                raise RuntimeError('Active work in ' + table + '; finish it before restarting')
        pids = {c.pid for c in psutil.net_connections(kind='tcp')
                if c.status == 'LISTEN' and c.laddr.port in (8765, 8443)}
        services = []
        for pid in pids:
            process = psutil.Process(pid)
            entrypoints=[Path(arg) for arg in process.cmdline() if arg.endswith('.py')]
            verified=any((p if p.is_absolute() else root/p).resolve()==root/'run_service.py' for p in entrypoints)
            if Path(process.cwd()).resolve() != root or not verified:
                raise RuntimeError('Unexpected process on service port; no restart performed')
            services.append(process)
        for process in services:
            process.terminate()
        _, alive = psutil.wait_procs(services, timeout=10)
        if alive:
            raise RuntimeError('Service did not stop; no duplicate service started')
        db.rollback()
    if enable_proxy:
        (root/'state/preview-proxy.enabled').touch(exist_ok=True)
    for mode in ('local', 'lan'):
        with (root / f'state/restart-{mode}.out.log').open('ab') as out, (root / f'state/restart-{mode}.err.log').open('ab') as err:
            subprocess.Popen([str(runtime), '-B', 'run_service.py', mode], cwd=root,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    import urllib.request
    import ssl
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(
        context=ssl.create_default_context(cafile=str(root / 'seedance-hub-ca.crt'))))
    for address in ('http://127.0.0.1:8765/', 'https://192.168.100.10:8443/'):
        for attempt in range(15):
            try:
                with opener.open(address, timeout=2) as response:
                    if response.status == 200:
                        print(address, 'OK')
                        break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Service health check failed: ' + address)
    print('Update loaded. Refresh the editor with Ctrl+F5.')


if __name__ == '__main__':
    main()
