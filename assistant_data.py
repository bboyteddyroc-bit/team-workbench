"""Allowlisted, permission-preserving workbench data for assistant conversations."""
import inspect
import json
import logging
import re
from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class Reader:
    label: str
    match: str
    path: str
    fields: str
    items: str = 'items'
    page_size: int = 0


READERS = (
    Reader('素材管理', '素材|参考图|参考音频', '/api/workspace/materials-page', 'id name mime size category classification_status created', page_size=8),
    Reader('制作台任务', '生成任务|制作台|生成视频|视频生成', '/api/tasks', 'id state duration created updated queue_reason owner_name account_name feedback_state error'),
    Reader('LibTV 任务', 'LibTV|生成任务|制作台|生成视频|视频生成', '/api/libtv/jobs', 'id state stage duration model resolution created updated feedback_state'),
    Reader('剪辑工程', '剪辑工程|剪辑项目|剪辑台|工程列表', '/api/editor/projects', 'id title version created updated'),
    Reader('导出成品', '导出|成品|归档', '/api/editor/exports', 'id name project_id state created error'),
    Reader('配音任务', '配音|音色', '/api/voice/jobs', 'id state completion_state timeline_status created duration model fmt', items='jobs'),
    Reader('飞书归档', '飞书|归档', '/api/feishu/uploads', 'export_id day state phase'),
    Reader('内容复用', '内容复用|案例|视频拆解', '/api/intelligence/cases', 'id video url handle case_number review_status metrics tagging fields updated', page_size=8),
    Reader('自营商品', '自营商品|商品证据', '/api/intelligence/own-goods', 'id name market shop sku links topics tag_profile', page_size=24),
    Reader('商品与店铺', '竞品|商品与店铺|店铺', '/api/intelligence/goods', 'id name shop shop_name', items='goods'),
    Reader('爆款文案库', '爆款文案|口播稿|逐字稿', '/api/intelligence/scripts', 'id video account_handle video_url description transcript_original transcript_en transcript_zh tags updated work_status transcript_status'),
    Reader('脚本任务', '脚本任务|脚本运营', '/api/intelligence/creative-tasks', 'id number title state updated reference_video'),
    Reader('Kalodata 查询记录', 'Kalodata 查询|Kalodata 查询记录|补数查询记录', '/api/intelligence/kalodata/jobs', 'id kind target days end_date state created updated'),
    Reader('异常任务', '异常任务|失败记录', '/api/intelligence/exceptions', 'id kind title state created updated feedback_state error'),
    Reader('TikTok 公司账号池', '公司账号池|账号连接', '/api/accounts', 'name status checked enabled scope'),
    Reader('LibTV 账号', 'LibTV 账号|LibTV连接|LibTV 连接', '/api/libtv/profiles', 'name connected enabled status', items='profiles'),
    Reader('团队成员', '团队成员|成员列表', '/api/users', 'username role enabled'),
    Reader('操作记录', '操作记录|操作日志', '/api/audit', 'at username action'),
    Reader('存储管理', '存储|磁盘|空间', '/api/storage-status', 'free total level warning_bytes critical_bytes', items=''),
)

HANDLE = re.compile(r'@([a-zA-Z0-9_.]{1,40})')
VIDEO = re.compile(r'(?:/video/|视频\s*(?:ID|号|编号)?\s*[:：]?\s*)(\d{5,25})', re.I)
DATA_INTENT = re.compile(r'查|列|看|统计|汇总|多少|几个|几条|哪些|明细|记录|分析|数据|状态|有没有|给我|展示|第\s*\d+\s*页')
HOWTO = re.compile(r'如何|怎么|在哪里|入口|能不能|有哪些功能')
PAGE_SIZE = 8
LOGGER = logging.getLogger(__name__)


def endpoints(app):
    return {route.path: route.endpoint for route in app.routes
            if 'GET' in getattr(route, 'methods', ()) and not inspect.iscoroutinefunction(route.endpoint)}


def catalog(app):
    routes = endpoints(app)
    labels = [reader.label for reader in READERS if reader.path in routes]
    if '/api/intelligence/apify/accounts' in routes and '/api/intelligence/apify/accounts/{aid}/videos' in routes:
        labels.insert(0, '竞对账号（@账号、视频表现、已保存分析）')
    return '、'.join(labels)


def pick(row, fields):
    if not isinstance(row, dict):
        return {}
    return {key: row[key] for key in fields.split() if key in row}


def read(routes, path, request, **kwargs):
    if path not in routes:
        raise HTTPException(404, '当前服务未提供这个查询')
    return routes[path](request=request, **kwargs)


def page_number(query):
    match = re.search(r'第\s*(\d{1,4})\s*页', query)
    return min(2000, max(1, int(match[1]))) if match else 1


def general(routes, request, reader, page, search):
    kwargs = {}
    if reader.page_size:
        kwargs['offset'] = (page - 1) * reader.page_size
        kwargs['q'] = search
        if reader.page_size == PAGE_SIZE:
            kwargs['limit'] = PAGE_SIZE
    if reader.label == '自营商品' and search and '/api/intelligence/own-goods/{gid}' in routes:
        matches = read(routes, reader.path, request, q=search)['items']
        if len(matches) == 1:
            record = read(routes, '/api/intelligence/own-goods/{gid}', request, gid=matches[0]['id'])
            return pick(record, 'id name shop market sku links topics tag_profile')
    if reader.path == '/api/editor/projects':
        kwargs['summary'] = True
    if reader.path == '/api/voice/jobs':
        kwargs['limit'] = 50
    if reader.path == '/api/tasks':
        kwargs.update(offset=(page - 1) * PAGE_SIZE, compact=True)
    result = read(routes, reader.path, request, **kwargs)
    if not reader.items:
        return pick(result, reader.fields)
    rows = result if isinstance(result, list) else result.get(reader.items, [])
    if not isinstance(rows, list):
        return {'说明': '这个入口未返回可读取的记录'}
    if search and not reader.page_size:
        rows = [row for row in rows if search.casefold() in ' '.join(
            str(row.get(key, '')) for key in ('title', 'name', 'description', 'handle', 'username')).casefold()]
    if reader.page_size:
        start, size = 0, reader.page_size
    elif reader.path == '/api/tasks':
        start, size = 0, PAGE_SIZE
    else:
        start, size = (page - 1) * PAGE_SIZE, PAGE_SIZE
    items = [pick(row, reader.fields) for row in rows[start:start + size]]
    return {'页': page, '每页最多': size, '入口返回总数': result.get('total') if isinstance(result, dict) else (None if reader.path == '/api/tasks' else len(rows)),
            '查询范围': '该中台页面已保存记录，以原页面的时间和数量范围为准', '记录': items}


def account_query(routes, hub, request, handle, page, video, search):
    accounts = read(routes, '/api/intelligence/apify/accounts', request)
    candidates = [row for row in accounts if str(row.get('handle', '')).casefold() == handle.casefold()]
    if len(candidates) > 1:
        selected = [row for row in candidates if row.get('owner_name') and row['owner_name']==search]
        if len(selected) != 1:
            return {'账号': '@'+handle, '说明': '同名账号有多份监测档案，请用引号指定添加成员',
                    '添加成员': [row.get('owner_name') for row in candidates]}
        candidates = selected
    account = candidates[0] if candidates else None
    if account is None:
        return {'账号': '@' + handle, '说明': '可见监测账号中没有找到这个名称'}
    aid = account['id']
    with hub.db() as db:
        count = db.execute('SELECT count(DISTINCT video) FROM apify_snapshots WHERE account=?', (aid,)).fetchone()[0]
        offset = (page - 1) * PAGE_SIZE
        if offset >= count and page > 1 and not video:
            return {'账号': '@' + handle, '已采集视频数': count, '说明': '该页超出范围'}
        rows = [dict(row) for row in db.execute("""WITH latest AS (
            SELECT video,title,published,collected,views,likes,comments,shares,collects,
                row_number() OVER (PARTITION BY video ORDER BY collected DESC,run DESC) AS rn
            FROM apify_snapshots WHERE account=? AND (?='' OR video=?)
        )
        SELECT l.*, (SELECT id FROM video_cases c
            WHERE c.platform='TikTok' AND c.video=l.video AND c.removed_at IS NULL) AS case_id
        FROM latest l WHERE rn=1 ORDER BY published DESC,video DESC LIMIT ? OFFSET ?""",
            (aid, video, video, PAGE_SIZE, 0 if video else offset))]
    if video and not rows:
        return {'账号': '@' + handle, '说明': '该视频没有采集记录'}
    service = request.app.state.video_enrichment
    for row in rows:
        row['url'] = f"https://www.tiktok.com/@{handle}/video/{row['video']}"
        row['kalodata'] = service.video(aid,row['video'])
    profile = pick(account.get('profile'), 'nickname name handle followers following likes videos fans heart videoCount')
    run = pick(account.get('run'), 'state created updated item_count')
    with hub.db() as db:
        records = [dict(row) for row in db.execute("""WITH tracked AS (SELECT DISTINCT video FROM apify_snapshots WHERE account=?)
            SELECT (SELECT count(*) FROM tracked) AS tracked,
            (SELECT count(DISTINCT j.video) FROM tracked v JOIN video_enrichment_jobs j USING(video)
                WHERE j.account=? AND j.state='ready') AS kalodata,
            (SELECT count(DISTINCT c.video) FROM tracked v JOIN video_cases c USING(video)
                WHERE c.platform='TikTok' AND c.removed_at IS NULL
                AND EXISTS (SELECT 1 FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=c.id)) AS cases,
            (SELECT count(DISTINCT l.video) FROM tracked v JOIN script_library l USING(video)
                WHERE l.removed_at IS NULL AND coalesce(l.transcript_original,'')<>'') AS transcripts,
            (SELECT count(DISTINCT c.video) FROM tracked v JOIN video_cases c USING(video)
                WHERE c.platform='TikTok' AND c.removed_at IS NULL AND coalesce(json_extract(c.ai,'$.generated_at'),0)>0
                AND EXISTS (SELECT 1 FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=c.id)) AS analyzed_cases""", (aid,aid))]
        ids = [row['video'] for row in rows]
        scripts = {}
        if ids:
            marks = ','.join('?' for _ in ids)
            for script in db.execute(f"""SELECT video,transcript_original,transcript_en,transcript_zh,opening,expression,ending
                FROM script_library WHERE removed_at IS NULL AND video IN ({marks}) ORDER BY updated DESC""", ids):
                scripts.setdefault(script['video'], dict(script))
    data = []
    for row in rows:
        item = pick(row, 'video title url published collected views likes comments shares collects growth')
        kalo = row.get('kalodata') or {}
        item['Kalodata'] = {'状态': pick(kalo.get('status'), 'state period_start period_end updated'),
                           '数据': pick(kalo.get('data'), 'gmv units revenue sales sold currency orders product_id product_name shop_id shop_name video_id period_views fetched_at') }
        item['逐字稿'] = pick(scripts.get(row['video']), 'transcript_original transcript_en transcript_zh opening expression ending')
        if row.get('case_id'):
            try:
                case = read(routes, '/api/intelligence/cases/{cid}', request, cid=row['case_id'])
                item['内容复用'] = pick(case, 'id case_number fields review_status metrics tagging updated')
                if video:
                    item['商品关联'] = pick(case, 'commercial')
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        try:
            comments = read(routes, '/api/intelligence/comment-samples/{video}', request, video=row['video'])
            item['评论分析'] = pick(comments, 'state ai_state comments replies topics')
            if video:
                item['评论样本（前12条）'] = [pick(sample, 'cid text parent') for sample in comments['samples'][:12]]
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        data.append(item)
    return {'账号': '@'+handle, '账号档案': profile, '标签': account.get('labels'), '最近采集': run,
            '数据覆盖': records[0], '页': page, '每页': PAGE_SIZE, '总页数': (count + PAGE_SIZE - 1)//PAGE_SIZE,
            '视频': data}


def bounded(value, depth=0):
    if depth >= 7:
        return None
    if isinstance(value, str):
        return value if len(value) <= 480 else value[:480] + '…'
    if isinstance(value, dict):
        return {key: bounded(item, depth + 1) for key, item in list(value.items())[:30]}
    if isinstance(value, list):
        return [bounded(item, depth + 1) for item in value[:48]]
    return value


def lookup(app, hub, request, query, previous=''):
    routes = endpoints(app)
    handle = HANDLE.search(query)
    video = VIDEO.search(query)
    if not handle and re.search(r'竞对|监测账号', query):
        handle = re.search(r'(?<![a-zA-Z0-9_.])([a-zA-Z][a-zA-Z0-9_.]{2,39})(?![a-zA-Z0-9_.])', query)
    if not handle and re.search(r'第\s*\d+\s*页|这个账号|该账号|这条视频', query):
        handle = HANDLE.search(previous)
    page = page_number(query)
    quoted = re.search(r'[“「"]([^”」"]{1,120})[”」"]', query)
    search = quoted[1] if quoted else ''
    result = {}
    try:
        if handle and (not HOWTO.search(query) or DATA_INTENT.search(query)):
            result['竞对账号'] = account_query(routes, hub, request, handle[1].rstrip('.'), page, video[1] if video else '', search)
        elif re.search(r'竞对账号|监测账号', query) and DATA_INTENT.search(query) and not HOWTO.search(query):
            rows = read(routes, '/api/intelligence/apify/accounts', request)
            result['竞对账号'] = {'总数': len(rows), '页': page,
                                   '记录': [pick(row, 'handle selected last_success labels')
                                          for row in rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE]]}
        elif video and DATA_INTENT.search(query):
            result['视频评论'] = pick(read(routes, '/api/intelligence/comment-samples/{video}', request, video=video[1]),
                                    'video url comments replies ai_state state topics')
        elif DATA_INTENT.search(query) and not HOWTO.search(query):
            for reader in [r for r in READERS if re.search(r.match, query, re.I)][:3]:
                try:
                    result[reader.label] = general(routes, request, reader, page, search)
                except HTTPException as exc:
                    result[reader.label] = {'说明': '当前账号没有权限' if exc.status_code in (401,403) else '该查询当前不可用'}
    except HTTPException as exc:
        result['查询状态'] = '当前账号没有权限' if exc.status_code in (401,403) else '未查到可见数据或该查询尚不可用'
    except Exception:
        LOGGER.exception('Assistant read-only lookup failed')
        result['查询状态'] = '读取中台数据失败，请稍后查询'
    return {label: fit(data) for label, data in result.items()}


def fit(data):
    result = bounded(data)
    if not isinstance(result, dict):
        return result
    for key in ('记录', '视频'):
        if key not in result:
            continue
        rows = result[key]
        # Keep IDs, links and metrics intact, paginate large analysis text separately.
        for row in rows:
            for detail in ('fields', 'tagging', '内容复用', '逐字稿', '评论分析', 'tag_profile'):
                if detail in row and len(json.dumps(row[detail], ensure_ascii=False)) > 1400:
                    if detail == '内容复用':
                        row[detail] = pick(row[detail], 'id case_number review_status')
                    else:
                        row[detail] = {'说明': '该项内容较长，请按单条视频或到原页面查阅'}
        if len(json.dumps(result, ensure_ascii=False)) > 22500:
            for row in rows:
                for detail in ('fields', 'tagging', '逐字稿', '商品关联', '评论样本（前12条）', 'tag_profile'):
                    row.pop(detail, None)
            result['明细说明'] = '本页优先显示基本数据，较长分析可到对应记录查看。'
    return result
