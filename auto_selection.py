"""Owner-scoped selection storage for the proposed automation.

This module is not attached to the running service. Turning settings on here
must only be done by an authenticated, explicitly confirmed application flow.
"""
import time


def init_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS auto_collection_config (
        owner TEXT PRIMARY KEY, collection_enabled INTEGER NOT NULL DEFAULT 0,
        enrichment_enabled INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS auto_collection_selection (
        owner TEXT NOT NULL, account TEXT NOT NULL, selected INTEGER NOT NULL DEFAULT 0,
        updated REAL NOT NULL, PRIMARY KEY(owner, account))''')


def select_account(db, owner, account, selected):
    if type(selected) is not bool:
        raise ValueError('selected must be boolean')
    if not db.execute('SELECT 1 FROM apify_accounts WHERE id=? AND owner=? AND deleted_at IS NULL', (account, owner)).fetchone():
        raise ValueError('account not owned')
    db.execute('''INSERT INTO auto_collection_selection(owner,account,selected,updated)
        VALUES(?,?,?,?) ON CONFLICT(owner,account) DO UPDATE SET
        selected=excluded.selected,updated=excluded.updated''', (owner, account, int(selected), time.time()))


def selected_accounts(db, owner):
    return [row[0] for row in db.execute('''SELECT a.id FROM apify_accounts a
        JOIN auto_collection_selection s ON s.account=a.id AND s.owner=a.owner
        WHERE a.owner=? AND s.selected=1 AND a.deleted_at IS NULL ORDER BY a.handle''', (owner,))]


def set_config(db, owner, collection, enrichment, confirmed=False):
    if type(collection) is not bool or type(enrichment) is not bool:
        raise ValueError('settings must be boolean')
    # Serialize the read and write at the caller's transaction boundary. An
    # enabling request must always carry its own confirmation, even if a
    # concurrent request is enabling the same setting.
    if (collection or enrichment) and confirmed is not True:
        raise ValueError('explicit paid confirmation required')
    db.execute('''INSERT INTO auto_collection_config(owner,collection_enabled,enrichment_enabled,updated)
        VALUES(?,?,?,?) ON CONFLICT(owner) DO UPDATE SET collection_enabled=excluded.collection_enabled,
        enrichment_enabled=excluded.enrichment_enabled,updated=excluded.updated''',
        (owner, int(collection), int(enrichment), time.time()))


def get_config(db, owner):
    row = db.execute('SELECT collection_enabled,enrichment_enabled FROM auto_collection_config WHERE owner=?', (owner,)).fetchone()
    return {'collection_enabled': bool(row[0]) if row else False,
            'enrichment_enabled': bool(row[1]) if row else False}
