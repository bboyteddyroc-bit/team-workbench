"""Owner-scoped, persistent manual Kalodata queries. No automatic paid retries."""
import hashlib
import json
import math
import os
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException, Request

from task_feedback import current as current_feedback

BASE_URL = 'https://www.kalodata.com/openapi/v1/tiktok'


class QueryError(Exception):
    def __init__(self,message,*,code=None,endpoint=None,reason=None,http_status=None):
        super().__init__(message)
        raw=str(code) if code is not None else ''
        self.code=raw if re.fullmatch(r'[A-Za-z0-9_-]{1,40}',raw) else None
        self.endpoint=endpoint
        self.reason=reason if reason in ('not_found','product_not_found') else None
        self.http_status=http_status

    @property
    def waiting_media(self):
        return self.code=='1054' and self.endpoint=='/video/url'


def failure_message(endpoint, data):
    """Keep actionable codes/known reasons without echoing raw provider text or URLs."""
    raw_code = str(data.get('code') or '') if isinstance(data, dict) else ''
    code = raw_code if re.fullmatch(r'[A-Za-z0-9_-]{1,40}', raw_code) else '未提供'
    path = endpoint if re.fullmatch(r'/[a-z]+/[a-z]+', endpoint) else '未识别接口'
    message = str(data.get('message') or '').strip().lower() if isinstance(data, dict) else ''
    if code == '2016':
        reason = 'API credits 余额不足，请充值后再查询'
    elif code == '1054':
        reason = '视频尚未缓存，供应商已排队获取；这不是视频地址获取成功，请稍后主动查询'
    elif code == '1053':
        reason = '供应商当前无法提供该视频；请核对视频是否存在或可访问'
    elif message in ('video not found', 'video not found.'):
        reason = '供应商返回 video not found：当前接口及查询条件下未找到该视频，不是字段填充失败'
    else:
        reason = '供应商未返回成功结果，原因未提供或未识别；请核对供应商记录'
    return f'Kalodata {path}：{reason}（错误码 {code}）；未自动重试'


def identifier(kind, value):
    value = str(value or '').strip()
    if len(value) > 500:
        raise ValueError('查询对象过长')
    if '://' in value:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not (parsed.hostname == 'tiktok.com' or (parsed.hostname or '').endswith('.tiktok.com')):
            raise ValueError('请输入 TikTok 完整链接或直接填写编号')
        if kind == 'creator':
            value = next((x[1:] for x in parsed.path.split('/') if x.startswith('@')), '')
        else:
            match = re.search(r'/(?:video|product|products)/(\d+)(?:/|$)', parsed.path)
            value = match.group(1) if match else ''
    if kind == 'creator':
        value = value.lstrip('@').lower()
        if not re.fullmatch(r'[a-z0-9_.]{1,64}', value):
            raise ValueError('请输入准确的账号 handle 或完整主页链接')
    elif kind in ('product', 'video'):
        if not re.fullmatch(r'\d{5,30}', value):
            raise ValueError('请输入商品或视频的纯数字 ID，短链接请先展开')
    else:
        raise ValueError('不支持的查询类型')
    return value


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


class Kalodata:
    def __init__(self, hub):
        self.hub = hub
        with hub.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS kalodata_jobs(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_key TEXT NOT NULL,
              fingerprint TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL,
              days INTEGER NOT NULL, end_date TEXT NOT NULL, state TEXT NOT NULL,
              created REAL NOT NULL, updated REAL NOT NULL, result TEXT, error TEXT,
              UNIQUE(owner,request_key));
            CREATE INDEX IF NOT EXISTS kalodata_owner ON kalodata_jobs(owner,created);
            CREATE TABLE IF NOT EXISTS kalodata_config(
              id INTEGER PRIMARY KEY CHECK(id=1), secret BLOB NOT NULL,
              updated REAL NOT NULL);
            ''')

    def secret(self):
        with self.hub.db() as db:
            row = db.execute('SELECT secret FROM kalodata_config WHERE id=1').fetchone()
        if row:
            try:
                return self.hub.cipher.decrypt(bytes(row['secret'])).decode('utf-8')
            except (InvalidToken, UnicodeError, ValueError):
                raise QueryError('已保存的 Kalodata 密钥无法解密，请管理员重新保存') from None
        return os.environ.get('KALODATA_SECRET_KEY', '').strip()

    def config_status(self, admin=False):
        with self.hub.db() as db:
            row = db.execute('SELECT updated FROM kalodata_config WHERE id=1').fetchone()
        try:
            configured, error = bool(self.secret()), None
        except QueryError as exc:
            configured, error = False, str(exc)
        result = dict(configured=configured, admin=admin, error=error,
                      region='US', currency='USD', automatic_monitoring=False)
        if admin:
            result.update(source='saved' if row else 'environment' if configured else 'none',
                          updated=row['updated'] if row else None)
        return result

    def post(self, endpoint, payload, secret=None):
        observed=current_feedback()
        secret = self.secret() if secret is None else secret
        if not secret:
            if observed:observed.mark('blocked')
            raise QueryError('服务进程未配置 Kalodata 密钥，请联系管理员')
        from video_case_skill import headers as skill_headers
        try:
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = client.post(BASE_URL + endpoint, json=payload,
                                       headers={'secret-key': secret,**skill_headers()})
            if observed:
                observed.http(response.status_code)
                if response.status_code in (400,401,402,403,404,422,429):observed.mark('failed')
            if response.status_code in (401, 403):
                raise QueryError('Kalodata 身份或接口权限校验失败，请管理员核对配置', http_status=response.status_code)
            if response.status_code == 429:
                raise QueryError('Kalodata 请求过于频繁；未自动重试', http_status=429)
            if response.status_code != 200:
                raise QueryError('Kalodata 请求失败；未自动重试，请稍后重新查询', http_status=response.status_code)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            if observed:
                observed.mark('unknown');observed.error_type(type(exc).__name__)
            raise QueryError('Kalodata 网络或响应异常，计费结果需核对；未自动重试') from None
        if not isinstance(data, dict) or data.get('success') is not True:
            message=str(data.get('message','')).strip().lower().rstrip('.') if isinstance(data,dict) else ''
            reason=('product_not_found' if endpoint=='/product/detail' and message=='product not found' else
                    'not_found' if message=='video not found' else None)
            error=QueryError(failure_message(endpoint, data),code=data.get('code') if isinstance(data,dict) else None,endpoint=endpoint,reason=reason)
            if observed:
                observed.code(error.code)
                if error.waiting_media:observed.mark('waiting')
            raise error
        if observed:observed.code(data.get('code'))
        return data.get('data')

    def fetch(self, job):
        # One credential snapshot per job; a rotation affects subsequent jobs.
        secret = self.secret()
        def call(endpoint, payload):
            return self.post(endpoint, payload, secret=secret)
        end = date.fromisoformat(job['end_date'])
        start = end - timedelta(days=job['days'] - 1)
        common = dict(region='US', language='en-US', currency='USD', date_range=f'{start}~{end}')
        kind, target = job['kind'], job['target']
        entity_id = target
        if kind == 'creator':
            candidates = call('/creator/rank', dict(common, keyword=target, page_size=100,
                                   page_number=1, sort_field={'field': 'revenue', 'type': 'DESC'}))
            if not isinstance(candidates, list):
                raise QueryError('Kalodata 账号列表格式变化，需检查接入')
            exact = [r for r in candidates if isinstance(r, dict) and
                     str(r.get('creator_handle', '')).lstrip('@').lower() == target]
            ids = {str(r['creator_id']) for r in exact if r.get('creator_id')}
            if not ids:
                raise QueryError('Kalodata 未收录该准确账号，或所选期间无匹配记录；不会替换为相似账号')
            if len(ids) != 1:
                raise QueryError('同名账号匹配不唯一，需人工核对')
            entity_id = ids.pop()
        detail = call('/' + kind + '/detail', dict(common, **{kind + '_id': entity_id}, need_extra=False))
        if not isinstance(detail, dict) or not detail:
            raise QueryError('Kalodata 暂无该对象的详情数据')
        if detail.get(kind + '_id') is not None and str(detail[kind + '_id']) != entity_id:
            raise QueryError('Kalodata 返回对象与请求不一致，未保存结果')
        if kind == 'creator' and detail.get('creator_handle') and str(detail['creator_handle']).lstrip('@').lower() != target:
            raise QueryError('Kalodata 返回账号与请求不一致，未保存结果')
        trend = detail.get('revenue_trend')
        # Do not guess which dates shortened or structurally changed arrays represent.
        daily = ([{'date': str(start + timedelta(days=i)), 'gmv': number(v)} for i, v in enumerate(trend)]
                 if isinstance(trend, list) and len(trend) == job['days'] else [])
        return dict(provider='Kalodata', data_type='third_party_estimate', region='US', currency='USD',
                    kind=kind, entity_id=entity_id, target=target,
                    name=str(detail.get(kind + '_name') or detail.get('creator_nickname') or detail.get('video_title') or target)[:1000],
                    period_start=str(start), period_end=str(end), fetched_at=datetime.now(timezone.utc).isoformat(),
                    gmv=number(detail.get('revenue')), units=number(detail.get('sales_volumn')),
                    views=number(detail.get('video_views' if kind == 'creator' else 'views')), video_count=number(detail.get('video_number')),
                    video_gmv=number(detail.get('video_revenue')), live_gmv=number(detail.get('live_revenue')),
                    daily_gmv=daily, trend_aligned=bool(daily),
                    planned_max_credits=0.2 if kind == 'creator' else 0.1,
                    limitations=['第三方估算，不是结算订单', '未提供字段保留为未知',
                                 '期间视频数不等于今日发片数', '不包含脚本归因、完整视频列表或逐日销量'])

    def recover(self):
        with self.hub.db() as db:
            db.execute("UPDATE kalodata_jobs SET state='attention',error='服务重启中断查询，计费结果需核对；未自动重试',updated=? WHERE state='running'", (time.time(),))

    def tick(self):
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT j.* FROM kalodata_jobs j JOIN users u ON u.id=j.owner WHERE j.state='queued' AND u.enabled=1 ORDER BY j.created LIMIT 1").fetchone()
            if not job:
                return False
            db.execute("UPDATE kalodata_jobs SET state='running',updated=? WHERE id=?", (time.time(), job['id']))
        try:
            import task_feedback as feedback
            with feedback.bound(self.hub,'kalodata',job['id']), feedback.step('metrics_query'):
                result = json.dumps(self.fetch(dict(job)), ensure_ascii=False, allow_nan=False)
            state, error = 'ready', None
        except QueryError as exc:
            result, state, error = None, 'attention', str(exc)
        except Exception:
            result, state, error = None, 'attention', '查询处理异常；未自动重试，请联系管理员'
        with self.hub.db() as db:
            db.execute('UPDATE kalodata_jobs SET state=?,result=?,error=?,updated=? WHERE id=?',
                       (state, result, error, time.time(), job['id']))
        return True

    def loop(self):
        while not self.hub.stop.is_set():
            try:
                self.tick()
            except Exception:
                pass  # Do not print upstream exceptions or credentials.
            self.hub.stop.wait(2.5)


def attach(app, hub, user, body):
    from apify_config import attach as attach_apify
    attach_apify(app, hub, user, body)
    service = Kalodata(hub)
    app.state.kalodata = service

    @app.get('/api/intelligence/kalodata/status')
    def status(request: Request):
        u = user(request)
        return service.config_status(admin=u['role']=='admin')

    @app.post('/api/intelligence/kalodata/config')
    async def config(request: Request):
        u = user(request, True)
        data = await body(request)
        secret = data.get('secret_key')
        if not isinstance(secret, str):
            raise HTTPException(400, '请填写新的 API 密钥；当前配置未修改')
        secret = secret.strip()
        if not re.fullmatch(r'[\x21-\x7e]{8,4096}', secret):
            raise HTTPException(400, '密钥应为 8–4096 位可见英文字符，不含空格；当前配置未修改')
        encrypted = hub.cipher.encrypt(secret.encode('utf-8'))
        with hub.db() as db:
            db.execute('INSERT OR REPLACE INTO kalodata_config(id,secret,updated) VALUES(1,?,?)',
                       (encrypted,time.time()))
            hub.log(db,u['id'],'kalodata_key_updated','kalodata_config')
        # Saving never makes a paid request and never returns any part of the key.
        return service.config_status(admin=True)

    def public(row):
        value = dict(row)
        for key in ('owner', 'request_key', 'fingerprint'):
            value.pop(key, None)
        value['result'] = json.loads(value['result']) if value['result'] else None
        return value

    @app.get('/api/intelligence/kalodata/jobs')
    def jobs(request: Request):
        u = user(request)
        with hub.db() as db:
            return [public(r) for r in db.execute('SELECT * FROM kalodata_jobs WHERE owner=? ORDER BY created DESC LIMIT 50', (u['id'],))]

    @app.post('/api/intelligence/kalodata/jobs')
    async def submit(request: Request):
        u = user(request)
        data = await body(request)
        try:
            kind = data.get('kind')
            target = identifier(kind, data.get('target'))
            days = data.get('days', 7)
            if type(days) is not int or days not in (7, 30):
                raise ValueError('仅支持近 7 或 30 个完整自然日')
            if data.get('region', 'US') != 'US':
                raise ValueError('当前仅接入美国市场')
            key = data.get('request_key', '')
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
                raise ValueError('请求编号无效，请刷新页面')
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from None
        # UTC boundary is explicit; never mix the host date with the data range.
        end = str(datetime.now(timezone.utc).date() - timedelta(days=1))
        fingerprint = hashlib.sha256(json.dumps([kind, target, days, end]).encode()).hexdigest()
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM kalodata_jobs WHERE owner=? AND request_key=?', (u['id'], key)).fetchone()
            if existing:
                if existing['fingerprint'] != fingerprint:
                    raise HTTPException(409, '请求编号已用于不同查询')
                return public(existing)
            if data.get('allow_paid_api') is not True:
                raise HTTPException(400, '查询需明确启用 Kalodata 计费调用')
            try:
                configured = bool(service.secret())
            except QueryError as exc:
                raise HTTPException(503, str(exc)) from None
            if not configured:
                raise HTTPException(503, '服务进程未配置 Kalodata 密钥')
            duplicate = db.execute("SELECT * FROM kalodata_jobs WHERE owner=? AND fingerprint=? AND (state IN ('queued','running') OR (state='ready' AND updated>?)) ORDER BY created DESC LIMIT 1", (u['id'], fingerprint, time.time()-900)).fetchone()
            if duplicate:
                return public(duplicate)
            if db.execute("SELECT count(*) FROM kalodata_jobs WHERE state IN ('queued','running')").fetchone()[0] >= 10:
                raise HTTPException(429, '查询队列已满，请等待已有查询完成')
            if db.execute('SELECT count(*) FROM kalodata_jobs WHERE owner=? AND created>?', (u['id'], time.time()-86400)).fetchone()[0] >= 50:
                raise HTTPException(429, '已达到每人每日 50 次查询上限')
            job_id, now = uuid.uuid4().hex, time.time()
            db.execute('INSERT INTO kalodata_jobs(id,owner,request_key,fingerprint,kind,target,days,end_date,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (job_id,u['id'],key,fingerprint,kind,target,days,end,'queued',now,now))
            hub.log(db, u['id'], 'kalodata_query_queued', job_id)
            return public(db.execute('SELECT * FROM kalodata_jobs WHERE id=?', (job_id,)).fetchone())
