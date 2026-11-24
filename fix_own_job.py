"""Clear the stale login-failure text on the owner's own abandoned LibTV job."""
import sqlite3
from pathlib import Path

db = sqlite3.connect(Path(__file__).parent / 'state' / 'hub.sqlite3', timeout=20)
changed = db.execute(
    "UPDATE libtv_jobs SET error=?,stage=? WHERE id=? AND state='attention'",
    ('这条任务在提交时中台 LibTV 登录已失效，没有创建画布，也没有产生扣费；请直接重新发起生成。',
     '未创建画布 · 请重新发起生成',
     'bd14de329a71133745f0afcf44dfb3c7'),
).rowcount
db.commit()
print('updated', changed)
