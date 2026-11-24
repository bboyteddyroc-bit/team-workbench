"""Read-only: recent LibTV jobs and the stuck-running risks behind the 409 guard."""
import sqlite3
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parent
src = root / 'state' / 'hub.sqlite3'
tmp = Path(tempfile.mkdtemp(prefix='libtv-recent-'))
for suffix in ('', '-wal', '-shm'):
    side = Path(str(src) + suffix)
    if side.exists():
        shutil.copy2(side, tmp / side.name)
con = sqlite3.connect(str(tmp / src.name))
con.row_factory = sqlite3.Row


def ts(value):
    if not value:
        return '-'
    return datetime.fromtimestamp(value).strftime('%m-%d %H:%M:%S')


print('== 最近 12 条 LibTV 任务 ==')
for r in con.execute(
        'SELECT id,owner,state,stage,created,updated,error,runner FROM libtv_jobs ORDER BY created DESC LIMIT 12'):
    print(f"{r['id'][:8]}  {ts(r['created'])} → {ts(r['updated'])}  "
          f"{r['state']:<9} runner={r['runner']}  stage={r['stage']}  err={(r['error'] or '')[:70]}")

print()
print('== attention 任务里“已提交但没走完”的（可能被误当成仍在生成）==')
for r in con.execute(
        "SELECT id,state,stage,created,updated,error FROM libtv_jobs "
        "WHERE state='attention' ORDER BY created DESC LIMIT 16"):
    print(f"{r['id'][:8]}  {ts(r['created'])}  {r['stage']:<28} err={(r['error'] or '')[:60]}")

print()
print('== 各状态计数 ==')
for r in con.execute('SELECT state,COUNT(*) n FROM libtv_jobs GROUP BY state'):
    print(f"{r['state']:<10} {r['n']}")

print()
now = time.time()
print('now=', ts(now))
