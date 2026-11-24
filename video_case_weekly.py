"""Case-scoped weekly Kalodata scheduling, no external submission in scheduler.
Only newly consented cases are enrolled. A unique case marker and transactional
queue insertion prevent replay; missed batches older than seven days are skipped.
"""
import json,time,uuid
from datetime import datetime,timedelta,timezone

CN=timezone(timedelta(hours=8))

def next_friday(timestamp):
    local=datetime.fromtimestamp(timestamp,CN)
    day=local.date()+timedelta(days=(4-local.weekday())%7)
    slot=datetime(day.year,day.month,day.day,8,tzinfo=CN).timestamp()
    return slot if slot>timestamp else slot+7*86400

def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS video_case_weekly_enrollment(
        case_id TEXT PRIMARY KEY,owner TEXT NOT NULL,created REAL NOT NULL,
        due REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',job_id TEXT)''')

def enroll(db,cid,owner,created):
    db.execute('INSERT OR IGNORE INTO video_case_weekly_enrollment(case_id,owner,created,due) VALUES(?,?,?,?)',
               (cid,owner,created,next_friday(created)))

def dispatch(hub,now=None):
    from video_case_kalodata import period
    now=time.time() if now is None else now
    with hub.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("""SELECT e.*,c.platform,u.enabled FROM video_case_weekly_enrollment e
          JOIN video_cases c ON c.id=e.case_id LEFT JOIN users u ON u.id=e.owner
          WHERE e.state='pending' AND e.due<=? ORDER BY e.due,e.created LIMIT 1""",(now,)).fetchone()
        if not row:return False
        row=dict(row);cid=row['case_id']
        if now>=row['due']+7*86400 or row['enabled']!=1 or not db.execute('SELECT 1 FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=?',(cid,)).fetchone():
            db.execute("UPDATE video_case_weekly_enrollment SET state='skipped' WHERE case_id=?",(cid,));return True
        # Respect the existing global queue safety limit; leave pending for the
        # current batch rather than creating an unbounded set of paid jobs.
        active_count=db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE kind='kalodata' AND state IN ('queued','submitting','running','waiting')").fetchone()[0]
        if active_count>=100:return False
        # Any earlier success satisfies this case; do not spend again.
        if db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND kind='kalodata' AND state='ready'",(cid,)).fetchone():
            db.execute("UPDATE video_case_weekly_enrollment SET state='existing' WHERE case_id=?",(cid,));return True
        # Do not duplicate any in-flight request.
        active=db.execute("SELECT id FROM video_case_jobs WHERE case_id=? AND kind='kalodata' AND state IN ('queued','submitting','running','waiting')",(cid,)).fetchone()
        if active:
            db.execute("UPDATE video_case_weekly_enrollment SET state='existing',job_id=? WHERE case_id=?",(active[0],cid));return True
        if db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND kind='kalodata' AND state='attention'",(cid,)).fetchone():
            db.execute("UPDATE video_case_weekly_enrollment SET state='attention' WHERE case_id=?",(cid,));return True
        jid=uuid.uuid4().hex
        # Query time range is the existing 30-day commercial range, not enrollment window.
        db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'kalodata','queued',?,?,?,?)",
                   (jid,cid,row['owner'],'weekly-case:'+cid,now,now,json.dumps({**period(),'weekly':True})))
        db.execute("UPDATE video_case_weekly_enrollment SET state='queued',job_id=? WHERE case_id=?",(jid,cid))
        return True
