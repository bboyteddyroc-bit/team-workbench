"""Bounded, scrubbed step feedback for existing Studio and Intelligence tasks.

Only fixed field names/operation codes and scalar observations enter the journal.
It is not a task queue, retry mechanism, or payment ledger. All readers must
first check access to the underlying business task.
"""
import contextlib
import contextvars
import logging
import re
import secrets
import sqlite3
import time
from collections import defaultdict

from fastapi import HTTPException

STAGES = {
    'quota': '核对账号与额度', 'upload': '上传参考素材', 'submit': '提交视频生成',
    'poll': '查询原生成任务', 'history': '核对平台历史', 'video_download': '下载生成视频',
    'save_task': '保存任务状态', 'libtv_account': '核对 LibTV 账号', 'libtv_model': '核对模型',
    'libtv_project': '创建画布', 'libtv_node': '设置生成节点', 'libtv_probe': '核对画布成片',
    'libtv_save': '成片校验与入库',
    'apify_submit': '提交 Apify 采集', 'apify_payload': '准备采集参数', 'apify_key': '选取 Apify 密钥',
    'apify_connection': '准备 Apify 请求', 'apify_response': '读取 Apify 提交响应',
    'apify_run_id': '解析 Apify 运行编号', 'apify_record': '保存 Apify 运行编号',
    'apify_poll': '查询 Apify 运行状态', 'apify_dataset': '读取 Apify 数据集', 'apify_save': '采集结果入库',
    'comment_page': '获取评论页', 'reply_page': '获取回复页',
    'comment_save': '评论页入库', 'reply_save': '回复页入库',
    'ai_preflight': '核对 AI 配置与授权', 'ai_call': '请求 AI 分析', 'ai_validate': '校验 AI 返回', 'ai_save': '保存 AI 结果',
    'case_metrics': '查询案例指标', 'metrics_query': '查询 Kalodata 指标', 'media_url': '获取案例视频地址', 'media_download': '下载案例视频',
    'media_prepare': '核验本地视频', 'transcript': '提取本地口播', 'data_save': '保存处理结果',
    'resolve_shop_link': '识别 TikTok Shop 商品链接', 'shop_product_detail': '查询 Kalodata 商品详情',
    'shop_listing_image': '获取 TikTok Shop 商品主图',
}
KINDS = {'tiktok', 'libtv', 'apify_run', 'apify_group', 'case_metadata', 'case_metrics',
         'case_analysis', 'case_text', 'case_transcript', 'comment_collect', 'comment_ai', 'comment_research',
         'script_labels', 'script_create', 'script_transcript', 'kalodata', 'video_enrichment', 'own_goods_lookup'}
OUTCOMES = {'ok', 'failed', 'unknown', 'attention', 'blocked', 'waiting'}
ID = re.compile(r'[A-Za-z0-9_-]{1,96}\Z')
# Only code-shaped numeric metadata is allowed, never arbitrary upstream strings.
CODE = re.compile(r'-?[0-9]{1,12}\Z')
_PARENT = contextvars.ContextVar('task_feedback_parent', default=None)
_CURRENT = contextvars.ContextVar('task_feedback_step', default=None)
_MAX_GLOBAL = 50000
_MAX_TASK = 48
_LOG = logging.getLogger(__name__)
_last_write_warning = float('-inf')


def init_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS task_feedback(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, task TEXT NOT NULL,
            reference TEXT NOT NULL, stage TEXT NOT NULL, outcome TEXT NOT NULL,
            at REAL NOT NULL, duration_ms INTEGER NOT NULL, http_status INTEGER,
            provider_code TEXT, cli_exit INTEGER, credits INTEGER,
            error_type TEXT, transport_started INTEGER, remote_id_seen INTEGER);
        CREATE INDEX IF NOT EXISTS task_feedback_timeline ON task_feedback(kind,task,seq DESC);
        CREATE INDEX IF NOT EXISTS task_feedback_exceptions ON task_feedback(kind,task,seq DESC)
            WHERE outcome NOT IN ('ok','waiting');
    ''')


@contextlib.contextmanager
def bound(hub, kind, task, *, retrieval=False):
    path = getattr(hub, 'path', None)
    parent = _PARENT.set((path, kind, task, retrieval) if path and kind in KINDS and isinstance(task, str) and ID.fullmatch(task) else None)
    active = _CURRENT.set(None)
    try:
        yield
    finally:
        _CURRENT.reset(active)
        _PARENT.reset(parent)


class Attempt:
    def __init__(self, stage):
        self.stage = stage
        self.outcome = None
        self.at = time.time()
        self.started = time.monotonic()
        self._http = self._code = self._exit = self._credits = None
        self._error_type = self._transport = self._remote = None

    def error_type(self, value):
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', value):
            self._error_type = value

    def transport(self, started, has_id):
        self._transport = int(started is True)
        self._remote = int(has_id is True)

    def mark(self, outcome):
        if outcome in OUTCOMES:
            self.outcome = outcome

    def move(self, stage):
        if stage in STAGES:
            self.stage = stage

    def http(self, value):
        if type(value) is int and 100 <= value <= 599:
            self._http = value

    def code(self, value):
        if type(value) in (str, int) and CODE.fullmatch(str(value)):
            self._code = str(value)

    def exit_code(self, value):
        if type(value) is int and -2**31 <= value < 2**32:
            self._exit = value

    def credits(self, value):
        if type(value) is int and 0 <= value < 10**9:
            self._credits = value


def current():
    return _CURRENT.get()


def _record(parent, attempt):
    global _last_write_warning
    path, kind, task, _ = parent
    outcome = attempt.outcome or 'ok'
    at = attempt.at
    duration = int(max(0, time.monotonic() - attempt.started) * 1000)
    ref = 'FB-' + secrets.token_hex(6).upper()
    # Keep observation best-effort. Contention must not delay business writes or
    # change a provider outcome. This uses its own short transaction, after the step.
    try:
        with contextlib.closing(sqlite3.connect(path, timeout=.06)) as db, db:
            seq = db.execute('''INSERT INTO task_feedback(kind,task,reference,stage,outcome,at,duration_ms,http_status,provider_code,cli_exit,credits,error_type,transport_started,remote_id_seen)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                             (kind, task, ref, attempt.stage, outcome, at, duration, attempt._http,
                              attempt._code, attempt._exit, attempt._credits, attempt._error_type, attempt._transport, attempt._remote)).lastrowid
            # Routine polls should not immediately erase the most useful older exceptions.
            bucket = "outcome IN ('ok','waiting')" if outcome in ('ok', 'waiting') else "outcome NOT IN ('ok','waiting')"
            keep = 32 if outcome in ('ok', 'waiting') else _MAX_TASK - 32
            db.execute(f'''DELETE FROM task_feedback WHERE kind=? AND task=? AND {bucket} AND seq<=
                       (SELECT seq FROM task_feedback WHERE kind=? AND task=? AND {bucket} ORDER BY seq DESC LIMIT 1 OFFSET ?)''',
                       (kind, task, kind, task, keep))
            if seq > _MAX_GLOBAL:
                db.execute('DELETE FROM task_feedback WHERE seq<=?', (seq - _MAX_GLOBAL,))
    except (sqlite3.Error, OSError):
        now = time.monotonic()
        if now - _last_write_warning >= 60:
            _last_write_warning = now
            _LOG.warning('Task feedback write unavailable (kind=%s, step=%s); business state unchanged', kind, attempt.stage)


@contextlib.contextmanager
def step(stage, failure='attention'):
    attempt = Attempt(stage)
    parent = _PARENT.get()
    if parent and parent[3] and failure=='blocked':failure='attention'
    if parent is None or stage not in STAGES:
        yield attempt
        return
    token = _CURRENT.set(attempt)
    try:
        yield attempt
    except Exception as exc:
        if attempt._error_type is None:
            attempt.error_type(type(exc).__name__)
        if attempt.outcome in (None, 'ok'):
            attempt.mark(failure)
        raise
    finally:
        _CURRENT.reset(token)
        if parent:
            _record(parent, attempt)


def outcome(state, error='', latest=None):
    """Classify the business outcome conservatively, not the HTTP result or billing."""
    error = str(error or '')
    if state == 'unknown':
        return 'unknown'
    if state in ('failed', 'attention', 'partial'):
        if latest and latest['outcome'] in ('blocked', 'unknown', 'failed'):
            return latest['outcome']
        if not latest and re.search(r'(?:[；。]未提交生成|生成尚未(?:提交|启动)|生成前校验未通过)', error):
            return 'blocked'
        if state == 'failed':
            return 'failed'
        if re.search(r'(?:结果(?:或计费)?(?:可能)?未知|结果待核对|状态无法确认|提交结果可能不明确|计费结果需核对)', error):
            return 'unknown'
        return 'attention'
    return state


def project(row):
    data = dict(row)
    data['stage'] = STAGES.get(data['stage'], '阶段未留存')
    return data


_SUMMARY = 'reference,stage,outcome,at,duration_ms,http_status,provider_code,cli_exit,credits'
_PUBLIC = _SUMMARY + ',error_type,transport_started,remote_id_seen'


def latest_failures(db, keys):
    """One grouped query per applicable kind, not one read per card."""
    groups = defaultdict(set)
    for kind, task in keys:
        if kind in KINDS:
            groups[kind].add(task)
    result = {}
    for kind, ids in groups.items():
        ids = sorted(ids)
        for i in range(0, len(ids), 200):
            batch = ids[i:i+200]
            marks = ','.join('?' for _ in batch)
            rows = db.execute(f'''SELECT task,{_SUMMARY} FROM task_feedback WHERE seq IN
                (SELECT max(seq) FROM task_feedback WHERE kind=? AND task IN ({marks})
                 AND outcome NOT IN ('ok','waiting') GROUP BY task)''', (kind, *batch))
            for row in rows:
                data = project(row)
                result[(kind, data.pop('task'))] = data
    return result


def timeline(db, kind, task):
    return [project(r) for r in db.execute(
        f'SELECT {_PUBLIC} FROM task_feedback WHERE kind=? AND task=? ORDER BY seq DESC LIMIT ?',
        (kind, task, _MAX_TASK))]


def valid_task(task):
    if not ID.fullmatch(task):
        raise HTTPException(404, '任务不存在')
