"""Durable, bounded recovery ONLY for a confirmed /video/url business code 1054.
Each poll may consume API credits. No network/AI request is ever replayed by this module.
"""
import time

DELAYS=(60,120,300,600,1200,1800)
MAX_AGE=86400
ACTIVE_SQL="('queued','submitting','running','waiting')"


def initialize(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(video_case_jobs)')}
    for name,definition in [('wait_count','INTEGER NOT NULL DEFAULT 0'),('next_attempt','REAL'),('wait_started','REAL'),('wait_deadline','REAL'),('error_code',"TEXT NOT NULL DEFAULT ''")]:
        if name not in columns:db.execute(f'ALTER TABLE video_case_jobs ADD COLUMN {name} {definition}')
    # Versioned index keeps existing active index until the replacement has been built.
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS video_case_one_recoverable ON video_case_jobs(case_id,kind) WHERE state IN '+ACTIVE_SQL)


def defer(db,jid,now=None):
    now=time.time() if now is None else now
    job=db.execute('SELECT * FROM video_case_jobs WHERE id=?',(jid,)).fetchone()
    count=job['wait_count']+1;started=job['wait_started'] or now;deadline=job['wait_deadline'] or started+MAX_AGE
    if count>len(DELAYS) or now>=deadline:
        db.execute("UPDATE video_case_jobs SET state='attention',next_attempt=NULL,error_code='1054',error='供应商仍未缓存视频，已达到自动检查次数或24小时时限；停止检查，请核对后手动处理',updated=? WHERE id=?",(now,jid))
        return False
    due=min(now+DELAYS[count-1],deadline)
    db.execute("UPDATE video_case_jobs SET state='waiting',wait_count=?,wait_started=?,wait_deadline=?,next_attempt=?,error_code='1054',error='供应商已排队获取视频；等待后自动检查，不代表视频已经下载。每次检查可能消耗API额度，可停止等待',updated=? WHERE id=?",(count,started,deadline,due,now,jid))
    return True
