"""Bundled royalty-free sound effects for the editor audio panel.

The seed library lives on disk (``state/sfx`` + ``index.json``) so it is shipped
with the app and needs no per-user upload. Using a seed copies the file once into
the owner's asset store, so the timeline, export and history keep working with the
existing asset pipeline.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


def attach(app, hub, user, body):
    root: Path = Path(hub.directory) / 'sfx'
    index_path = root / 'index.json'
    cache = {'mtime': None, 'data': None}

    with hub.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS sfx_favorites(
            owner TEXT NOT NULL, sfx_id TEXT NOT NULL, created REAL NOT NULL,
            PRIMARY KEY(owner, sfx_id));
        CREATE TABLE IF NOT EXISTS sfx_usage(
            owner TEXT NOT NULL, sfx_id TEXT NOT NULL, asset_id TEXT NOT NULL,
            uses INTEGER NOT NULL DEFAULT 0, last_used REAL NOT NULL,
            PRIMARY KEY(owner, sfx_id));
        ''')

    def manifest():
        try:
            mtime = index_path.stat().st_mtime
        except OSError:
            return {'categories': [], 'items': [], 'license': ''}
        if cache['mtime'] != mtime:
            try:
                cache['data'] = json.loads(index_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                cache['data'] = {'categories': [], 'items': [], 'license': ''}
            cache['mtime'] = mtime
        return cache['data']

    def lookup(sfx_id):
        if not ID_PATTERN.match(sfx_id or ''):
            raise HTTPException(404, '音效不存在')
        for item in manifest().get('items', []):
            if item['id'] == sfx_id:
                path = (root / item['file']).resolve()
                if not path.is_file() or root.resolve() not in path.parents:
                    raise HTTPException(404, '音效文件缺失，请运行 sfx_seed.py 重新下载')
                return item, path
        raise HTTPException(404, '音效不存在')

    @app.get('/api/editor/sfx')
    def list_sfx(request: Request, q: str = '', category: str = ''):
        u = user(request)
        data = manifest()
        with hub.db() as db:
            favorites = {r['sfx_id'] for r in db.execute('SELECT sfx_id FROM sfx_favorites WHERE owner=?', (u['id'],))}
            usage = {r['sfx_id']: r['uses'] for r in db.execute('SELECT sfx_id,uses FROM sfx_usage WHERE owner=?', (u['id'],))}
        needle = (q or '').strip().lower()
        wanted = (category or '').strip()
        labels = {c['key']: c['label'] for c in data.get('categories', [])}
        rows = []
        for index, item in enumerate(data.get('items', [])):
            if wanted and item['category'] != wanted:
                continue
            haystack = ' '.join([item['name'], item.get('name_en', ''), labels.get(item['category'], ''), *item.get('tags', [])]).lower()
            if needle and needle not in haystack:
                continue
            rows.append({**{k: item[k] for k in ('id', 'name', 'name_en', 'category', 'duration', 'tags', 'source', 'source_url', 'license')},
                         'index': index,
                         'favorite': item['id'] in favorites,
                         'uses': usage.get(item['id'], 0),
                         'audio_url': f'/api/editor/sfx/{item["id"]}/audio'})
        rows.sort(key=lambda r: (not r['favorite'], -r['uses'], r['index']))
        counts = {}
        for item in data.get('items', []):
            counts[item['category']] = counts.get(item['category'], 0) + 1
        categories = [{'key': key, 'label': label, 'count': counts.get(key, 0)}
                      for key, label in ((c['key'], c['label']) for c in data.get('categories', []))]
        return {'categories': categories, 'items': rows, 'total': len(data.get('items', [])),
                'license': data.get('license', ''), 'source': data.get('source', '')}

    @app.get('/api/editor/sfx/{sfx_id}/audio')
    def seed_audio(sfx_id: str, request: Request):
        user(request)
        item, path = lookup(sfx_id)
        return FileResponse(path, media_type='audio/mpeg', filename=item['file'])

    @app.post('/api/editor/sfx/{sfx_id}/favorite')
    async def favorite(sfx_id: str, request: Request):
        u = user(request)
        lookup(sfx_id)
        payload = {}
        try:
            payload = json.loads((await request.body()) or b'{}')
        except ValueError:
            payload = {}
        on = bool(payload.get('on', True))
        with hub.db() as db:
            if on:
                db.execute('INSERT OR IGNORE INTO sfx_favorites VALUES(?,?,?)', (u['id'], sfx_id, time.time()))
            else:
                db.execute('DELETE FROM sfx_favorites WHERE owner=? AND sfx_id=?', (u['id'], sfx_id))
        return {'favorite': on, 'id': sfx_id}

    @app.post('/api/editor/sfx/{sfx_id}/adopt')
    def adopt(sfx_id: str, request: Request):
        """Copy a seed sound into the caller's asset store (idempotent per owner)."""
        u = user(request)
        item, path = lookup(sfx_id)
        with hub.db() as db:
            row = db.execute('SELECT asset_id FROM sfx_usage WHERE owner=? AND sfx_id=?', (u['id'], sfx_id)).fetchone()
            asset = db.execute('SELECT * FROM assets WHERE id=? AND owner=?', (row['asset_id'], u['id'])).fetchone() if row else None
            reused = bool(asset and (hub.assets / asset['id']).is_file())
            if not reused:
                asset_id = uuid.uuid4().hex
                target = hub.assets / asset_id
                shutil.copyfile(path, target)
                name = f'{item["name"]}.mp3'
                db.execute('INSERT INTO assets(id,owner,name,mime,size,created) VALUES(?,?,?,?,?,?)',
                           (asset_id, u['id'], name, 'audio/mpeg', target.stat().st_size, time.time()))
                asset = db.execute('SELECT * FROM assets WHERE id=?', (asset_id,)).fetchone()
            db.execute('INSERT INTO sfx_usage(owner,sfx_id,asset_id,uses,last_used) VALUES(?,?,?,1,?) '
                       'ON CONFLICT(owner,sfx_id) DO UPDATE SET uses=uses+1,last_used=excluded.last_used',
                       (u['id'], sfx_id, asset['id'], time.time()))
            return {'id': asset['id'], 'name': asset['name'], 'mime': asset['mime'],
                    'size': asset['size'], 'created': asset['created'],
                    'duration': item['duration'], 'reused': reused}
