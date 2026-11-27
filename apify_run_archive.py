"""Reversible visibility control for one completed Apify run's snapshots."""
import argparse
import json
import sqlite3
import time
from pathlib import Path


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS apify_hidden_runs(
        run TEXT PRIMARY KEY, account TEXT NOT NULL, hidden_at REAL NOT NULL,
        snapshot_count INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS apify_hidden_snapshots(
        run TEXT NOT NULL, video TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run,video))''')


def hide(db, run, handle, expected=None):
    db.execute('BEGIN IMMEDIATE')
    initialize(db)
    identity = db.execute('''SELECT r.account,r.state,a.handle FROM apify_runs r
        JOIN apify_accounts a ON a.id=r.account WHERE r.id=?''',(run,)).fetchone()
    if not identity or identity['handle'].casefold()!=handle.casefold() or identity['state'] not in ('ready','attention'):
        raise ValueError('采集批次、账号或完成状态不符，未隐藏')
    existing=db.execute('SELECT snapshot_count FROM apify_hidden_runs WHERE run=?',(run,)).fetchone()
    if existing:
        return existing['snapshot_count']
    rows=db.execute('SELECT * FROM apify_snapshots WHERE run=? AND account=?',(run,identity['account'])).fetchall()
    if not rows or (expected is not None and len(rows)!=expected):
        raise ValueError('批次的快照数量已变化，未隐藏')
    db.executemany('INSERT INTO apify_hidden_snapshots(run,video,payload) VALUES(?,?,?)',
        [(run,row['video'],json.dumps(dict(row),ensure_ascii=False)) for row in rows])
    db.execute('INSERT INTO apify_hidden_runs VALUES(?,?,?,?)',(run,identity['account'],time.time(),len(rows)))
    removed=db.execute('DELETE FROM apify_snapshots WHERE run=? AND account=?',(run,identity['account'])).rowcount
    if removed!=len(rows):
        raise RuntimeError('写入数量不一致，未提交变更')
    return removed


def restore(db, run, handle):
    db.execute('BEGIN IMMEDIATE')
    initialize(db)
    hidden=db.execute('''SELECT h.account,h.snapshot_count,a.handle FROM apify_hidden_runs h
        JOIN apify_accounts a ON a.id=h.account WHERE h.run=?''',(run,)).fetchone()
    if not hidden or hidden['handle'].casefold()!=handle.casefold():
        raise ValueError('没有找到该账号的隐藏批次')
    rows=[json.loads(r['payload']) for r in db.execute('SELECT payload FROM apify_hidden_snapshots WHERE run=?',(run,))]
    if len(rows)!=hidden['snapshot_count'] or any(r['account']!=hidden['account'] or r['run']!=run for r in rows):
        raise ValueError('归档记录与原批次不符，未恢复')
    columns=[r['name'] for r in db.execute('PRAGMA table_info(apify_snapshots)') if r['name'] in rows[0]]
    identifiers=','.join('"'+col.replace('"','""')+'"' for col in columns)
    marks=','.join('?' for _ in columns)
    db.executemany(f'INSERT OR IGNORE INTO apify_snapshots({identifiers}) VALUES({marks})',
        [tuple(row[col] for col in columns) for row in rows])
    db.execute('DELETE FROM apify_hidden_snapshots WHERE run=?',(run,))
    db.execute('DELETE FROM apify_hidden_runs WHERE run=?',(run,))
    return len(rows)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('hide','restore'))
    parser.add_argument('run')
    parser.add_argument('handle')
    parser.add_argument('--expected',type=int)
    args=parser.parse_args()
    database=Path(__file__).resolve().parent/'state'/'hub.sqlite3'
    with sqlite3.connect(database.as_uri()+'?mode=rw',uri=True,timeout=12) as db:
        db.row_factory=sqlite3.Row
        handle=args.handle.removeprefix('@')
        count=hide(db,args.run,handle,args.expected) if args.action=='hide' else restore(db,args.run,handle)
        print(json.dumps({'action':args.action,'count':count}))


if __name__=='__main__':
    main()
