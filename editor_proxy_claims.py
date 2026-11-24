"""SQLite-backed proxy claims. Explicit setup only; not yet connected to workers.

A running claim never expires automatically: a slow or orphaned encoder must be
verified stopped before an operator clears it. This prevents overlapping work.
"""
import sqlite3
import time
import uuid


def setup(db):
    db.execute('''CREATE TABLE IF NOT EXISTS preview_proxy_jobs (
        cache_key TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL,
        claim TEXT, updated REAL NOT NULL)''')


def setup_sources(db):
    setup(db)
    db.execute('CREATE TABLE IF NOT EXISTS preview_proxy_sources (cache_key TEXT PRIMARY KEY, owner TEXT NOT NULL, task_id TEXT NOT NULL)')


def enqueue(db, key, capacity=16, *, source=None):
    if not isinstance(key,str) or not key or len(key)>128 or capacity<1:raise ValueError('invalid queue input')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT state FROM preview_proxy_jobs WHERE cache_key=?',(key,)).fetchone()
        if row:result='existing'
        elif db.execute("SELECT COUNT(*) FROM preview_proxy_jobs WHERE state IN ('queued','running')").fetchone()[0]>=capacity:result='full'
        else:
            now=time.time();db.execute("INSERT INTO preview_proxy_jobs VALUES (?,'queued',?,NULL,?)",(key,now,now));result='queued'
            if source is not None:
                db.execute('INSERT INTO preview_proxy_sources VALUES (?,?,?)',(key,*source))
        db.commit();return result
    except BaseException:db.rollback();raise


def claim_next(db):
    """Claim one job, or defer while export is pending/running; atomic across processes.

    Export start must also use the same transaction protocol for mutual exclusion;
    checking its state here alone does not prevent an export starting afterwards.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute("SELECT 1 FROM preview_proxy_jobs WHERE state='running' LIMIT 1").fetchone():db.commit();return None
        if db.execute("SELECT 1 FROM edit_exports WHERE state IN ('queued','rendering') LIMIT 1").fetchone():db.commit();return None
        row=db.execute("SELECT cache_key FROM preview_proxy_jobs WHERE state='queued' ORDER BY created,cache_key LIMIT 1").fetchone()
        if not row:db.commit();return None
        token=uuid.uuid4().hex
        db.execute("UPDATE preview_proxy_jobs SET state='running',claim=?,updated=? WHERE cache_key=? AND state='queued'",(token,time.time(),row[0]));db.commit();return row[0],token
    except BaseException:db.rollback();raise


def claim_export(db):
    """Experimental atomic claim; callers must provide a verified orphan recovery.

    A queued export makes a running proxy yield; the export remains queued until
    the proxy's owner confirms its encoder has exited. Not connected to Editor.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute("SELECT e.*,u.role,u.enabled FROM edit_exports e JOIN users u ON u.id=e.owner WHERE e.state='queued' ORDER BY e.created LIMIT 1").fetchone()
        if not row or db.execute("SELECT 1 FROM preview_proxy_jobs WHERE state='running' LIMIT 1").fetchone():
            db.commit();return None
        db.execute("UPDATE edit_exports SET state='rendering',updated=? WHERE id=? AND state='queued'",(time.time(),row['id']))
        db.commit();return row
    except BaseException:db.rollback();raise


def export_waiting(db,key,token):
    """Check ownership and whether the worker should stop its encoder for export."""
    row=db.execute("SELECT 1 FROM preview_proxy_jobs WHERE cache_key=? AND state='running' AND claim=?",(key,token)).fetchone()
    if not row:raise ValueError('proxy claim lost')
    return bool(db.execute("SELECT 1 FROM edit_exports WHERE state IN ('queued','rendering') LIMIT 1").fetchone())


def requeue_after_stop(db,key,token):
    """Only call after the owned encoder has exited and temporary output is isolated."""
    with db:
        result=db.execute("UPDATE preview_proxy_jobs SET state='queued',claim=NULL,updated=? WHERE cache_key=? AND state='running' AND claim=?",(time.time(),key,token))
    return result.rowcount==1


def finish(db,key,token,state):
    if state not in ('ready','failed'):raise ValueError('invalid terminal state')
    with db:
        result=db.execute("UPDATE preview_proxy_jobs SET state=?,claim=NULL,updated=? WHERE cache_key=? AND state='running' AND claim=?",(state,time.time(),key,token))
    return result.rowcount==1
