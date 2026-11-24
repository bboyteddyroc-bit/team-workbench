import sqlite3
from pathlib import Path
with sqlite3.connect(Path(__file__).resolve().parent/'state/hub.sqlite3') as db:
 print('active_libtv_jobs',db.execute("SELECT count(*) FROM libtv_jobs WHERE state IN ('running','importing')").fetchone()[0])
