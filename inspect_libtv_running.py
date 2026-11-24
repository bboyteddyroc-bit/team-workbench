"""Read-only: list LibTV jobs that can block the shared single-flight guard."""
import json
import sqlite3
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent
db_path = root / 'state' / 'hub.sqlite3'
# Copy first: the live database runs in WAL mode and a read-only open would need
# write access to the -wal/-shm sidecars.
import shutil
import tempfile
tmpdir = Path(tempfile.mkdtemp(prefix='libtv-inspect-'))
for suffix in ('', '-wal', '-shm'):
    side = Path(str(db_path) + suffix)
    if side.exists():
        shutil.copy2(side, tmpdir / side.name)
con = sqlite3.connect(str(tmpdir / db_path.name))
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT id,owner,state,stage,runner,profile,project,created,updated,error,retry_at,asset_id "
    "FROM libtv_jobs WHERE state IN ('running','importing') ORDER BY created"
).fetchall()
now = time.time()
print(json.dumps([{
    'id': r['id'][:8],
    'owner': r['owner'],
    'state': r['state'],
    'stage': r['stage'],
    'runner_pid': r['runner'],
    'profile': r['profile'],
    'project': r['project'],
    'age_s': round(now - (r['created'] or now), 1),
    'idle_s': round(now - (r['updated'] or now), 1),
    'error': (r['error'] or '')[:200],
    'has_asset': bool(r['asset_id']),
} for r in rows], ensure_ascii=False, indent=1))
print('running_count=', len(rows))
print('attention_count=', con.execute("SELECT COUNT(*) FROM libtv_jobs WHERE state='attention'").fetchone()[0])
print('recent=', json.dumps([dict(r) for r in con.execute(
    "SELECT id,state,stage,created,updated FROM libtv_jobs ORDER BY created DESC LIMIT 5")],
    ensure_ascii=False, default=str))
