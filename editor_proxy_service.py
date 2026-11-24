"""Shared preview cache. Only the hub worker-lock holder executes jobs."""
import logging
import os
import re
import shutil
import time

import editor_proxy_claims as claims
from editor_media_cache import fingerprint
from editor_proxy_policy import inspect
from editor_proxy_worker import run_claim

log = logging.getLogger(__name__)
BUDGET = 2 << 30
RESERVE = 256 << 20


class PreviewProxies:
    def __init__(self, editor, probe):
        self.editor = editor
        self.hub = editor.hub
        self.probe = probe
        self.root = editor.root / 'preview-proxies-v1'
        self.enabled = os.name == 'nt' and os.getenv('HUB_PREVIEW_PROXY', '0') == '1'
        with self.hub.db() as db:
            claims.setup_sources(db)

    def source(self, owner, admin, task):
        path = self.editor.source(owner, admin, task)
        return path, fingerprint(path, 'preview-v1')

    def status(self, owner, admin, task):
        if not self.enabled:
            return {'state': 'original'}
        _, key = self.source(owner, admin, task)
        with self.hub.db() as db:
            row = db.execute('SELECT state FROM preview_proxy_jobs WHERE cache_key=?', (key,)).fetchone()
            if not row:
                status = claims.enqueue(db, key, source=(owner,task))
                return {'state': 'pending' if status != 'full' else 'original'}
        if row[0] == 'ready' and (self.root / (key+'.mp4')).is_file():
            return {'state':'ready','version':key}
        return {'state':'pending' if row[0] in ('queued','running') else 'original'}

    def file(self, owner, admin, task, version):
        if not self.enabled:
            return None
        _, key = self.source(owner, admin, task)
        if key != version:
            return None
        with self.hub.db() as db:
            row = db.execute('SELECT state FROM preview_proxy_jobs WHERE cache_key=?', (key,)).fetchone()
        path = self.root / (key+'.mp4')
        return path if row and row[0]=='ready' and path.is_file() else None

    def recover(self):
        # Called exclusively by the worker-lock holder, never by an HTTP process.
        with self.hub.db() as db:
            rows = db.execute("SELECT cache_key,claim FROM preview_proxy_jobs WHERE state='running'").fetchall()
        for key, token in rows:
            try:
                from editor_proxy_winjob import recover_job
                recover_job(token)
                valid = bool(re.fullmatch('[0-9a-f]{64}', key))
                if valid:
                    target = self.root / (key+'.mp4')
                    for partial in self.root.glob('.'+key+'.*.part.mp4'):
                        try:partial.unlink(missing_ok=True)
                        except OSError:log.warning('Preview staging cleanup failed')
                with self.hub.db() as db:
                    # The final name is only published by atomic rename after validation.
                    claims.finish(db,key,token,'ready' if valid and target.is_file() else 'failed')
            except Exception:
                log.exception('Could not verify shutdown of interrupted preview encoder')
                return False
        return True

    def tick(self):
        if not self.enabled or self.hub.stop.is_set():return
        with self.hub.db() as db:
            claim = claims.claim_next(db)
        if not claim:return
        key, token = claim
        try:
            if not re.fullmatch('[0-9a-f]{64}',key):raise ValueError('Invalid preview fingerprint')
            with self.hub.db() as db:
                row = db.execute('SELECT p.*,u.role,u.enabled FROM preview_proxy_sources p JOIN users u ON u.id=p.owner WHERE p.cache_key=?', (key,)).fetchone()
            if not row or not row['enabled']:raise ValueError('Unavailable preview owner')
            path, version = self.source(row['owner'],row['role']=='admin',row['task_id'])
            if version != key:raise ValueError('Preview source changed')
            metadata = self.probe(path)
            facts = inspect(*metadata)
            if not facts['eligible'] or facts['timing_uncertain'] or facts['duration'] > 600:
                raise ValueError('Use original source')
            self.root.mkdir(exist_ok=True)
            # Only expire older published files; fresh playback remains pinned.
            files = [(p,p.stat()) for p in self.root.glob('*.mp4') if p.is_file()]
            used = sum(s.st_size for _,s in files)
            for old, stat in sorted(files,key=lambda item:item[1].st_mtime):
                if used+RESERVE <= BUDGET:break
                if time.time()-stat.st_mtime < 86400 or not re.fullmatch('[0-9a-f]{64}',old.stem):continue
                try:old.unlink()
                except OSError:continue
                used -= stat.st_size
                with self.hub.db() as db:
                    db.execute("DELETE FROM preview_proxy_sources WHERE cache_key=?",(old.stem,))
                    db.execute("DELETE FROM preview_proxy_jobs WHERE cache_key=? AND state='ready'",(old.stem,))
            if used+RESERVE > BUDGET or shutil.disk_usage(self.root).free < 2*RESERVE:
                raise ValueError('Preview cache capacity reached')
            def checked_probe(p):
                if p == path.resolve():
                    if fingerprint(p,'preview-v1') != key:raise ValueError('Preview source changed')
                    return metadata
                return self.probe(p)
            run_claim(self.hub.db,key,token,path,self.root/(key+'.mp4'),checked_probe,
                      protected=True,stopping=self.hub.stop.is_set)
        except Exception:
            # No other proxy can start while this claim exists. Recover through
            # its unique OS job before releasing an uncertain encoder.
            self.recover()
