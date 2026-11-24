"""Free-to-Kalodata, persistent thumbnail completion for saved product dossiers."""
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timezone

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, Request

from own_goods_erp_cover import SourceError, fetch_image
from own_goods_lookup import link_key, latest, CACHE_SECONDS
from safe_cover import CoverFetchError, image_url
from tiktok_shop_link import LinkError, check_market, listing_parts, parse, resolve

LOG = logging.getLogger(__name__)
CANDIDATE_TTL = 86400
BACKOFF = (30, 180)
SOURCES = ('kalodata', 'kalodata_cache', 'lingxing')
REASONS = {
    'short_link': '分享短链无法确认商品 ID，请换成完整的 TikTok Shop 商品页链接。',
    'unsupported': '请核对 TikTok Shop 商品链接和档案市场。',
    'no_source': '暂无同商品 ID 的主图来源。',
    'source_not_enabled': '暂无本地主图。管理员可在列表的「主图图源」启用美国站领星图源。',
    'market_not_supported': '暂无本地主图；领星自动补图目前只支持美国站（US）。',
    'inactive_owner': '录入账号已停用，未开始补图。',
    'dossier_changed': '补图期间档案已变化；未应用原图。',
    'internal_error': '自动补图未完成；已有商品资料不受影响。',
    'no_exact_image': '图源未返回此市场、此商品 ID 的唯一主图。未使用相似商品。',
    'erp_forbidden': '领星权限校验失败，请管理员检查主图图源配置。',
    'erp_unavailable': '领星主图读取未确认；没有自动重查。请管理员核对图源配置。',
    'image_unavailable': '图片服务器暂未返回可用主图。',
    'image_rejected': '图源不是可验证的商品主图，已停止。',
    'image_address_expired': '已有图源已过期，未重复查询领星。',
}


def initialize(hub):
    with hub.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS own_goods_cover_jobs(
            goods TEXT PRIMARY KEY, market TEXT NOT NULL, link_key TEXT NOT NULL,
            state TEXT NOT NULL, next_at REAL NOT NULL, updated REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
            product_id TEXT NOT NULL DEFAULT '', resolved_url TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS own_goods_cover_source_reads(
            market TEXT NOT NULL, product_id TEXT NOT NULL, config_version REAL NOT NULL,
            reason TEXT NOT NULL, PRIMARY KEY(market,product_id,config_version));
        CREATE INDEX IF NOT EXISTS own_cover_due ON own_goods_cover_jobs(state,next_at);
        CREATE INDEX IF NOT EXISTS own_cover_product ON own_goods_cover_jobs(market,product_id) WHERE product_id<>'';
        CREATE TABLE IF NOT EXISTS own_goods_cover_candidates(
            market TEXT NOT NULL, product_id TEXT NOT NULL, source TEXT NOT NULL,
            sealed_url BLOB NOT NULL, expires REAL NOT NULL, PRIMARY KEY(market,product_id));
        CREATE TABLE IF NOT EXISTS own_goods_cover_config(
            id INTEGER PRIMARY KEY CHECK(id=1), secret BLOB NOT NULL, updated REAL NOT NULL,
            generation REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
        ''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS own_cover_exact_cache_available AFTER INSERT ON goods_details
            WHEN new.kind='shop' BEGIN
                UPDATE own_goods_cover_jobs SET state='queued',reason='',attempts=0,
                    next_at=CAST(strftime('%s','now') AS REAL),updated=CAST(strftime('%s','now') AS REAL)
                WHERE market='US' AND product_id=new.key AND state='blocked'
                    AND reason IN ('source_not_enabled','no_source','no_exact_image','erp_unavailable','erp_forbidden');
            END''')
        db.execute('BEGIN IMMEDIATE')
        if 'source' not in {r[1] for r in db.execute('PRAGMA table_info(own_goods_listing_images)')}:
            db.execute("ALTER TABLE own_goods_listing_images ADD COLUMN source TEXT NOT NULL DEFAULT 'kalodata'")
        columns = {r[1] for r in db.execute('PRAGMA table_info(own_goods_cover_config)')}
        if 'enabled' not in columns:
            db.execute('ALTER TABLE own_goods_cover_config ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1')
        if 'generation' not in columns:
            db.execute('ALTER TABLE own_goods_cover_config ADD COLUMN generation REAL NOT NULL DEFAULT 0')
            db.execute('UPDATE own_goods_cover_config SET generation=updated')


def _identity(goods, lookup=None, job=None):
    """An automatic image is bound to the current link and market, not the title/SKU."""
    market = goods['market']
    pid = listing_parts(goods['url'], market)[1]
    if pid:
        return pid
    try:
        p, match = parse(goods['url'])
        check_market(p, match, market)
    except LinkError:
        return ''
    if match:
        return ''
    for candidate in (lookup, job):
        if candidate and candidate['market']==market and candidate['link_key']==link_key(goods['url']):
            pid = listing_parts(candidate['resolved_url'], market)[1]
            if pid and pid==candidate['product_id']:
                return pid
    return ''


def resolved_short(db, goods, lookup=None):
    """Use only a verified resolution tied to this exact saved share link."""
    if _identity(goods, lookup):
        return None
    job = db.execute('SELECT * FROM own_goods_cover_jobs WHERE goods=?', (goods['id'],)).fetchone()
    return job if _identity(goods, None, job) else None


def image_record(db, goods, lookup=None, *, picture=False):
    if lookup is None:
        lookup = latest(db, goods)
    pid = _identity(goods, lookup)
    if not pid:
        job = resolved_short(db, goods, lookup)
        pid = job['product_id'] if job else ''
    if not pid:
        return None
    cols = 'version,observed,source,picture' if picture else 'version,observed,source'
    return db.execute(f'SELECT {cols} FROM own_goods_listing_images WHERE market=? AND product_id=?',
                      (goods['market'],pid)).fetchone()


def store_image(db, market, pid, picture, source, now):
    if source not in SOURCES or not re.fullmatch('[0-9]{5,32}', pid):
        raise ValueError('Invalid listing image identity')
    # Never rewrite an existing verified image; manual images are a separate table.
    return db.execute('''INSERT OR IGNORE INTO own_goods_listing_images
        (market,product_id,version,observed,picture,source) VALUES(?,?,?,?,?,?)''',
        (market,pid,hashlib.sha256(picture).hexdigest()[:16],now,picture,source)).rowcount


def remember(hub, db, market, pid, url, source, now, *, goods=''):
    normalized = image_url(url, product=True).geturl()
    sealed = hub.cipher.encrypt(normalized.encode('ascii'))
    db.execute('''INSERT INTO own_goods_cover_candidates VALUES(?,?,?,?,?)
               ON CONFLICT(market,product_id) DO UPDATE SET source=excluded.source,
               sealed_url=excluded.sealed_url,expires=excluded.expires''',
               (market,pid,source,sealed,now+CANDIDATE_TTL))
    if source != 'lingxing':
        wake_for_image(db, market, pid, now, goods=goods)


def wake_for_image(db, market, pid, now, *, goods=''):
    # The product ID is already known to the caller. Rechecking a same-link short URL
    # can now reuse its saved lookup identity instead of doing another redirect.
    db.execute("""UPDATE own_goods_cover_jobs SET state='queued',next_at=?,updated=?,attempts=0,reason=''
        WHERE market=? AND (product_id=? OR goods=?) AND state IN ('retry','blocked')
        AND reason<>'unsupported'""", (now,now,market,pid,goods))


def release_candidate(db, market, pid):
    db.execute('DELETE FROM own_goods_cover_candidates WHERE market=? AND product_id=?', (market,pid))


def queue(db, goods, now, *, legacy=False):
    state, reason, pid = 'queued','',''
    try:
        p, match = parse(goods['url'])
        check_market(p, match, goods['market'])
        pid = match['id'] if match else _identity(goods, latest(db, goods))
        if legacy and not pid:
            # Do not replay an unresolved legacy share link; it might already be blocked.
            state, reason = 'blocked','short_link'
    except LinkError:
        state, reason = 'blocked','unsupported'
    db.execute('''INSERT INTO own_goods_cover_jobs(goods,market,link_key,state,next_at,updated,reason,product_id)
         VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(goods) DO UPDATE SET market=excluded.market,
         link_key=excluded.link_key,state=excluded.state,next_at=excluded.next_at,updated=excluded.updated,
         attempts=0,reason=excluded.reason,product_id=excluded.product_id,resolved_url=''
         WHERE excluded.market<>own_goods_cover_jobs.market OR excluded.link_key<>own_goods_cover_jobs.link_key
         OR own_goods_cover_jobs.reason='dossier_changed' ''',
         (goods['id'],goods['market'],link_key(goods['url']),state,now,now,reason,pid))


def progress(db, goods, cover, lookup=None, *, compact=False):
    if cover['cover_source'] and compact:
        return 'ready'
    row = db.execute('''SELECT * FROM own_goods_cover_jobs WHERE goods=? AND market=? AND link_key=?''',
                     (goods['id'],goods['market'],link_key(goods['url']))).fetchone()
    try:
        p, match = parse(goods['url'])
        check_market(p,match,goods['market'])
        valid = True
    except LinkError:
        valid, match = False,None
    if cover['cover_source']:
        state, reason = 'ready',''
    elif not valid:
        state, reason = 'blocked','unsupported'
    elif db.execute('''SELECT 1 FROM own_goods g JOIN users u ON u.id=g.owner AND u.enabled=1
                        WHERE g.id=?''', (goods['id'],)).fetchone() is None:
        state, reason = 'blocked','inactive_owner'
    elif row and row['state']!='ready':
        state, reason = row['state'],row['reason']
    elif not row and not match and not _identity(goods, lookup if lookup is not None else latest(db,goods)):
        state, reason = 'blocked','short_link'
    else:
        state, reason = 'queued',''
    if compact:
        return state
    pid = _identity(goods, lookup, row)
    resolved = ''
    if pid:
        if match:
            resolved = p.geturl()
        else:
            resolved = next((r['resolved_url'] for r in (lookup,row) if r and r['product_id']==pid
                             and listing_parts(r['resolved_url'],goods['market'])[1]==pid),'')
    return {'state':state,'message':REASONS.get(reason,''),
            'next_at':row['next_at'] if state=='retry' else None,'product_id':pid,'resolved_url':resolved}


def _thumbnail(url):
    from own_goods_cover import listing_thumbnail
    try:
        return listing_thumbnail(url)
    except CoverFetchError as exc:
        if (exc.reason in ('CdnTimeout','CdnConnectionFailed','CdnBusy','CdnTruncated','CdnEmpty')
                or exc.status==429 or exc.status is not None and 500<=exc.status<=599):
            raise SourceError('image_unavailable') from None
        raise SourceError('image_rejected') from None
    except (HTTPException,ValueError,OSError):
        raise SourceError('image_rejected') from None


def _existing_detail(db, market, pid, now):
    if market != 'US':  # Existing competitor detail cache is queried in US only.
        return ''
    row = db.execute("SELECT payload FROM goods_details WHERE kind='shop' AND key=?", (pid,)).fetchone()
    if not row:
        return ''
    try:
        data = json.loads(row[0]); raw = data.get('master_image_url')
        if str(data.get('product_id',pid)) != pid or data.get('region',market) != market:
            return ''
        observed = datetime.combine(date.fromisoformat(data.get('end','')),datetime.min.time(),tzinfo=timezone.utc).timestamp()
        return image_url(raw, product=True).geturl() if now-CACHE_SECONDS<=observed<=now else ''
    except (AttributeError, TypeError, ValueError, OverflowError, OSError):
        return ''


class CoverWorker:
    def __init__(self, hub):
        self.hub = hub
        self.scan_after = 0

    def recover(self):
        now=time.time()
        with self.hub.db() as db:
            # Do not replay a short-link read whose outcome was never recorded.
            db.execute("""UPDATE own_goods_cover_jobs SET
                state=CASE WHEN product_id='' OR attempts>? THEN 'blocked' ELSE 'queued' END,
                reason=CASE WHEN product_id='' THEN 'short_link' WHEN attempts>? THEN 'image_unavailable' ELSE '' END,
                next_at=?,updated=? WHERE state='running'""", (len(BACKOFF),len(BACKOFF),now,now))

    def _current(self, db, job):
        goods = db.execute('''SELECT g.* FROM own_goods g JOIN users u ON u.id=g.owner AND u.enabled=1
            WHERE g.id=? AND g.archived IS NULL AND NOT EXISTS(SELECT 1 FROM own_goods_covers c WHERE c.goods=g.id)''',
            (job['goods'],)).fetchone()
        if not goods or goods['market']!=job['market'] or link_key(goods['url'])!=job['link_key']:
            return None
        owner = db.execute('''SELECT 1 FROM own_goods_cover_jobs WHERE goods=? AND market=? AND link_key=?
            AND state='running' AND attempts=? AND updated=?''',
            (job['goods'],job['market'],job['link_key'],job['attempts'],job['updated'])).fetchone()
        return goods if owner else None

    def _finish(self, db, job, state, reason='', delay=0):
        now=time.time()
        db.execute('''UPDATE own_goods_cover_jobs SET state=?,reason=?,next_at=?,updated=?
            WHERE goods=? AND market=? AND link_key=? AND state='running' AND attempts=? AND updated=?''',
            (state,reason,now+delay,now,job['goods'],job['market'],job['link_key'],job['attempts'],job['updated']))

    def tick(self):
        if self.hub.stop.is_set():
            return False
        now=time.time()
        with self.hub.db() as db:
            # The steady-state idle worker does not take a write lock on every tick.
            if now>=self.scan_after:
                db.execute('BEGIN IMMEDIATE')
                rows = db.execute('''SELECT g.id,g.url,g.market FROM own_goods g JOIN users u ON u.id=g.owner AND u.enabled=1
                  WHERE g.archived IS NULL AND NOT EXISTS(SELECT 1 FROM own_goods_covers c WHERE c.goods=g.id)
                  AND NOT EXISTS(SELECT 1 FROM own_goods_cover_jobs j WHERE j.goods=g.id) ORDER BY g.id LIMIT 48''').fetchall()
                for row in rows:
                    queue(db,row,now,legacy=True)
                db.execute('DELETE FROM own_goods_cover_candidates WHERE expires<=?', (now,))
                self.scan_after=now+(3 if len(rows)==48 else 60)
                db.commit()
            selection = '''SELECT j.* FROM own_goods_cover_jobs j JOIN own_goods g ON g.id=j.goods
              JOIN users u ON u.id=g.owner AND u.enabled=1 WHERE g.archived IS NULL
              AND j.state IN ('queued','retry') AND j.next_at<=? AND j.market=g.market
              AND NOT EXISTS(SELECT 1 FROM own_goods_covers c WHERE c.goods=j.goods)
              AND NOT EXISTS(SELECT 1 FROM own_goods_lookup l WHERE l.market=j.market AND
                   ((l.goods=j.goods AND l.link_key=j.link_key) OR (j.product_id<>'' AND l.product_id=j.product_id))
                   AND (l.state IN ('queued','resolving','fetching') OR l.image_state='checking'))
              ORDER BY j.next_at,j.goods LIMIT 1'''
            if not db.execute(selection,(now,)).fetchone():
                return False
            db.execute('BEGIN IMMEDIATE')
            job = db.execute(selection,(now,)).fetchone()
            if not job:
                return False
            job = dict(job)
            # Guard a stale completion even if the link is changed away and back.
            job['attempts'] += 1
            job['updated'] = max(now, job['updated']+0.000001)
            db.execute("UPDATE own_goods_cover_jobs SET state='running',attempts=?,updated=? WHERE goods=?",
                       (job['attempts'],job['updated'],job['goods']))
        try:
            with self.hub.db() as db:
                goods = self._current(db,job)
                if not goods:
                    self._finish(db,job,'blocked','dossier_changed')
                    return True
                prior = latest(db,goods)
                pid = _identity(goods,prior,job)
                if listing_parts(goods['url'],goods['market'])[1]:
                    resolved = ''  # A complete URL already supplies the report identity.
                else:
                    resolved = prior['resolved_url'] if prior and _identity(goods,prior) else job['resolved_url']
            self._process(job,goods,pid,resolved)
        except SourceError as exc:
            self._failure(job,exc.reason, retry=exc.reason=='image_unavailable')
        except Exception:
            self._failure(job,'internal_error',retry=False)
            LOG.warning('Own goods thumbnail job failed; no Kalodata transport was attempted')
        return True

    def _failure(self, job, reason, *, retry):
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._current(db,job):
                self._finish(db,job,'blocked','dossier_changed')
                return
            if job['market']=='US' and 'source_revision' in job:
                config = db.execute('SELECT updated FROM own_goods_cover_config WHERE id=1 AND enabled=1').fetchone()
                if config and config['updated']!=job['source_revision']:
                    self._finish(db,job,'queued')
                    return
            if retry and 1<=job['attempts']<=len(BACKOFF):
                self._finish(db,job,'retry',reason,BACKOFF[job['attempts']-1])
            else:
                self._finish(db,job,'blocked',reason)

    def _matches(self, db, job, pid):
        goods = self._current(db,job)
        if not goods:
            self._finish(db,job,'blocked','dossier_changed')
            return False
        bound = _identity(goods,latest(db,goods))
        if bound and bound!=pid:
            self._finish(db,job,'queued')
            return False
        return True

    def _process(self, job, goods, pid, resolved):
        market = job['market']
        if not pid:
            try:
                resolved,pid=resolve(goods['url'],market)
            except LinkError:
                raise SourceError('short_link') from None
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._matches(db,job,pid):
                return
            # Persist a successful resolution even when a stop arrives before the download.
            db.execute('UPDATE own_goods_cover_jobs SET product_id=?,resolved_url=? WHERE goods=?', (pid,resolved,job['goods']))
            if self.hub.stop.is_set():
                self._finish(db,job,'queued')
                return
            if db.execute('SELECT 1 FROM own_goods_listing_images WHERE market=? AND product_id=?',(market,pid)).fetchone():
                self._finish(db,job,'ready')
                return
            now = time.time()
            retained = db.execute('''SELECT sealed_url,source FROM own_goods_cover_candidates
                                    WHERE market=? AND product_id=? AND expires>?''',(market,pid,now)).fetchone()
            cached = _existing_detail(db,market,pid,now)
            config = db.execute('SELECT secret,updated,generation FROM own_goods_cover_config WHERE id=1 AND enabled=1').fetchone()
            job['source_revision'] = config['updated'] if config else None
        choices = []
        if retained:
            try:
                choices.append((self.hub.cipher.decrypt(retained['sealed_url']).decode('ascii'),retained['source']))
            except (InvalidToken,UnicodeError):
                pass
        if cached and all(existing!=cached for existing,_ in choices):
            choices.append((cached,'kalodata_cache'))
        outcome = 'market_not_supported' if market!='US' else 'source_not_enabled' if not config else 'no_source'
        tried, picture = set(), None
        for url, source in choices:
            if self.hub.stop.is_set():
                break
            tried.add(url)
            try:
                picture = _thumbnail(url)
                break
            except SourceError as exc:
                outcome = exc.reason
                if source=='lingxing' and outcome=='image_unavailable':
                    # Retry the cached image URL, not another read of the ERP report.
                    raise
        if not picture and config and market=='US' and not self.hub.stop.is_set():
            try:
                key=self.hub.cipher.decrypt(config['secret']).decode('ascii')
            except (InvalidToken,UnicodeError):
                raise SourceError('erp_forbidden') from None
            scope = (market,pid,config['generation'])
            with self.hub.db() as db:
                db.execute('BEGIN IMMEDIATE')
                current_config = db.execute('SELECT 1 FROM own_goods_cover_config WHERE id=1 AND enabled=1 AND updated=?', (config['updated'],)).fetchone()
                if not self._matches(db,job,pid):
                    return
                if not current_config or self.hub.stop.is_set():
                    self._finish(db,job,'queued')
                    return
                read = db.execute('SELECT reason FROM own_goods_cover_source_reads WHERE market=? AND product_id=? AND config_version=?',scope).fetchone()
                if read:
                    raise SourceError(outcome if outcome!='no_source' else read['reason'])
                # One read per listing per saved configuration. Unknown outcomes are not replayed.
                db.execute("INSERT INTO own_goods_cover_source_reads VALUES(?,?,?,'erp_unavailable')", scope)
            source = 'lingxing'
            try:
                url = fetch_image(key,market,pid)
            except SourceError as exc:
                with self.hub.db() as db:
                    db.execute('UPDATE own_goods_cover_source_reads SET reason=? WHERE market=? AND product_id=? AND config_version=?', (exc.reason,*scope))
                raise
            # Retain the address before CDN I/O. A retry can reuse it without searching ERP again.
            with self.hub.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if not self._matches(db,job,pid):
                    return
                db.execute("UPDATE own_goods_cover_source_reads SET reason='image_address_expired' WHERE market=? AND product_id=? AND config_version=?", scope)
                remember(self.hub,db,market,pid,url,source,time.time())
            if url not in tried and not self.hub.stop.is_set():
                picture = _thumbnail(url)
        if not picture and not self.hub.stop.is_set():
            raise SourceError(outcome)
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._matches(db,job,pid):
                return
            if not picture:
                self._finish(db,job,'queued')
            else:
                store_image(db,market,pid,picture,source,time.time())
                release_candidate(db,market,pid)
                self._finish(db,job,'ready')

    def loop(self):
        while not self.hub.stop.is_set():
            try:
                self.tick()
            except Exception:
                LOG.warning('Own goods thumbnail queue could not advance')
            self.hub.stop.wait(3)


def attach(app, hub, user, body):
    from own_goods import PREFIX
    initialize(hub)
    app.state.own_goods_covers=CoverWorker(hub)

    def projection(db):
        row = db.execute('SELECT updated,enabled FROM own_goods_cover_config WHERE id=1').fetchone()
        return {'configured':row is not None, 'enabled':bool(row and row['enabled']),
                'updated':row['updated'] if row else None}

    @app.get(PREFIX+'/cover-source')
    def config_state(request: Request):
        user(request,admin=True)
        with hub.db() as db:
            return projection(db)

    @app.post(PREFIX+'/cover-source')
    async def save_source(request: Request):
        actor=user(request,admin=True)
        data=await body(request)
        key, enabled = data.get('key',''), data.get('enabled')
        if (type(enabled) is not bool or 'expected_updated' not in data or
                type(data['expected_updated']) not in (float,int,type(None)) or not isinstance(key,str) or
                key and (not enabled or not re.fullmatch("[A-Za-z0-9._+/=-]{12,512}",key))):
            raise HTTPException(400,'请核对设置；只在此输入领星 MCP 密钥，不要粘贴配置 JSON 或地址。')
        now=time.time()
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM own_goods_cover_config WHERE id=1').fetchone()
            if (old['updated'] if old else None)!=data['expected_updated']:
                raise HTTPException(409,'图源配置已变更，请关闭后重新查看。')
            if not old and not key:
                raise HTTPException(400,'首次启用需要领星 MCP 密钥。')
            changed = bool(key)
            if key and old:
                try:
                    changed = hub.cipher.decrypt(old['secret'])!=key.encode('ascii')
                except InvalidToken:
                    pass
            if old and not changed and enabled==bool(old['enabled']):
                return projection(db)
            if old:
                now=max(now,old['updated']+0.000001)
            sealed = hub.cipher.encrypt(key.encode('ascii')) if changed else old['secret']
            db.execute('''INSERT OR REPLACE INTO own_goods_cover_config(id,secret,updated,generation,enabled)
                           VALUES(1,?,?,?,?)''', (sealed,now,now if changed else old['generation'],int(enabled)))
            if enabled:
                db.execute('''UPDATE own_goods_cover_jobs SET state='queued',attempts=0,reason='',next_at=?,updated=?
                    WHERE market='US' AND state IN ('blocked','retry') AND reason NOT IN ('unsupported','short_link')''', (now,now))
            hub.log(db,actor['id'],'own_goods_cover_source_updated','lingxing')
            return projection(db)
