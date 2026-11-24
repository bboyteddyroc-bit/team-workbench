"""Rewrite the three stale LibTV diagnoses so the cards stop blaming the website.

Only touches the message/stage text of jobs that are already in `attention`; the
generation itself is never re-run and no credits are spent.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / 'state' / 'hub.sqlite3'

NO_OUTPUT = '画布上没有可下载成片：LibTV 未记录到本次生成结果（生成未开始或已失败）。未自动重试，也不会重复扣费；请先在画布核对，必要时重新发起生成。'
REVIEW = ('LibTV 生成未通过：输入内容未通过安全审核，积分将会在2小时内返还；未自动重试。'
          '请修改提示词或素材后重新发起生成。')

FIXES = {
    '129a6d7eeeb17b47c0fce8a73027bb95': (NO_OUTPUT, '画布无成片 · 需重新发起生成'),
    'ab88b6eec79c4220c899fa48416e2908': (NO_OUTPUT, '画布无成片 · 需重新发起生成'),
    'dc3eff2b5be282e3eb77157e80c47978': (REVIEW, '生成未通过审核 · 需改提示词后重发'),
}

with sqlite3.connect(DB, timeout=20) as db:
    db.row_factory = sqlite3.Row
    for jid, (error, stage) in FIXES.items():
        row = db.execute('SELECT state,stage,error FROM libtv_jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            print(jid, 'missing')
            continue
        if row['state'] != 'attention':
            print(jid, 'skipped, state=', row['state'])
            continue
        db.execute('UPDATE libtv_jobs SET error=?,stage=? WHERE id=? AND state=?', (error, stage, jid, 'attention'))
        print(jid, 'updated')
    db.commit()
