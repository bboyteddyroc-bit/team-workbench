"""Durable storage for grouped collection runs. No network operations.

The scheduler must claim a batch before submitting it and must never resubmit an
ambiguous submission. This module is not connected to the production worker.
"""
import json
import time
import uuid


def init_schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS grouped_runs (
      id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL,
      options TEXT NOT NULL, start_at REAL NOT NULL, end_at REAL NOT NULL,
      remote_id TEXT, created REAL NOT NULL, updated REAL NOT NULL, error TEXT);
    CREATE TABLE IF NOT EXISTS grouped_run_members (
      batch TEXT NOT NULL, account TEXT NOT NULL, handle TEXT NOT NULL,
      state TEXT NOT NULL, child_run TEXT, PRIMARY KEY(batch,account));
    CREATE UNIQUE INDEX IF NOT EXISTS grouped_member_active
      ON grouped_run_members(account) WHERE state IN ('queued','submitting','running');
    ''')
    if 'automatic' not in {row[1] for row in db.execute('PRAGMA table_info(grouped_runs)')}:
        db.execute('ALTER TABLE grouped_runs ADD COLUMN automatic INTEGER NOT NULL DEFAULT 0')


def enqueue(db, owner, accounts, options, start_at, end_at, now=None, automatic=False):
    """Enqueue one owner/window atomically; caller owns the write transaction."""
    if not owner or not accounts or start_at >= end_at:
        raise ValueError('invalid batch')
    ids = [a['id'] for a in accounts]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate account')
    checked = []
    for account in accounts:
        row = db.execute('SELECT handle FROM apify_accounts WHERE id=? AND owner=? AND deleted_at IS NULL',
                         (account['id'], owner)).fetchone()
        if not row or row[0] != account['handle']:
            raise ValueError('account not owned or handle mismatch')
        if db.execute("SELECT 1 FROM apify_runs WHERE account=? AND state IN ('queued','submitting','running')", (account['id'],)).fetchone():
            raise ValueError('account already active')
        checked.append((account['id'], row[0]))
    stamp = time.time() if now is None else now
    bid = uuid.uuid4().hex
    db.execute("INSERT INTO grouped_runs(id,owner,state,options,start_at,end_at,created,updated,automatic) VALUES(?,?,'queued',?,?,?,?,?,?)",
               (bid, owner, json.dumps(options), start_at, end_at, stamp, stamp, int(automatic)))
    db.executemany("INSERT INTO grouped_run_members VALUES(?,?,?,'queued',NULL)",
                   [(bid, aid, handle) for aid, handle in checked])
    return bid


def claim(db, batch, now=None):
    """Claim a queued run within a caller-owned BEGIN IMMEDIATE transaction."""
    stamp = time.time() if now is None else now
    result = db.execute("UPDATE grouped_runs SET state='submitting',updated=? WHERE id=? AND state='queued'", (stamp, batch))
    if result.rowcount != 1:
        return False
    db.execute("UPDATE grouped_run_members SET state='submitting' WHERE batch=? AND state='queued'", (batch,))
    return True


def submitted(db, batch, remote_id, now=None):
    if not isinstance(remote_id, str) or not remote_id.strip():
        raise ValueError('missing remote id')
    stamp = time.time() if now is None else now
    changed = db.execute("UPDATE grouped_runs SET state='running',remote_id=?,updated=? WHERE id=? AND state='submitting'", (remote_id, stamp, batch))
    if changed.rowcount != 1:
        raise ValueError('batch not submitting')
    db.execute("UPDATE grouped_run_members SET state='running' WHERE batch=? AND state='submitting'", (batch,))


def recover(db, now=None):
    """Do not retry an uncertain POST; known remote ids are left running."""
    stamp = time.time() if now is None else now
    db.execute("UPDATE grouped_run_members SET state='attention' WHERE batch IN (SELECT id FROM grouped_runs WHERE state='submitting') AND state='submitting'")
    db.execute("UPDATE grouped_runs SET state='attention',error='提交结果未知，请核对 Apify 控制台；未自动重试',updated=? WHERE state='submitting'", (stamp,))


def finish(db, batch, member_states, error=None, now=None):
    """Record final per-account outcomes atomically after persistence by caller.

    Each submitted member must be accounted for. Uncertain or incomplete
    outcomes must be attention, not ready. No remote operation is performed.
    """
    stamp = time.time() if now is None else now
    run = db.execute("SELECT state FROM grouped_runs WHERE id=?", (batch,)).fetchone()
    if not run or run[0] != 'running':
        raise ValueError('batch not running')
    members = {r[0] for r in db.execute("SELECT account FROM grouped_run_members WHERE batch=? AND state='running'", (batch,))}
    if not members or set(member_states) != members or any(v not in ('ready', 'attention') for v in member_states.values()):
        raise ValueError('every running member needs a valid outcome')
    for account, state in member_states.items():
        db.execute("UPDATE grouped_run_members SET state=? WHERE batch=? AND account=? AND state='running'", (state, batch, account))
    state = 'attention' if error or 'attention' in member_states.values() else 'ready'
    db.execute("UPDATE grouped_runs SET state=?,error=?,updated=? WHERE id=? AND state='running'", (state, error, stamp, batch))


def deselect_pending(db, owner, account, now=None):
    """Remove only members not yet claimed; do not interrupt remote runs."""
    stamp = time.time() if now is None else now
    batches = [r[0] for r in db.execute("SELECT m.batch FROM grouped_run_members m JOIN grouped_runs b ON b.id=m.batch WHERE b.owner=? AND m.account=? AND b.state='queued' AND m.state='queued'", (owner, account))]
    for batch in batches:
        db.execute("UPDATE grouped_run_members SET state='cancelled' WHERE batch=? AND account=? AND state='queued'", (batch, account))
        db.execute("UPDATE grouped_runs SET state='cancelled',updated=? WHERE id=? AND state='queued' AND NOT EXISTS (SELECT 1 FROM grouped_run_members WHERE batch=? AND state='queued')", (stamp, batch, batch))
