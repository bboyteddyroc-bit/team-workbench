"""Owner-scoped public video snapshots; durable remote runs, no submission retries."""
import json
import time
import uuid
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from apify_submit_diagnostics import SubmissionTrace
import task_feedback as feedback
from kalodata_integration import identifier

DEFAULT_OPTIONS={'mode':'seven','timezone':'America/New_York'}
# 单次抓取不设条数上限：按用户选择的日期区间取全部视频。
# MAX_ITEMS / MAX_CHARGE 只是防跑飞的熔断值，正常日期窗口远达不到。
MAX_ITEMS=5000
MAX_CHARGE=2.00
# 勾选账号合并成一次 Apify 任务：单次远程任务费用熔断 10 美元，不设账号数量上限。
GROUP_MAX_CHARGE=10.00
SCHEDULE_TZ=ZoneInfo('Asia/Shanghai')
def norm_times(value):
    """['08:00','17:00'] → 排好序的定时列表；只允许 1–4 个 HH:MM（中国时间）。"""
    if not isinstance(value,list) or not 1<=len(value)<=4:raise HTTPException(400,'请选择 1–4 个采集时间')
    cleaned=[]
    for item in value:
        if not isinstance(item,str) or len(item)!=5 or item[2]!=':':raise HTTPException(400,'时间格式应为 HH:MM')
        try:hh,mm=int(item[:2]),int(item[3:])
        except ValueError:raise HTTPException(400,'时间格式应为 HH:MM') from None
        if not(0<=hh<=23 and 0<=mm<=59):raise HTTPException(400,'时间格式应为 HH:MM')
        cleaned.append('%02d:%02d'%(hh,mm))
    return sorted(set(cleaned))
def next_slot(times, after=None):
    """下一个严格晚于 after 的定点时刻（Asia/Shanghai）。"""
    after=time.time() if after is None else after
    local=datetime.fromtimestamp(after,SCHEDULE_TZ)
    for day in (0,1,2):
        d=(local+timedelta(days=day)).date()
        for hhmm in sorted(times):
            hh,mm=hhmm.split(':')
            cand=datetime(d.year,d.month,d.day,int(hh),int(mm),tzinfo=SCHEDULE_TZ).timestamp()
            if cand>after:return cand
    raise ValueError('定时时间无效')
def options(value=None):
    v=dict(DEFAULT_OPTIONS);v.update(value or {})
    if v['mode'] not in ('today','seven','rolling','custom') or v['timezone'] not in ('America/New_York','Asia/Shanghai','UTC'):
        raise HTTPException(400,'日期或时区设置无效')
    if v['mode']=='custom':
        try:
            start=date.fromisoformat(v.get('start',''));end=date.fromisoformat(v.get('end',''))
            if start>end or (end-start).days>365:raise ValueError()
        except (ValueError,TypeError):raise HTTPException(400,'请选择有效起止日期，最多 366 天')
    # 旧记录里残留的 limit 字段在这里被丢弃：单次抓取一律按日期取全量。
    return {k:v[k] for k in ('mode','timezone','start','end') if k in v}
def window(v, now=None):
    try:
        tz=ZoneInfo(v['timezone'])
    except ZoneInfoNotFoundError:
        raise HTTPException(503,'服务器缺少 tzdata 时区数据，请修复项目依赖；未提交付费任务') from None
    today=(now or datetime.now(timezone.utc)).astimezone(tz).date()
    # rolling：昨天+今天。定时采集跑到点时才计算，用来兜住「今天」那档每天结尾几小时的盲区。
    start=date.fromisoformat(v['start']) if v['mode']=='custom' else today-timedelta(days={'seven':6,'rolling':1}.get(v['mode'],0))
    end=date.fromisoformat(v['end']) if v['mode']=='custom' else today
    return datetime.combine(start,datetime.min.time(),tz).timestamp(),datetime.combine(end+timedelta(days=1),datetime.min.time(),tz).timestamp()

def cover_url(item):
    """封面只记录 http(s) 地址，不下载、不代理由本机转发；取不到就留空，界面显示占位。"""
    if not isinstance(item,dict):return None
    meta=item.get('videoMeta') or {}
    covers=item.get('covers') if isinstance(item.get('covers'),dict) else {}
    for value in (meta.get('originalCoverUrl'),meta.get('coverUrl'),covers.get('default'),covers.get('dynamic')):
        if isinstance(value,str):
            value=value.strip()
            if value.startswith(('https://','http://')) and len(value)<=1000:return value
    return None

class Monitor:
    def __init__(self, hub, config):
        self.hub, self.config = hub, config
        with hub.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS apify_accounts(id TEXT PRIMARY KEY,owner TEXT NOT NULL,handle TEXT NOT NULL,interval_hours INTEGER DEFAULT 0,next_at REAL DEFAULT 0,UNIQUE(owner,handle));
            CREATE TABLE IF NOT EXISTS apify_runs(id TEXT PRIMARY KEY,account TEXT NOT NULL,state TEXT NOT NULL,remote_id TEXT,dataset TEXT,created REAL NOT NULL,updated REAL NOT NULL,error TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS apify_one_active ON apify_runs(account) WHERE state IN ('queued','submitting','running');
            CREATE TABLE IF NOT EXISTS apify_snapshots(run TEXT NOT NULL,account TEXT NOT NULL,video TEXT NOT NULL,published REAL,title TEXT,views INTEGER,likes INTEGER,comments INTEGER,shares INTEGER,collects INTEGER,cover TEXT,collected REAL NOT NULL,PRIMARY KEY(run,video));
            CREATE TABLE IF NOT EXISTS apify_profiles(account TEXT PRIMARY KEY,profile TEXT NOT NULL,collected REAL NOT NULL);
            ''')
            db.execute('BEGIN IMMEDIATE')
            for table, columns in {'apify_accounts':{'options':"TEXT NOT NULL DEFAULT '{}'",'times':'TEXT','deleted_at':'REAL'},'apify_runs':{'options':"TEXT NOT NULL DEFAULT '{}'",'start_at':'REAL','end_at':'REAL','warning':'TEXT','item_count':'INTEGER'},'apify_snapshots':{'cover':'TEXT','collects':'INTEGER'}}.items():
                existing={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
                for name,kind in columns.items():
                    if name not in existing:db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+kind)
            from auto_selection import init_schema as init_auto
            from group_runs import init_schema as init_group
            init_auto(db);init_group(db)

    def request(self, method, path, **kwargs):
        binding=kwargs.pop('_pool_run',None)
        trace=kwargs.pop('_submit_trace',None)
        observed=feedback.current()
        if trace is not None:
            trace.stage='select_key'
        pool=getattr(self.config,'pool',None)
        token = pool.token(binding,submit=method=='POST',budget=(kwargs.get('params') or {}).get('maxTotalChargeUsd',0)) if pool and binding else self.config.secret()
        if not token: raise ValueError('请先在数据接入保存 Apify 密钥')
        client_options={}
        if trace is not None:
            trace.stage='init_client'
            client_options['event_hooks']={'request':[trace.before_transport],'response':[trace.observe_response]}
        try:
            with httpx.Client(timeout=30,trust_env=True,**client_options) as client:
                if trace is not None:trace.stage='prepare_request'
                response=client.request(method,'https://api.apify.com/v2'+path,headers={'Authorization':'Bearer '+token},**kwargs)
            if observed:observed.http(response.status_code)
            if trace is not None:
                trace.observe_response(response)
                trace.stage='check_http_status'
            if response.status_code>=400:
                if pool and binding:
                    if trace is not None:trace.stage='update_key_status'
                    pool.mark(binding,response.status_code)
                    if trace is not None:trace.stage='check_http_status'
                raise ValueError({401:'Apify 密钥无效',403:'Apify 权限不足',402:'Apify 额度不足',429:'Apify 请求受限'}.get(response.status_code,'Apify 请求失败（HTTP '+str(response.status_code)+'）'))
            if trace is not None:trace.stage='decode_json'
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            if trace is not None:trace.capture_error(exc)
            if observed:observed.error_type(type(exc).__name__)
            raise ValueError('Apify 网络异常；提交结果可能不明确，请核对控制台' if method=='POST' else '读取 Apify 原任务或数据集失败；未重新提交采集') from None

    def submit_actor(self, trace, **kwargs):
        response = self.request('POST','/acts/clockworks~tiktok-scraper/runs',
                                _pool_run=trace.binding,_submit_trace=trace,**kwargs)
        trace.stage='validate_response'
        data = response['data']
        if not isinstance(data,dict):raise TypeError('Invalid Apify run response')
        trace.stage='validate_run_id'
        return data

    def queue(self, account, settings=None):
        if not (self.config.available() if hasattr(self.config,'available') else self.config.secret()): raise HTTPException(400,'请先配置 Apify 密钥')
        with self.hub.db() as db:
            saved=db.execute('SELECT options,interval_hours,times FROM apify_accounts WHERE id=?',(account,)).fetchone()
        settings=options(settings if settings is not None else json.loads(saved['options']))
        start,end=window(settings)
        now=time.time()
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM apify_accounts WHERE id=? AND deleted_at IS NULL',(account,)).fetchone():
                raise HTTPException(404,'账号不存在')
            old=db.execute("SELECT id FROM apify_runs WHERE account=? AND state IN ('queued','submitting','running')",(account,)).fetchone()
            if old:return old['id']
            rid=uuid.uuid4().hex
            db.execute("INSERT INTO apify_runs(id,account,state,created,updated,options,start_at,end_at) VALUES(?,?,'queued',?,?,?,?,?)",(rid,account,now,now,json.dumps(settings),start,end))
            slots=json.loads(saved['times']) if saved and saved['times'] else None
            # 定点模式下 next_at 取下一定点，普通模式下取「现在 + 间隔」。
            next_at=next_slot(slots,now) if slots else now+(saved['interval_hours'] if saved else 0)*3600
            db.execute('UPDATE apify_accounts SET next_at=? WHERE id=?',(next_at,account))
        return rid

    def recover(self):
        if hasattr(self,'enrichment'):
            self.enrichment.recover()
        with self.hub.db() as db:
            db.execute("UPDATE apify_accounts SET interval_hours=0,times=NULL WHERE id IN (SELECT account FROM apify_runs WHERE state='submitting')")
            db.execute("UPDATE apify_runs SET state='attention',error='提交期间重启，请核对 Apify 控制台；定时监测已暂停' WHERE state='submitting'")
        from group_runs import recover as group_recover
        with self.hub.db() as db:
            # 合并任务若停在 submitting，远程计费结果未知：只标待核对，绝不自动重提。
            group_recover(db)

    def enqueue_group(self, owner, accounts, settings, now=None, automatic=False):
        """把同一用户、同一采集窗口的勾选账号合并成一个 Apify 任务。"""
        from group_runs import enqueue
        settings=options(settings)
        start,end=window(settings, now)
        stamp=time.time() if now is None else now
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if automatic:
                from auto_selection import get_config, selected_accounts
                selected=set(selected_accounts(db,owner))
                if not get_config(db,owner)['collection_enabled']:
                    return None
                accounts=[a for a in accounts if a['id'] in selected]
                if not accounts:
                    return None
            busy=[r[0] for r in db.execute('''SELECT handle FROM apify_accounts WHERE id IN (SELECT m.account FROM grouped_run_members m
                JOIN grouped_runs b ON b.id=m.batch WHERE b.state IN ('queued','submitting','running') AND m.state IN ('queued','submitting','running'))''') if r[0] in {a['handle'] for a in accounts}]
            if busy:raise ValueError('这些账号已有未完成的合并采集：'+'、'.join('@'+h for h in busy))
            batch=enqueue(db,owner,[{'id':a['id'],'handle':a['handle']} for a in accounts],settings,start,end,stamp,automatic=automatic)
            for account in accounts:
                slots=json.loads(account['times']) if account.get('times') else None
                hours=account.get('interval_hours') or 0
                next_at=next_slot(slots,stamp) if slots else stamp+hours*3600 if hours else 0
                db.execute('UPDATE apify_accounts SET next_at=? WHERE id=?',(next_at,account['id']))
        return batch

    def group_tick(self):
        """推进合并任务：提交一次、按账号写入快照，绝不对未知结果重试。"""
        from apify_grouping import build_request, partition_results
        from group_runs import claim, submitted, finish
        with self.hub.db() as db:
            row=db.execute("SELECT * FROM grouped_runs WHERE state IN ('queued','running') ORDER BY updated,created LIMIT 1").fetchone()
            if not row:return False
            batch=dict(row)
            members=[dict(m) for m in db.execute("SELECT * FROM grouped_run_members WHERE batch=? AND state IN ('queued','submitting','running') ORDER BY handle",(batch['id'],))]
        if not members:return False
        if batch['state']=='queued':
            with self.hub.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT 1 FROM users WHERE id=? AND enabled=1',(batch['owner'],)).fetchone():
                    db.execute("UPDATE grouped_run_members SET state='cancelled' WHERE batch=? AND state='queued'",(batch['id'],))
                    db.execute("UPDATE grouped_runs SET state='cancelled',error='成员已停用，未提交远程采集',updated=? WHERE id=? AND state='queued'",(time.time(),batch['id']))
                    return True
                if not claim(db,batch['id']):return True
                # 与取消勾选使用同一写事务边界，避免 claim 前读取到过期成员。
                members=[dict(m) for m in db.execute("SELECT * FROM grouped_run_members WHERE batch=? AND state='submitting' ORDER BY handle",(batch['id'],))]
            try:
                with feedback.bound(self.hub,'apify_group',batch['id']), feedback.step('apify_submit','unknown'), SubmissionTrace(self.hub.directory,'group:'+batch['id']) as trace:
                    settings=json.loads(batch['options'])
                    zone=settings.get('timezone','UTC')
                    group=[{'owner':batch['owner'],'handle':m['handle'],'start_at':batch['start_at'],'end_at':batch['end_at'],'timezone':zone} for m in members]
                    request=build_request(group,max_items=MAX_ITEMS,max_charge=GROUP_MAX_CHARGE)
                    data=self.submit_actor(trace,params=request['params'],json=request['json'])
                    remote=data.get('id')
                    if not isinstance(remote,str) or not remote.strip():
                        raise ValueError('未取得 Apify 任务编号，请核对控制台')
                    trace.received_run_id()
                    with self.hub.db() as db:
                        db.execute('BEGIN IMMEDIATE')
                        submitted(db,batch['id'],remote)
                    trace.saved()
            except Exception as exc:
                message=exc.detail if isinstance(exc,HTTPException) else str(exc) if isinstance(exc,ValueError) else '合并任务提交响应异常'
                with self.hub.db() as db:
                    db.execute("UPDATE grouped_run_members SET state='attention' WHERE batch=? AND state IN ('submitting','queued')",(batch['id'],))
                    db.execute("UPDATE grouped_runs SET state='attention',error=?,updated=? WHERE id=? AND state IN ('queued','submitting')",(message+'；未自动重试，请核对 Apify 控制台',time.time(),batch['id']))
            return True
        try:
            with feedback.bound(self.hub,'apify_group',batch['id']), feedback.step('apify_poll') as attempt:
                data=self.request('GET','/actor-runs/'+str(batch['remote_id']),_pool_run='group:'+batch['id'])['data']
                status=data.get('status')
                if status in ('FAILED','ABORTED','TIMED-OUT'):attempt.mark('failed')
                elif status!='SUCCEEDED':attempt.mark('waiting')
            if status!='SUCCEEDED':
                if status in ('FAILED','ABORTED','TIMED-OUT'):
                    with self.hub.db() as db:
                        db.execute("UPDATE grouped_run_members SET state='attention' WHERE batch=? AND state='running'",(batch['id'],))
                        db.execute("UPDATE grouped_runs SET state='attention',error=?,updated=? WHERE id=? AND state='running'",('Apify 任务结束：'+str(status),time.time(),batch['id']))
                else:
                    with self.hub.db() as db:db.execute('UPDATE grouped_runs SET updated=? WHERE id=?',(time.time(),batch['id']))
                return True
            with feedback.bound(self.hub,'apify_group',batch['id']), feedback.step('apify_dataset'):
                items=self.request('GET','/datasets/'+data['defaultDatasetId']+'/items',_pool_run='group:'+batch['id'],params={'clean':'true','limit':MAX_ITEMS})
            hand=[m['handle'] for m in members]
            split=partition_results(hand,items if isinstance(items,list) else [])
            truncated=isinstance(items,list) and len(items)>=MAX_ITEMS
            outcomes={}
            children={}
            with self.hub.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for member in members:
                    child=uuid.uuid4().hex
                    children[member['account']]=child
                    db.execute("INSERT INTO apify_runs(id,account,state,created,updated,options,start_at,end_at,remote_id) VALUES(?,?,'running',?,?,?,?,?,?)",
                               (child,member['account'],time.time(),time.time(),batch['options'],batch['start_at'],batch['end_at'],batch['remote_id']))
                    db.execute('UPDATE grouped_run_members SET child_run=? WHERE batch=? AND account=?',(child,batch['id'],member['account']))
                    outcomes[member['account']]='ready'
                db.execute('COMMIT')
            for member in members:
                child=children[member['account']]
                rows=split['accounts'].get(str(member['handle']).strip().lstrip('@').lower(),[])
                try:
                    with feedback.bound(self.hub,'apify_run',child), feedback.step('apify_save'):
                        self.ingest({'id':child,'account':member['account'],'start_at':batch['start_at'],'end_at':batch['end_at'],'automatic':bool(batch['automatic'])},rows)
                except Exception:
                    logger.exception('合并采集单账号入库失败：%s',member['account'])
                    with self.hub.db() as db:
                        db.execute("UPDATE apify_runs SET state='attention',error=? WHERE id=?",('合并任务已返回，但该账号入库失败，请重试采集',child))
                    outcomes[member['account']]='attention'
                if truncated:
                    with self.hub.db() as db:
                        db.execute("UPDATE apify_runs SET warning=COALESCE(warning,'')||? WHERE id=?",('已触及单次 %d 条熔断，可能未采全。'%MAX_ITEMS,child))
            with self.hub.db() as db:
                db.execute('BEGIN IMMEDIATE')
                finish(db,batch['id'],outcomes,'；'.join(filter(None,[
                    '有 %d 条结果无法归属到任何勾选账号'%len(split['unassigned']) if split['unassigned'] else '',
                    '已触及 %d 条熔断，可能未采全'%MAX_ITEMS if truncated else ''])) or None)
        except Exception as exc:
            message=str(exc) if isinstance(exc,ValueError) else '合并任务读取异常'
            with self.hub.db() as db:
                db.execute("UPDATE grouped_run_members SET state='attention' WHERE batch=? AND state='running'",(batch['id'],))
                db.execute("UPDATE grouped_runs SET state='attention',error=?,updated=? WHERE id=? AND state='running'",(message,time.time(),batch['id']))
        return True

    def ingest(self, run, items):
        if not isinstance(items,list):raise ValueError('Apify 视频列表格式异常')
        with self.hub.db() as db:
            handle=db.execute('SELECT handle FROM apify_accounts WHERE id=?',(run['account'],)).fetchone()['handle']
        product_links=[]
        from product_intel import products,record
        parsed=[]
        profile=None
        def metric(value):
            return int(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and value>=0 else None
        for item in items:
            if not isinstance(item,dict):continue
            vid=str(item.get('id',''))
            author=str((item.get('authorMeta') or {}).get('name','')).lstrip('@').lower()
            if not vid.isdigit() or author!=handle:continue
            meta=item.get('authorMeta') or {}
            profile={k:meta[k] for k in ('id','name','nickName','fans','following','heart','video','verified','signature','avatar') if k in meta and isinstance(meta[k],(str,int,float,bool))}
            published=item.get('createTime')
            if not isinstance(published,(int,float)):
                try:published=datetime.fromisoformat(item['createTimeISO'].replace('Z','+00:00')).timestamp()
                except (KeyError,ValueError,TypeError):published=None
            if run.get('start_at') is not None and (published is None or not run['start_at']<=published<run['end_at']):continue
            product_links.extend((vid,p) for p in products(item))
            parsed.append((run['id'],run['account'],vid,published,str(item.get('text') or '')[:10000],*[metric(item.get(k)) for k in ('playCount','diggCount','commentCount','shareCount','collectCount')],cover_url(item),time.time()))
        warning=('已触及单次熔断上限（%d 条），可能未采全。' % MAX_ITEMS if len(items)>=MAX_ITEMS else '')+('未取得范围内可核对的视频，不能据此认定发片为零。' if not parsed else '')
        with self.hub.db() as db:
            if profile:
                db.execute('INSERT OR REPLACE INTO apify_profiles VALUES(?,?,?)',(run['account'],json.dumps(profile,ensure_ascii=False),time.time()))
            from product_intel import enqueue
            linked={vid for vid,p in product_links if p.get('product_id') or p.get('productId')}
            for item in parsed:
                if item[2] not in linked:enqueue(db,'video',item[2])
            for vid,product in product_links:
                record(db,vid,handle,product,'Apify')
            db.executemany('INSERT OR IGNORE INTO apify_snapshots(run,account,video,published,title,views,likes,comments,shares,collects,cover,collected) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',parsed)
            db.execute("UPDATE apify_runs SET state='ready',updated=?,error=NULL,warning=?,item_count=? WHERE id=?",(time.time(),warning,len(parsed),run['id']))

        from apify_cover_cache import warm
        for record in parsed:
            if record[-2]:
                warm(Path(self.hub.directory)/'apify-covers',record[2],record[-2])

    def automation_tick(self):
        """自动采集开启时，把到点且被勾选的账号按同一窗口合并成一次任务。"""
        from auto_selection import get_config, selected_accounts
        with self.hub.db() as db:
            owners=[r[0] for r in db.execute('SELECT owner FROM auto_collection_config WHERE collection_enabled=1')]
        for owner in owners:
            with self.hub.db() as db:
                if not get_config(db,owner)['collection_enabled']:continue
                picked=set(selected_accounts(db,owner))
                if not picked:continue
                due=[dict(r) for r in db.execute('''SELECT a.id,a.handle,a.options,a.interval_hours,a.times FROM apify_accounts a JOIN users u ON u.id=a.owner
                  WHERE a.owner=? AND a.next_at>0 AND a.next_at<=? AND u.enabled=1''',(owner,time.time()))]
            groups={}
            for row in due:
                if row['id'] in picked:groups.setdefault(row['options'],[]).append(row)
            for raw,members in groups.items():
                try:
                    self.enqueue_group(owner,members,json.loads(raw or '{}'),automatic=True)
                except Exception:
                    logger.exception('自动合并采集排队失败：%s',owner)

    def tick(self):
        try:
            self.automation_tick()
        except Exception:
            logger.exception('自动采集检查失败')
        # 合并任务优先推进；一次只跑一个远程任务，避免并发超额。
        if self.group_tick():return
        with self.hub.db() as db:
            # 定时任务只由 automation_tick 按已确认的全局开关和勾选名单创建。
            # 不再回退到旧的逐账号调度，否则关闭全局开关后仍可能产生付费请求。
            due=[]
        for a in due:
            try:
                self.queue(a['id'])
            except Exception as exc:
                message = exc.detail if isinstance(exc,HTTPException) else '定时采集排队失败，请检查配置'
                with self.hub.db() as db:
                    db.execute('UPDATE apify_accounts SET interval_hours=0,times=NULL WHERE id=?',(a['id'],))
                    db.execute("INSERT INTO apify_runs(id,account,state,created,updated,error) VALUES(?,?,'attention',?,?,?)",(uuid.uuid4().hex,a['id'],time.time(),time.time(),message))
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""UPDATE apify_runs SET state='cancelled',updated=? WHERE state='queued' AND id IN (
              SELECT r.run FROM script_rechecks r JOIN apify_accounts a ON a.id=r.account
              LEFT JOIN users u ON u.id=a.owner LEFT JOIN script_auto_config c ON c.owner=a.owner
              LEFT JOIN auto_collection_selection s ON s.owner=a.owner AND s.account=a.id
              WHERE a.deleted_at IS NOT NULL OR COALESCE(u.enabled,0)<>1 OR COALESCE(c.enabled,0)<>1
                OR COALESCE(c.recheck,0)<>1 OR COALESCE(s.selected,0)<>1)""",(time.time(),))
            run=db.execute("SELECT r.*,a.handle FROM apify_runs r JOIN apify_accounts a ON a.id=r.account WHERE r.state IN ('queued','running') ORDER BY r.updated LIMIT 1").fetchone()
            if not run:return
            run=dict(run)
            if run['state']=='queued':
                if not db.execute('SELECT 1 FROM apify_accounts a JOIN users u ON u.id=a.owner WHERE a.id=? AND u.enabled=1 AND a.deleted_at IS NULL',(run['account'],)).fetchone():
                    db.execute("UPDATE apify_runs SET state='cancelled',error='成员已停用，未提交远程采集' WHERE id=?",(run['id'],))
                    return
                db.execute("UPDATE apify_runs SET state='submitting',updated=? WHERE id=?",(time.time(),run['id']))
        try:
            if run['state']=='queued':
                with feedback.bound(self.hub,'apify_run',run['id']), feedback.step('apify_submit','unknown'), SubmissionTrace(self.hub.directory,'run:'+run['id']) as trace:
                    # 日期区间内的视频全部取回，MAX_ITEMS/MAX_CHARGE 仅作熔断。
                    payload={'profiles':[run['handle']],'resultsPerPage':1000000,'profileScrapeSections':['videos'],'profileSorting':'latest','shouldDownloadVideos':False,'shouldDownloadCovers':False}
                    if run.get('start_at') is not None:
                        # 日期按采集配置的时区换算，避免把起点/终点各多带一天。
                        try:tz=ZoneInfo(options(json.loads(run.get('options') or '{}'))['timezone'])
                        except (ZoneInfoNotFoundError,KeyError,HTTPException):tz=timezone.utc
                        payload.update(oldestPostDateUnified=datetime.fromtimestamp(run['start_at'],tz).strftime('%Y-%m-%d'),newestPostDate=datetime.fromtimestamp(run['end_at']-1,tz).strftime('%Y-%m-%d'))
                    data=self.submit_actor(trace,params={'timeout':300,'maxItems':MAX_ITEMS,'maxTotalChargeUsd':MAX_CHARGE},json=payload)
                    remote=data.get('id')
                    if not isinstance(remote,str) or not remote.strip():
                        raise ValueError('未取得 Apify 任务编号，请核对控制台')
                    trace.received_run_id()
                    with self.hub.db() as db:
                        changed=db.execute("UPDATE apify_runs SET state='running',remote_id=?,updated=? WHERE id=?",(remote,time.time(),run['id']))
                        if changed.rowcount!=1:raise RuntimeError('Apify run row not updated')
                    trace.saved()
            else:
                with feedback.bound(self.hub,'apify_run',run['id']):
                    with feedback.step('apify_poll') as attempt:
                        data=self.request('GET','/actor-runs/'+run['remote_id'],_pool_run='run:'+run['id'])['data']
                        status=data['status']
                        if status in ('FAILED','ABORTED','TIMED-OUT'):
                            attempt.mark('failed')
                            raise ValueError('Apify 任务结束：'+status)
                        if status!='SUCCEEDED':attempt.mark('waiting')
                    if status=='SUCCEEDED':
                        with feedback.step('apify_dataset'):
                            items=self.request('GET','/datasets/'+data['defaultDatasetId']+'/items',_pool_run='run:'+run['id'],params={'clean':'true','limit':MAX_ITEMS})
                        with feedback.step('apify_save'):
                            self.ingest(run,items)
                    else:
                        with self.hub.db() as db:db.execute('UPDATE apify_runs SET updated=? WHERE id=?',(time.time(),run['id']))
        except Exception as exc:
            message=str(exc) if isinstance(exc,ValueError) else '采集响应异常，请核对 Apify 控制台'
            with self.hub.db() as db:
                db.execute("UPDATE apify_runs SET state='attention',error=?,updated=? WHERE id=?",(message,time.time(),run['id']))
                db.execute('UPDATE apify_accounts SET interval_hours=0,times=NULL WHERE id=?',(run['account'],))

    def loop(self):
        while not self.hub.stop.is_set():
            try:self.tick()
            except Exception as exc:
                logger.error('Apify worker failure (%s)',type(exc).__name__)
            self.hub.stop.wait(10)

def attach(app,hub,user,body):
    service=Monitor(hub,app.state.apify_config)
    app.state.apify_monitor=service
    from auto_selection import init_schema, select_account, selected_accounts
    with hub.db() as db:
        init_schema(db)
    from video_enrichment import attach as attach_enrichment
    service.enrichment=attach_enrichment(app,hub,user,body)
    def owned(aid,uid):
        with hub.db() as db:r=db.execute('SELECT * FROM apify_accounts WHERE id=? AND owner=? AND deleted_at IS NULL',(aid,uid)).fetchone()
        if not r:raise HTTPException(404,'账号不存在')
        return r

    def visible(aid):
        # 此部署的启用用户属于同一团队；删除的账号不再对团队可见。
        with hub.db() as db:r=db.execute('SELECT a.* FROM apify_accounts a JOIN users u ON u.id=a.owner WHERE a.id=? AND a.deleted_at IS NULL AND u.enabled=1',(aid,)).fetchone()
        if not r:raise HTTPException(404,'账号不存在')
        return r

    @app.get('/api/intelligence/apify/selection')
    def get_selection(request:Request):
        u=user(request)
        with hub.db() as db:
            return {'accounts':selected_accounts(db,u['id'])}

    @app.post('/api/intelligence/apify/accounts/{aid}/selection')
    async def update_selection(aid:str,request:Request):
        u=user(request);owned(aid,u['id']);data=await body(request)
        try:
            with hub.db() as db:
                select_account(db,u['id'],aid,data.get('selected'))
                if data.get('selected') is True:
                    db.execute('INSERT OR IGNORE INTO video_enrichment_config(account,updated) VALUES(?,?)',(aid,time.time()))
                if data.get('selected') is not True:
                    # 取消勾选只撤掉还没提交的合并成员，已在跑的任务不受影响。
                    from group_runs import deselect_pending
                    deselect_pending(db,u['id'],aid)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        return {'selected':data['selected']}

    @app.get('/api/intelligence/apify/members')
    def monitoring_members(request:Request):
        user(request)
        with hub.db() as db:
            return [row['username'] for row in db.execute('SELECT username FROM users WHERE enabled=1 ORDER BY username')]

    @app.get('/api/intelligence/apify/accounts')
    def accounts(request:Request):
        u=user(request)
        with hub.db() as db:
            result=[]
            rows=db.execute('''SELECT a.*,u.username AS owner_name,COALESCE(s.selected,0) AS selected,
              COALESCE(g.enrichment_enabled,0) AS owner_enrichment_enabled
              FROM apify_accounts a JOIN users u ON u.id=a.owner AND u.enabled=1
              LEFT JOIN auto_collection_selection s ON s.owner=a.owner AND s.account=a.id
              LEFT JOIN auto_collection_config g ON g.owner=a.owner
              WHERE a.deleted_at IS NULL ORDER BY a.handle,u.username''').fetchall()
            for row in rows:
                a=dict(row);a['is_owner']=a.pop('owner')==u['id']
                a['selected']=bool(a['selected'])
                a['owner_enrichment_enabled']=bool(a['owner_enrichment_enabled'])
                a['times']=json.loads(a['times']) if a.get('times') else None
                run=db.execute('SELECT id,state,created,updated,error,warning,item_count,start_at,end_at,options FROM apify_runs WHERE account=? ORDER BY created DESC LIMIT 1',(a['id'],)).fetchone()
                a['run']=dict(run) if run else None
                a['last_success']=db.execute("SELECT MAX(updated) FROM apify_runs WHERE account=? AND state='ready'",(a['id'],)).fetchone()[0]
                a['new_count']=db.execute('''SELECT COUNT(DISTINCT s.video) FROM apify_snapshots s WHERE s.account=? AND s.run=(SELECT id FROM apify_runs WHERE account=? AND state='ready' ORDER BY updated DESC LIMIT 1) AND NOT EXISTS(SELECT 1 FROM apify_snapshots prior WHERE prior.account=s.account AND prior.video=s.video AND prior.collected<s.collected)''',(a['id'],a['id'])).fetchone()[0]
                profile=db.execute('SELECT profile,collected FROM apify_profiles WHERE account=?',(a['id'],)).fetchone()
                a['profile']=json.loads(profile['profile']) if profile else None
                a['profile_collected']=profile['collected'] if profile else None
                a['enrichment']=service.enrichment.status(a['id'])
                result.append(a)
        return result

    @app.post('/api/intelligence/apify/accounts')
    async def add(request:Request):
        u=user(request);data=await body(request)
        try:handle=identifier('creator',data.get('handle',''))
        except ValueError as exc:raise HTTPException(400,str(exc))
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT id,deleted_at FROM apify_accounts WHERE owner=? AND handle=?',(u['id'],handle)).fetchone()
            if previous:
                restored=previous['deleted_at'] is not None
                if restored:db.execute('UPDATE apify_accounts SET deleted_at=NULL,next_at=0 WHERE id=?',(previous['id'],))
                return {'id':previous['id'],'handle':handle,'restored':restored}
            aid=uuid.uuid4().hex
            db.execute('INSERT INTO apify_accounts(id,owner,handle) VALUES(?,?,?)',(aid,u['id'],handle))
            return {'id':aid,'handle':handle,'restored':False}

    @app.post('/api/intelligence/apify/accounts/{aid}/delete')
    async def delete(aid:str,request:Request):
        u=user(request);owned(aid,u['id'])
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM apify_accounts WHERE id=? AND owner=? AND deleted_at IS NULL',(aid,u['id'])).fetchone():
                raise HTTPException(404,'账号不存在')
            select_account(db,u['id'],aid,False)
            from group_runs import deselect_pending
            deselect_pending(db,u['id'],aid)
            db.execute("UPDATE apify_runs SET state='cancelled',updated=? WHERE account=? AND state='queued'",(time.time(),aid))
            db.execute('UPDATE apify_accounts SET deleted_at=?,next_at=0 WHERE id=?',(time.time(),aid))
        return {'ok':True}

    @app.post('/api/intelligence/apify/accounts/{aid}/collect')
    async def collect(aid:str,request:Request):
        u=user(request);owned(aid,u['id']);data=await body(request)
        if data.get('allow_paid') is not True:raise HTTPException(400,'请确认采集消耗 Apify 额度')
        return {'id':service.queue(aid,options(data.get('options')))}

    @app.post('/api/intelligence/apify/accounts/{aid}/schedule')
    async def schedule(aid:str,request:Request):
        u=user(request);owned(aid,u['id']);data=await body(request)
        raw_times=data.get('times')
        hours=data.get('hours',0)
        settings=options(data.get('options'))
        # 定时开着时采集范围由服务端定：固定「昨天+今天」滚动，避免把 7 天窗口每 12 小时重买一遍，
        # 也避免「今天」在美东时区每天漏掉最后 4–5 小时。关掉定时再交还给用户选。
        if raw_times is not None or bool(hours):
            settings=dict(settings,mode='rolling')
        elif settings.get('mode')=='rolling':
            settings=dict(settings,mode='today')
        if raw_times is not None:
            slots=norm_times(raw_times);hours=0
            if data.get('allow_paid') is not True:raise HTTPException(400,'请确认定时采集费用')
            if not service.config.available():raise HTTPException(400,'请先配置 Apify 密钥')
            next_at=next_slot(slots)
            with hub.db() as db:db.execute('UPDATE apify_accounts SET interval_hours=0,times=?,next_at=?,options=? WHERE id=?',(json.dumps(slots),next_at,json.dumps(settings),aid))
            return {'ok':True,'times':slots,'next_at':next_at}
        if type(hours) is not int or hours not in (0,6,12,24):raise HTTPException(400,'请选择支持的频率')
        if hours and data.get('allow_paid') is not True:raise HTTPException(400,'请确认定时采集费用')
        if hours and not service.config.available():raise HTTPException(400,'请先配置 Apify 密钥')
        next_at=time.time()+hours*3600 if hours else 0
        with hub.db() as db:db.execute('UPDATE apify_accounts SET interval_hours=?,times=NULL,next_at=?,options=? WHERE id=?',(hours,next_at,json.dumps(settings),aid))
        return {'ok':True,'next_at':next_at}

    @app.post('/api/intelligence/apify/batch')
    async def batch(request:Request):
        """勾选账号合并成一次 Apify 任务：不设账号数量上限，单次费用熔断 10 美元。"""
        u=user(request);data=await body(request);ids=data.get('accounts')
        if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids):raise HTTPException(400,'请先勾选要采集的账号')
        ids=list(dict.fromkeys(ids));settings=options(data.get('options'))
        rows=[dict(owned(aid,u['id'])) for aid in ids]
        if data.get('allow_paid') is not True:raise HTTPException(400,'请确认采集费用')
        if not service.config.available():raise HTTPException(400,'请先配置 Apify 密钥')
        try:
            batch_id=service.enqueue_group(u['id'],rows,settings)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        return {'batch':batch_id,'accounts':len(rows),'max_charge':GROUP_MAX_CHARGE,'max_items':MAX_ITEMS}

    @app.get('/api/intelligence/apify/automation')
    def get_automation(request:Request):
        u=user(request)
        from auto_selection import get_config, selected_accounts
        with hub.db() as db:
            config=get_config(db,u['id'])
            return {'collection':config['collection_enabled'],'enrichment':config['enrichment_enabled'],'selected':len(selected_accounts(db,u['id']))}

    @app.post('/api/intelligence/apify/automation')
    async def set_automation(request:Request):
        u=user(request);data=await body(request)
        from auto_selection import set_config, get_config
        try:
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE')
                current=get_config(db,u['id'])
                collection=data.get('collection') if type(data.get('collection')) is bool else current['collection_enabled']
                enrichment=data.get('enrichment') if type(data.get('enrichment')) is bool else current['enrichment_enabled']
                config=set_config(db,u['id'],collection,enrichment,
                    confirmed=data.get('confirmed') is True)
                if not collection:
                    db.execute("UPDATE grouped_run_members SET state='cancelled' WHERE state='queued' AND batch IN (SELECT id FROM grouped_runs WHERE owner=? AND automatic=1 AND state='queued')",(u['id'],))
                    db.execute("UPDATE grouped_runs SET state='cancelled',updated=? WHERE owner=? AND automatic=1 AND state='queued'",(time.time(),u['id']))
                config=get_config(db,u['id'])
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        return {'collection':config['collection_enabled'],'enrichment':config['enrichment_enabled']}

    @app.get('/api/intelligence/apify/accounts/{aid}/videos')
    def videos(aid:str,request:Request):
        user(request);a=visible(aid)
        with hub.db() as db:
            rows=db.execute('''SELECT s.* FROM apify_snapshots s WHERE account=? AND collected=(SELECT MAX(x.collected) FROM apify_snapshots x WHERE x.account=s.account AND x.video=s.video) ORDER BY published DESC LIMIT 500''',(aid,)).fetchall()
            result=[]
            cases={row["video"]:row["id"] for row in db.execute("SELECT video,id FROM video_cases WHERE platform='TikTok' AND video IN (SELECT video FROM apify_snapshots WHERE account=?)",(aid,))}
            for row in rows:
                r=dict(row);r["case_id"]=cases.get(r["video"])
                previous=db.execute('SELECT views,collected FROM apify_snapshots WHERE account=? AND video=? AND collected<? ORDER BY collected DESC LIMIT 1',(aid,r['video'],r['collected'])).fetchone()
                r['growth']=r['views']-previous['views'] if previous and r['views'] is not None and previous['views'] is not None else None
                r['previous_at']=previous['collected'] if previous else None
                r['url']='https://www.tiktok.com/@'+a['handle']+'/video/'+r['video']
                r['kalodata']=service.enrichment.video(aid,r['video'])
                result.append(r)
        return result

    @app.get('/api/intelligence/apify/accounts/{aid}/cover/{video}')
    def cover(aid:str,video:str,request:Request):
        """缩略图代理：首次按快照里的签名地址取回并落盘，之后直接发缓存。

        Apify 返回的封面地址带签名、会过期；本地留一份，历史视频的缩略图就不会某天突然消失。
        """
        user(request);visible(aid)
        if not video.isdigit():raise HTTPException(404,'没有封面')
        directory=Path(hub.directory)/'apify-covers'
        directory.mkdir(exist_ok=True)
        from apify_cover_cache import existing, store, MIME
        path=existing(directory,video)
        if path is None:
            with hub.db() as db:
                row=db.execute('SELECT cover FROM apify_snapshots WHERE account=? AND video=? AND cover IS NOT NULL ORDER BY collected DESC LIMIT 1',(aid,video)).fetchone()
            if not row:raise HTTPException(404,'没有封面')
            try:
                path=store(directory,video,row['cover'])
            except (ValueError,OSError):
                raise HTTPException(404,'封面暂不可用，请稍后刷新') from None
        return FileResponse(path,media_type=MIME[path.suffix],headers={'Cache-Control':'private, max-age=604800'})
