"""Stop one previously identified idle Hub lane, never a fresh or unrelated listener."""
from pathlib import Path
import sqlite3
import sys

import psutil
from inspect_cases_deploy import root, work


def stop_idle(lane, expected_pid=None):
    if lane not in ('local','lan'):
        raise ValueError('Use explicit local/lan')
    port=8765 if lane=='local' else 8443
    with sqlite3.connect(root/'state/hub.sqlite3',timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        blocked={key:n for key,n in work(db,lane).items() if n}
        if blocked:
            raise RuntimeError(f'Active/due work: {blocked}; no stop')
        listening=[c for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port in (8765,8443,8000)]
        found={c.pid for c in listening if c.laddr.port==port}
        if len(found)!=1 or expected_pid is not None and found!={expected_pid}:
            raise RuntimeError('Listener changed or was not identified; no stop')
        pid=next(iter(found));proc=psutil.Process(pid);args=proc.cmdline()
        cwd=Path(proc.cwd()).resolve()
        entry=(cwd/args[-2]).resolve() if len(args)>=3 else None
        if cwd!=root or entry!=root/'run_service.py' or args[-1]!=lane:
            raise RuntimeError('Unexpected listener; no stop')
        if lane=='lan' and {c.pid for c in listening if c.laddr.port==8000}!={pid}:
            raise RuntimeError('Unexpected phone listener; no stop')
        proc.terminate();proc.wait(timeout=20)
        db.rollback()
    print('Idle Hub lane stopped:',lane,pid,flush=True)


if __name__=='__main__':
    if len(sys.argv) not in (2,3):
        raise SystemExit('Usage: deploy_case_data_lane_stop.py local|lan [expected-pid]')
    stop_idle(sys.argv[1],int(sys.argv[2]) if len(sys.argv)==3 else None)
