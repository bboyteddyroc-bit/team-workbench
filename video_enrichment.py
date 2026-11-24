"""Durable, owner-scoped Kalodata enrichment for videos already collected by Apify.

Only the existing single LAN worker executes calls. Ambiguous paid calls never retry.
"""
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException, Request
from kalodata_integration import QueryError, number

RETRY = 12 * 3600    # 抓取之后每 12 小时自动重查一次
GIVE_UP = 72 * 3600  # 72 小时仍无数据才停止，避免对未收录视频无限付费
MIN_AGE = 86400      # 发布满 1 天才开始查：太新的视频 Kalodata 一定还没有数据
# 全局补数开关 + 勾选名单：只有「全局开启」且「账号仍被勾选」才允许付费补数。
# 取消勾选等于暂停排队中的补数，重新勾选立即恢复；已有结果不动。
GATE = '''
  AND a.deleted_at IS NULL
  AND EXISTS(SELECT 1 FROM auto_collection_config g WHERE g.owner=a.owner AND g.enrichment_enabled=1)
  AND EXISTS(SELECT 1 FROM auto_collection_selection s WHERE s.owner=a.owner AND s.account=c.account AND s.selected=1)'''


class VideoEnrichment:
    def __init__(self, hub, kalodata):
        self.hub, self.kalodata = hub, kalodata
        with hub.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS video_enrichment_config(
              account TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
              days INTEGER NOT NULL DEFAULT 30, daily_limit INTEGER NOT NULL DEFAULT 30,
              paused INTEGER NOT NULL DEFAULT 0, error TEXT, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS video_enrichment_jobs(
              id TEXT PRIMARY KEY, account TEXT NOT NULL, video TEXT NOT NULL,
              period_start TEXT NOT NULL, period_end TEXT NOT NULL,
              state TEXT NOT NULL, next_at REAL NOT NULL DEFAULT 0,
              created REAL NOT NULL, updated REAL NOT NULL, started REAL,
              attempts INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
              UNIQUE(account,video,period_start,period_end));
            CREATE INDEX IF NOT EXISTS enrichment_due ON video_enrichment_jobs(state,next_at);
            CREATE TABLE IF NOT EXISTS video_enrichment_calls(
              id TEXT PRIMARY KEY, job TEXT NOT NULL, account TEXT NOT NULL,
              started REAL NOT NULL, state TEXT NOT NULL);
            ''')
            # 补数改为「一批采集补一批」：任务记录它属于哪次采集，账号记录已排过哪一批。
            if 'run' not in {row['name'] for row in db.execute('PRAGMA table_info(video_enrichment_jobs)')}:
                db.execute('ALTER TABLE video_enrichment_jobs ADD COLUMN run TEXT')
            if 'last_run' not in {row['name'] for row in db.execute('PRAGMA table_info(video_enrichment_config)')}:
                db.execute('ALTER TABLE video_enrichment_config ADD COLUMN last_run TEXT')
            db.execute('CREATE INDEX IF NOT EXISTS enrichment_wave ON video_enrichment_jobs(account,run)')
            # 历史任务没有 run 字段；回填到该账号最近一次成功采集，避免升级后马上重复买同一批视频。
            try:
                db.execute('''UPDATE video_enrichment_jobs SET run=(SELECT r.id FROM apify_runs r
                  WHERE r.account=video_enrichment_jobs.account AND r.state='ready'
                  ORDER BY r.updated DESC, r.created DESC LIMIT 1) WHERE run IS NULL''')
                db.execute('''UPDATE video_enrichment_config SET last_run=(SELECT j.run FROM video_enrichment_jobs j
                  WHERE j.account=video_enrichment_config.account AND j.run IS NOT NULL
                  ORDER BY j.created DESC, j.rowid DESC LIMIT 1) WHERE last_run IS NULL''')
            except sqlite3.OperationalError:
                pass

    def recover(self):
        with self.hub.db() as db:
            # A crash can occur after the remote service charges but before local commit.
            db.execute("UPDATE video_enrichment_config SET paused=1,error='补数期间服务重启，计费结果需核对；未自动重试' WHERE account IN (SELECT account FROM video_enrichment_jobs WHERE state='running')")
            db.execute("UPDATE video_enrichment_calls SET state='attention' WHERE state='running'")
            db.execute("UPDATE video_enrichment_jobs SET state='attention',error='补数期间服务重启，计费结果需核对；未自动重试',updated=? WHERE state='running'", (time.time(),))

    def plan(self, now=None):
        now = time.time() if now is None else now
        # 发布满 1 天才查（MIN_AGE）；窗口末日取昨天，超新视频留给下一批采集。
        end = datetime.fromtimestamp(now, timezone.utc).date() - timedelta(days=1)
        cutoff = now - MIN_AGE
        with self.hub.db() as db:
            # 兼容升级前已勾选但尚无旧版逐账号配置的记录。
            db.execute('''INSERT OR IGNORE INTO video_enrichment_config(account,updated)
              SELECT a.id,? FROM apify_accounts a JOIN auto_collection_selection s
                ON s.account=a.id AND s.owner=a.owner AND s.selected=1
              JOIN auto_collection_config g ON g.owner=a.owner AND g.enrichment_enabled=1''', (now,))
            configs = db.execute('''SELECT c.* FROM video_enrichment_config c
              JOIN apify_accounts a ON a.id=c.account JOIN users u ON u.id=a.owner
              WHERE c.paused=0 AND u.enabled=1'''+GATE).fetchall()
            for config in configs:
                # 只跟随「最近一次成功采集」：没有新采集就绝不自己触发付费查询。
                try:
                    run = db.execute('''SELECT id FROM apify_runs WHERE account=? AND state='ready'
                      ORDER BY updated DESC, created DESC LIMIT 1''', (config['account'],)).fetchone()
                except sqlite3.OperationalError:
                    continue
                if not run or run['id'] == config['last_run']:
                    continue
                start = end - timedelta(days=config['days'] - 1)
                videos = db.execute('''SELECT video,MAX(published) published FROM apify_snapshots
                  WHERE account=? AND run=? GROUP BY video ORDER BY published DESC''',
                  (config['account'], run['id'])).fetchall()
                for video in videos:
                    # Unknown publish date requires manual review, never a paid guess.
                    if video['published'] is None or video['published'] > cutoff:
                        continue
                    # 上一次采集里放弃过的视频，新一批仍会重试（补齐优先），同批不会重复买。
                    # Don't stack a fresh paid task on top of an unresolved/uncertain call.
                    active = db.execute('''SELECT 1 FROM video_enrichment_jobs WHERE account=? AND video=?
                      AND state IN ('queued','running','waiting','attention') LIMIT 1''',
                      (config['account'], video['video'])).fetchone()
                    if active:
                        continue
                    db.execute('''INSERT OR IGNORE INTO video_enrichment_jobs
                      (id,account,video,run,period_start,period_end,state,next_at,created,updated)
                      VALUES(?,?,?,?,?,?,'queued',?,?,?)''',
                      (uuid.uuid4().hex, config['account'], video['video'], run['id'], str(start), str(end), now, now, now))
                db.execute('UPDATE video_enrichment_config SET last_run=? WHERE account=?', (run['id'], config['account']))

    def tick(self, now=None):
        self.plan(now)
        # Missing key isn't an attempt; queue remains durable until configuration is saved.
        try:
            if not self.kalodata.secret():
                return False
        except QueryError:
            return False
        now = time.time() if now is None else now
        midnight = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('''SELECT j.*,a.handle FROM video_enrichment_jobs j
              JOIN video_enrichment_config c ON c.account=j.account
              JOIN apify_accounts a ON a.id=j.account JOIN users u ON u.id=a.owner
              WHERE c.paused=0 AND u.enabled=1'''+GATE+'''
                AND j.state IN ('queued','waiting') AND j.next_at<=?
                AND (c.daily_limit<=0 OR (SELECT COUNT(*) FROM video_enrichment_calls x
                     WHERE x.account=j.account AND x.started>=?) < c.daily_limit)
              ORDER BY j.next_at,j.created,j.id LIMIT 1''', (now, midnight)).fetchone()
            if not job:
                return False
            job = dict(job)
            call_id = uuid.uuid4().hex
            db.execute("UPDATE video_enrichment_jobs SET state='running',started=?,updated=?,attempts=attempts+1 WHERE id=?", (now, now, job['id']))
            db.execute("INSERT INTO video_enrichment_calls VALUES(?,?,?,?,'running')", (call_id, job['id'], job['account'], now))
        try:
            payload = dict(region='US', language='en-US', currency='USD',
                           date_range=job['period_start']+'~'+job['period_end'],
                           video_id=job['video'], need_extra=False)
            import task_feedback as feedback
            with feedback.bound(self.hub,'video_enrichment',job['id']), feedback.step('metrics_query') as attempt:
                detail = self.kalodata.post('/video/detail', payload)
                if detail is None or detail == {}:
                    attempt.mark('waiting')
                elif not isinstance(detail, dict) or str(detail.get('video_id', '')) != job['video']:
                    raise QueryError('Kalodata 视频 ID 不匹配或格式变化；已暂停补数')
                else:
                    author = str(detail.get('belonged_creator_handle') or '').lstrip('@').lower()
                    if author and author != job['handle']:
                        raise QueryError('Kalodata 返回视频所属账号不匹配；已暂停补数')
            if detail is None or detail == {}:
                # Kalodata 有滞后：抓取后每 12 小时重查，直到这一批视频全部补齐。
                expired = now - job['created'] >= GIVE_UP
                state = 'unavailable' if expired else 'waiting'
                error = ('Kalodata 72 小时内未收录此视频，已停止补数' if expired
                         else 'Kalodata 暂未收录；12 小时后自动重查')
                result = None
            else:
                trend = detail.get('revenue_trend')
                start = datetime.fromisoformat(job['period_start']).date()
                length = (datetime.fromisoformat(job['period_end']).date() - start).days + 1
                aligned = isinstance(trend, list) and len(trend) == length
                daily = [{'date':str(start+timedelta(days=i)), 'gmv':number(v)} for i,v in enumerate(trend)] if aligned else []
                data = dict(provider='Kalodata', data_type='third_party_estimate', currency='USD', region='US',
                            video_id=job['video'], period_start=job['period_start'], period_end=job['period_end'],
                            fetched_at=time.time(), gmv=number(detail.get('revenue')),
                            units=number(detail.get('sales_volumn')), gpm=number(detail.get('video_gpm')),
                            period_views=number(detail.get('views')), daily_gmv=daily, trend_aligned=aligned)
                result, state, error = json.dumps(data, ensure_ascii=False, allow_nan=False), 'ready', None
        except Exception as exc:
            # Only known sanitized application errors may leave this service.
            error = str(exc) if isinstance(exc, QueryError) else '补数处理异常，计费结果需核对；未自动重试'
            result, state = None, 'attention'
        with self.hub.db() as db:
            db.execute('''UPDATE video_enrichment_jobs SET state=?,result=?,error=?,updated=?,next_at=? WHERE id=?''',
                       (state, result, error, now, now + RETRY, job['id']))
            db.execute('UPDATE video_enrichment_calls SET state=? WHERE id=?', (state, call_id))
            if state == 'attention':
                db.execute('UPDATE video_enrichment_config SET paused=1,error=?,updated=? WHERE account=?',
                           (error, now, job['account']))
        return True

    def loop(self):
        import logging
        while not self.hub.stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                logging.getLogger(__name__).error('Video enrichment worker failure (%s)', type(exc).__name__)
                # If post-call persistence failed, never leave a running call silently stuck.
                self.recover()
            self.hub.stop.wait(10)

    def status(self, account):
        with self.hub.db() as db:
            config = db.execute('SELECT * FROM video_enrichment_config WHERE account=?', (account,)).fetchone()
            counts = {r['state']:r['n'] for r in db.execute('''SELECT state,COUNT(*) n FROM video_enrichment_jobs
              WHERE account=? GROUP BY state''', (account,))}
            calls = db.execute('SELECT COUNT(*) FROM video_enrichment_calls WHERE account=? AND started>=?',
                               (account, datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())).fetchone()[0]
            total = db.execute('SELECT COUNT(DISTINCT video) FROM apify_snapshots WHERE account=?', (account,)).fetchone()[0]
        value = dict(config) if config else dict(enabled=0, days=30, daily_limit=30, paused=0, error=None)
        value.pop('account', None)
        value.update(counts=counts, calls_today=calls, tracked_videos=total)
        return value

    def video(self, account, video):
        with self.hub.db() as db:
            latest = db.execute('''SELECT state,error,period_start,period_end,updated FROM video_enrichment_jobs
              WHERE account=? AND video=? ORDER BY created DESC,rowid DESC LIMIT 1''', (account,video)).fetchone()
            success = db.execute('''SELECT result FROM video_enrichment_jobs WHERE account=? AND video=?
              AND state='ready' ORDER BY updated DESC LIMIT 1''', (account,video)).fetchone()
        return dict(status=dict(latest) if latest else None, data=json.loads(success['result']) if success else None)


def attach(app, hub, user, body):
    service = VideoEnrichment(hub, app.state.kalodata)
    app.state.video_enrichment = service

    @app.post('/api/intelligence/apify/accounts/{aid}/enrichment')
    async def configure(aid: str, request: Request):
        u = user(request)
        with hub.db() as db:
            account = db.execute('SELECT id FROM apify_accounts WHERE id=? AND owner=? AND deleted_at IS NULL', (aid,u['id'])).fetchone()
        if not account:
            raise HTTPException(404, '账号不存在')
        data = await body(request)
        enabled, days, limit = data.get('enabled'), data.get('days',30), data.get('daily_limit',30)
        if type(enabled) is not bool or type(days) is not int or days not in (7,30) or type(limit) is not int or not 0<=limit<=300:
            raise HTTPException(400, '请选择开关、7/30 日统计区间及每日上限（0 表示不限，最多 300）')
        if enabled:
            if data.get('allow_paid') is not True:
                raise HTTPException(400, '开启自动补数需确认 Kalodata 计费')
            try:
                if not service.kalodata.secret():
                    raise HTTPException(400, '请先配置 Kalodata 密钥')
            except QueryError as exc:
                raise HTTPException(400, str(exc)) from None
        with hub.db() as db:
            db.execute('''INSERT INTO video_enrichment_config(account,enabled,days,daily_limit,updated)
              VALUES(?,?,?,?,?) ON CONFLICT(account) DO UPDATE SET enabled=excluded.enabled,
              days=excluded.days,daily_limit=excluded.daily_limit,paused=0,error=NULL,updated=excluded.updated''',
              (aid,int(enabled),days,limit,time.time()))
            hub.log(db,u['id'],'video_enrichment_enabled' if enabled else 'video_enrichment_disabled',aid)
        # No paid request in the HTTP handler. Existing and future snapshots are planned by worker.
        return service.status(aid)

    return service
