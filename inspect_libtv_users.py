"""Read-only: who submits LibTV jobs, and is anything running right now."""
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parent
src = root / 'state' / 'hub.sqlite3'
tmp = Path(tempfile.mkdtemp(prefix='libtv-users-'))
for suffix in ('', '-wal', '-shm'):
    side = Path(str(src) + suffix)
    if side.exists():
        shutil.copy2(side, tmp / side.name)
con = sqlite3.connect(str(tmp / src.name))
con.row_factory = sqlite3.Row
t = lambda v: datetime.fromtimestamp(v).strftime('%m-%d %H:%M:%S') if v else '-'

print('users:', [(r['username'], r['role'], r['enabled']) for r in con.execute('SELECT username,role,enabled FROM users')])
print('owners:', [(r['username'], r['n']) for r in con.execute(
    'SELECT u.username,COUNT(*) n FROM libtv_jobs j LEFT JOIN users u ON u.id=j.owner GROUP BY u.username')])
print('sessions_alive:', con.execute('SELECT COUNT(*) FROM sessions WHERE expires>?', (time.time(),)).fetchone()[0])
print('running_now:', con.execute("SELECT COUNT(*) FROM libtv_jobs WHERE state='running'").fetchone()[0])
print('recent:')
for r in con.execute('SELECT j.id,j.state,j.stage,j.created,j.updated,u.username FROM libtv_jobs j '
                     'LEFT JOIN users u ON u.id=j.owner ORDER BY j.created DESC LIMIT 6'):
    print('  ', r['id'][:8], r['username'], r['state'], t(r['created']), '->', t(r['updated']), (r['stage'] or '')[:20])
