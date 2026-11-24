"""Opt-in TikTok Shop identity and Kalodata metadata for own goods.

The worker only consumes confirmed requests. Each paid call is fenced by a durable
(market, product ID) claim before transport, separate from the editable dossier.
"""
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from html import unescape
from uuid import uuid4

from fastapi import HTTPException, Request

import task_feedback as feedback
from kalodata_integration import QueryError
from product_research_tags import product_profile
from safe_cover import CoverFetchError, image_url
from tiktok_shop_link import LinkError, check_market, parse, resolve

US = 'US'  # Match the current Hub product integration, never silently query another market.
ACTIVE = ('queued', 'resolving', 'fetching')
ACTIVE_SQL = "state IN ('queued','resolving','fetching') OR image_state='checking'"
MAX_QUEUE, MAX_DAILY = 10, 50
CACHE_SECONDS = 7 * 86400
UNKNOWN = 'Kalodata 查询或计费结果需核对；未再次提交。请管理员核对供应商记录。'
LOG = logging.getLogger(__name__)


def initialize(hub):
    with hub.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS own_goods_lookup(
            id TEXT PRIMARY KEY, goods TEXT NOT NULL, owner TEXT NOT NULL,
            link_key TEXT NOT NULL, market TEXT NOT NULL, state TEXT NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL,
            product_id TEXT NOT NULL DEFAULT '', resolved_url TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}', observed REAL, reused INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '', error_code TEXT, retry INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS own_lookup_dossier ON own_goods_lookup(goods,market,link_key,created DESC);
        CREATE INDEX IF NOT EXISTS own_lookup_queue ON own_goods_lookup(state,created);
        CREATE INDEX IF NOT EXISTS own_lookup_owner ON own_goods_lookup(owner,created);
        CREATE INDEX IF NOT EXISTS own_lookup_cache ON own_goods_lookup(market,product_id,observed DESC) WHERE state='ready';
        CREATE UNIQUE INDEX IF NOT EXISTS own_lookup_claim ON own_goods_lookup(market,product_id)
            WHERE state IN ('fetching','unknown');
        CREATE TABLE IF NOT EXISTS own_goods_listing_images(
            market TEXT NOT NULL, product_id TEXT NOT NULL, version TEXT NOT NULL,
            observed REAL NOT NULL, picture BLOB NOT NULL, PRIMARY KEY(market,product_id));
        ''')
        db.execute('BEGIN IMMEDIATE')
        if 'image_state' not in {col[1] for col in db.execute('PRAGMA table_info(own_goods_lookup)')}:
            db.execute("ALTER TABLE own_goods_lookup ADD COLUMN image_state TEXT NOT NULL DEFAULT ''")


def link_key(url):
    try:
        url = parse(url)[0].geturl()
    except LinkError:
        pass
    return hashlib.sha256(url.encode()).hexdigest()


def latest(db, goods):
    return db.execute('''SELECT * FROM own_goods_lookup WHERE goods=? AND market=? AND link_key=?
                      ORDER BY created DESC,rowid DESC LIMIT 1''',
                      (goods['id'], goods['market'], link_key(goods['url']))).fetchone()


def dossier_profile(db, goods, override=''):
    row = latest(db, goods)
    confirmed = {json.loads(r[0])[1] for r in db.execute('''SELECT tag_key FROM research_tag_reviews
        WHERE entity='goods' AND ref=? AND decision='confirmed' AND json_extract(tag_key,'$[0]')='细品类' ''', (goods['id'],))}
    return product_profile(goods, override, dict(row) if row else None, confirmed)


def eligible(goods):
    if goods['market'] != US:
        return '当前 Kalodata 商品接入仅支持美国市场（US），不会改用其他市场查询。'
    try:
        p, m = parse(goods['url'])
        check_market(p, m, goods['market'])
    except LinkError as exc:
        return str(exc)
    return ''


def listing_image(db, goods, lookup, *, picture=False):
    from tiktok_shop_link import listing_parts
    if not lookup or lookup['state'] != 'ready' or lookup['market'] != goods['market']:
        return None
    pid = listing_parts(lookup['resolved_url'], goods['market'])[1]
    if not pid or pid != lookup['product_id'] or lookup['link_key'] != link_key(goods['url']):
        return None
    columns = 'version,observed,picture' if picture else 'version,observed'
    return db.execute(f'SELECT {columns} FROM own_goods_listing_images WHERE market=? AND product_id=?',
                      (goods['market'], pid)).fetchone()


def status(db, goods):
    from own_goods_cover import displayed_cover
    reason = eligible(goods)
    row = latest(db, goods) if not reason else None
    cover = displayed_cover(db, goods, row)
    if reason:
        return {'state': 'unsupported', 'error': reason, 'can_lookup': False, **cover}
    if not row:
        return {'state': 'idle', 'can_lookup': True, **cover}
    return {k: row[k] for k in ('id','state','product_id','resolved_url','observed','updated','error','error_code','reused','image_state')} | {
        'source': json.loads(row['metadata']), 'can_lookup': bool(row['retry']), **cover}


def text(value, limit):
    if not isinstance(value, str):
        return ''
    text = unescape(value[:limit * 4])
    text = re.sub(r'<[^>]{0,400}>', ' ', text)
    text = re.sub(r'(?i)(?:https?://|www\.)[^\s<>]+', ' ', text)
    text = re.sub(r'[\x00-\x1f\x7f-\x9f\ud800-\udfff\u202a-\u202e\u2066-\u2069]', ' ', text)
    return ' '.join(text.split())[:limit]


def description(value):
    # The vendor contract permits rich text blocks with text/t/sub; not arbitrary JSON.
    stack, chunks, n = [(value, 0)], [], 0
    while stack and n < 120:
        item, depth = stack.pop()
        n += 1
        if depth > 6:
            continue
        if isinstance(item, str):
            chunks.append(text(item, 640))
        elif isinstance(item, list):
            stack.extend((x, depth + 1) for x in reversed(item[:48]))
        elif isinstance(item, dict):
            stack.append((item.get('text') or item.get('t') or item.get('sub'), depth + 1))
    return ' '.join(chunk for chunk in chunks if chunk)[:1400]


def metadata(data, basis):
    name = text(data.get('product_name'), 300)
    return {'name': '' if name.isdecimal() else name,
            'shop': text(data.get('shop_name') or data.get('product_shop_name'), 160),
            'category': text(data.get('category_name'), 110),
            'description': description(data.get('product_description')),
            'basis': basis}


class InvalidDetail(ValueError):
    pass


def exact_detail(data, pid, market):
    if isinstance(data, dict) and 'product_id' not in data and 'data' in data:
        data = data['data']
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict) or not data:
        raise InvalidDetail('Kalodata 暂无此商品的资料；未替换为相似商品。')
    received = data.get('product_id')
    if type(received) not in (str, int) or str(received) != pid:
        raise InvalidDetail('Kalodata 未返回一致的商品 ID，未采用资料或标签。')
    if data.get('region') and data['region'] != market:
        raise InvalidDetail('Kalodata 返回的地区与档案市场不一致，未采用资料或标签。')
    result = metadata(data, 'detail')
    url, image_state = image_candidate(data.get('master_image_url'))
    if not url and not any(result[key] for key in ('name', 'category', 'description')):
        raise InvalidDetail('已确认商品 ID，但 Kalodata 未提供可用的名称、类目、描述或主图。')
    return result, url, image_state


def image_candidate(value):
    if value in (None, ''):
        return '', 'missing'
    try:
        return image_url(value, product=True).geturl(), 'checking'
    except ValueError:
        return '', 'unavailable'


def cache(db, market, pid, now):
    row = db.execute('''SELECT metadata,observed,image_state FROM own_goods_lookup WHERE state='ready'
                      AND market=? AND product_id=? AND observed BETWEEN ? AND ?
                      ORDER BY observed DESC,created DESC LIMIT 1''', (market, pid, now-CACHE_SECONDS, now)).fetchone()
    if row:
        image_state = 'missing' if row['image_state'] in ('', 'missing') else 'unavailable'
        return row['metadata'], row['observed'], '', image_state
    if market != US:
        return None
    # Exact-ID US /product/detail cache. Keep signed URLs transient, not in the dossier.
    row = db.execute("SELECT payload FROM goods_details WHERE kind='shop' AND key=?", (pid,)).fetchone()
    if row:
        try:
            data = json.loads(row[0])
            if not isinstance(data, dict) or (data.get('region') and data['region']!=market):
                return None
            if 'product_id' in data and str(data['product_id']) != pid:
                return None
            day = date.fromisoformat(data.get('end') or '')
            observed = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError, OverflowError, OSError):
            return None
        if now-CACHE_SECONDS <= observed <= now:
            clean = metadata({k: data.get(k) for k in ('product_name', 'shop_name')}, 'existing_detail_cache')
            url, image_state = image_candidate(data.get('master_image_url'))
            if clean['name'] or url:
                return json.dumps(clean, ensure_ascii=False), observed, url, image_state
    return None


class Lookup:
    def __init__(self, hub, kalodata):
        self.hub = hub
        self.kalodata = kalodata

    def recover(self):
        now = time.time()
        with self.hub.db() as db:
            db.execute("UPDATE own_goods_lookup SET state='failed',error='服务在解析链接时中断，未发起 Kalodata 查询。',retry=1,updated=? WHERE state='resolving'", (now,))
            db.execute("UPDATE own_goods_lookup SET state='unknown',error=?,updated=? WHERE state='fetching'", (UNKNOWN, now))
            db.execute("UPDATE own_goods_lookup SET image_state='unavailable',updated=? WHERE image_state='checking'", (now,))

    def _current(self, db, job):
        row = db.execute('''SELECT g.url,g.market FROM own_goods g JOIN users u ON u.id=? AND u.enabled=1
            WHERE g.id=? AND g.archived IS NULL AND (g.owner=u.id OR u.role='admin')''',
            (job['owner'], job['goods'])).fetchone()
        if row and row['market'] == job['market'] and link_key(row['url']) == job['link_key']:
            return row
        return None

    def _set(self, db, job, state, *, error='', code=None, retry=False, values=None):
        db.execute('''UPDATE own_goods_lookup SET state=?,updated=?,error=?,error_code=?,retry=? WHERE id=?''',
                   (state, time.time(), error, code, int(retry), job['id']))
        if values:
            # Only the worker supplies values, never arbitrary payload keys.
            db.execute('''UPDATE own_goods_lookup SET metadata=?,observed=?,reused=? WHERE id=?''', (*values, job['id']))

    def _ready(self, db, job, pid, data, observed, url, image_state, *, reused):
        # Commit the text and identity before downloading the optional thumbnail.
        # Image problems must not turn an observed Kalodata response into an unknown charge.
        have_image = db.execute('SELECT 1 FROM own_goods_listing_images WHERE market=? AND product_id=?',
                                (job['market'], pid)).fetchone()
        if have_image and (reused or not url):
            url, image_state = '', 'ready'
        elif url and (self.hub.stop.is_set() or not self._current(db, job)):
            url, image_state = '', 'unavailable'
        self._set(db, job, 'ready', values=(data, observed, int(reused)))
        db.execute('UPDATE own_goods_lookup SET image_state=? WHERE id=?', (image_state, job['id']))
        return url

    def _download_image(self, job, pid, url):
        if not url:
            return
        picture = None
        with feedback.step('shop_listing_image') as step:
            try:
                if not self.hub.stop.is_set():
                    from own_goods_cover import listing_thumbnail
                    picture = listing_thumbnail(url)
            except CoverFetchError as exc:
                step.error_type(exc.reason)
                step.http(exc.status)
            except HTTPException:
                step.error_type('ListingImageRejected')
            except (ValueError, OSError):
                step.error_type('ListingImageUnavailable')
            if not picture:
                # Only bounded diagnostics; never record a signed URL or response body.
                step.mark('attention')
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM own_goods_lookup WHERE id=? AND image_state='checking'", (job['id'],)).fetchone():
                return
            fetched = bool(picture and self._current(db, job))
            if fetched:
                db.execute('''INSERT INTO own_goods_listing_images(market, product_id, version, observed, picture)
                              VALUES(?,?,?,?,?) ON CONFLICT(market,product_id) DO UPDATE SET
                              version=excluded.version, observed=excluded.observed, picture=excluded.picture''',
                           (job['market'], pid, hashlib.sha256(picture).hexdigest()[:16], time.time(), picture))
            db.execute('UPDATE own_goods_lookup SET image_state=?,updated=? WHERE id=?',
                       ('ready' if fetched else 'unavailable', time.time(), job['id']))

    def tick(self):
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT * FROM own_goods_lookup WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if not job:
                return False
            goods = self._current(db, job)
            if not goods:
                self._set(db, job, 'cancelled', error='档案链接、市场或操作权限已变更，未发起 Kalodata 查询。', retry=True)
                return True
            self._set(db, job, 'resolving')
        try:
            with feedback.bound(self.hub, 'own_goods_lookup', job['id']):
                self._process(job, goods['url'])
        except Exception:
            with self.hub.db() as db:
                actual=db.execute('SELECT state,image_state FROM own_goods_lookup WHERE id=?',(job['id'],)).fetchone()
                if actual and actual['state']=='fetching':
                    self._set(db, job, 'unknown', error=UNKNOWN)
                elif actual and actual['state']=='resolving':
                    self._set(db, job, 'failed', error='准备查询时处理失败，未发起 Kalodata 查询。', retry=True)
                elif actual and actual['image_state']=='checking':
                    db.execute("UPDATE own_goods_lookup SET image_state='unavailable',updated=? WHERE id=?",(time.time(),job['id']))
            LOG.warning('Own goods lookup stopped; a claimed call was not resubmitted')
        return True

    def _process(self, job, url):
        try:
            with feedback.step('resolve_shop_link') as step:
                try:
                    resolved, pid = (job['resolved_url'], job['product_id']) if job['product_id'] else resolve(url, job['market'])
                except LinkError:
                    step.mark('failed')
                    raise
        except LinkError as exc:
            with self.hub.db() as db:
                self._set(db, job, 'failed', error=str(exc) + ' 未发起 Kalodata 查询。', retry=True)
            return
        except Exception:
            with self.hub.db() as db:
                self._set(db, job, 'failed', error='链接识别异常，未发起 Kalodata 查询；可换完整商品链接。', retry=True)
            LOG.warning('Own goods lookup link resolver failed')
            return

        try:
            secret = self.kalodata.secret()
        except QueryError:
            secret = ''
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._current(db, job) or self.hub.stop.is_set():
                self._set(db, job, 'cancelled', error='档案或服务状态已变化，未发起 Kalodata 查询。', retry=True)
                return
            db.execute('UPDATE own_goods_lookup SET resolved_url=?,product_id=? WHERE id=?', (resolved, pid, job['id']))
            existing = cache(db, job['market'], pid, time.time())
            if existing:
                image = self._ready(db, job, pid, *existing, reused=True)
            else:
                prior = db.execute('''SELECT state FROM own_goods_lookup WHERE market=? AND product_id=?
                    AND (state IN ('fetching','unknown') OR (state='attention' AND error_code='unusable'))
                    ORDER BY created DESC LIMIT 1''', (job['market'], pid)).fetchone()
                if prior:
                    error = ('同市场同商品已有查询正在执行；未重复提交。' if prior['state'] == 'fetching' else
                             '同市场同商品已有查询但未取得可用资料；请核对原记录，未重复提交。' if prior['state'] == 'attention' else UNKNOWN)
                    self._set(db, job, 'attention', error=error, retry=prior['state'] == 'fetching')
                    return
                if not secret:
                    self._set(db, job, 'failed', error='未配置可用的 Kalodata 密钥，未发起查询。请在「数据接入」核对。', retry=True)
                    return
                self._set(db, job, 'fetching')  # Commit before transport. Recovery never replays this state.
        if existing:
            self._download_image(job, pid, image)
            return

        end = datetime.now(timezone.utc).date() - timedelta(days=1)
        params = dict(region=job['market'], language='en-US', currency='USD',
                      date_range=f'{end - timedelta(days=29)}~{end}', product_id=pid, need_extra=True, need_image=1)
        state, error, code, retry = 'unknown', UNKNOWN, None, False
        values = None
        try:
            with feedback.step('shop_product_detail') as step:
                step.transport(True, False)
                try:
                    data = self.kalodata.post('/product/detail', params, secret=secret)
                    clean, url, image_state = exact_detail(data, pid, job['market'])
                except InvalidDetail as exc:
                    state, error, code = 'attention', str(exc), 'unusable'
                    step.mark('attention')
                except QueryError as exc:
                    code = exc.code if feedback.CODE.fullmatch(exc.code or '') else None
                    if code == '2016' or exc.http_status == 402:
                        state, error, retry = 'failed', 'Kalodata API Credits 余额不足或支付受限；请核对额度后再手动查询。', True
                    elif exc.reason == 'product_not_found' or exc.http_status == 404:
                        state, error, code = 'attention', 'Kalodata 未收录此商品或当前市场无可用详情，未替换为相似商品。', 'unusable'
                    elif exc.http_status in (400, 401, 403, 422, 429):
                        state, error, retry = 'failed', str(exc), True
                    step.mark(state)
                else:
                    state, error = 'ready', ''
                    values = (json.dumps(clean, ensure_ascii=False), time.time(), url, image_state)
        except Exception:
            LOG.warning('Own goods lookup did not finish cleanly after a provider claim')
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if values:
                image = self._ready(db, job, pid, *values, reused=False)
            else:
                self._set(db, job, state, error=error, code=code, retry=retry)
                image = ''
        self._download_image(job, pid, image)

    def loop(self):
        while not self.hub.stop.is_set():
            try:
                self.tick()
            except Exception:
                LOG.warning('Own goods lookup could not advance; no automatic resubmission')
            self.hub.stop.wait(2.5)


def attach(app, hub, user, body):
    from own_goods import PREFIX, get_goods, require_editor, revision

    lookup = app.state.own_goods_lookup = Lookup(hub, app.state.kalodata)

    @app.get(PREFIX+'/{gid}/lookup')
    def read_lookup(gid: str, request: Request):
        user(request)
        with hub.db() as db:
            db.execute('BEGIN')
            return status(db, get_goods(db, gid))

    @app.post(PREFIX+'/{gid}/lookup')
    async def request_lookup(gid: str, request: Request):
        actor = user(request)
        data = await body(request)
        if data.get('confirmed') is not True:
            raise HTTPException(400, '请确认这次查询可能消耗 Kalodata API Credits。')
        seen = data.get('last_lookup_id', '')
        if not isinstance(seen, str) or (seen and not re.fullmatch(r'[0-9a-f]{32}', seen)):
            raise HTTPException(400, '取数状态无效，请刷新档案。')
        now = time.time()
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            goods = get_goods(db, gid)
            require_editor(goods, actor)
            if goods['revision'] != revision(data):
                raise HTTPException(409, '档案有更新，请刷新后再查询。')
            if reason := eligible(goods):
                raise HTTPException(400, reason)
            old = latest(db, goods)
            if (seen != (old['id'] if old else '') or
                    old and (old['state'] in ACTIVE or not old['retry'])):
                return status(db, goods)
            if db.execute('SELECT count(*) FROM own_goods_lookup WHERE '+ACTIVE_SQL).fetchone()[0] >= MAX_QUEUE:
                raise HTTPException(429, '自营商品取数队列已满，请稍后查看。')
            if db.execute('SELECT count(*) FROM own_goods_lookup WHERE owner=? AND created>?', (actor['id'], now-86400)).fetchone()[0] >= MAX_DAILY:
                raise HTTPException(429, '已达自营商品 24 小时查询上限，请稍后再试。')
            jid = uuid4().hex
            db.execute('''INSERT INTO own_goods_lookup(id,goods,owner,link_key,market,state,created,updated,resolved_url,product_id)
                        VALUES(?,?,?,?,?,'queued',?,?,?,?)''',
                        (jid, gid, actor['id'], link_key(goods['url']), goods['market'], now, now,
                         old['resolved_url'] if old else '', old['product_id'] if old else ''))
            hub.log(db, actor['id'], 'own_goods_lookup_requested', jid)
            return status(db, goods)

    return lookup
