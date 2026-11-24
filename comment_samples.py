"""Independent, opt-in TikTok public-text sampler. No Apify or case state is mutated."""
import json
import re
import time
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException, Request
from a6_provider import MODEL
from comment_sample_io import RemoteError, analyse, page
from comment_research import SIGNALS, read_pack, row_counts
import task_feedback as feedback

PREFIX='/api/intelligence/comment-samples'
MAX_TOP=60
MAX_REPLIES=20
MAX_BACKFILL=500
CN=timezone(timedelta(hours=8))
# Only team-visible Content Reuse cases. Legacy monitor rows remain stored, but
# they cannot be read, collected or analysed unless the video belongs to the case library.
CASE_VISIBLE="c.platform='TikTok' AND c.removed_at IS NULL AND EXISTS (SELECT 1 FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=c.id)"
IN_CASE_LIBRARY=f'EXISTS(SELECT 1 FROM video_cases c WHERE c.video=j.video AND {CASE_VISIBLE})'


def public_url(handle,video):
    if re.fullmatch(r'[A-Za-z0-9._]{1,64}',str(handle)) and re.fullmatch(r'[0-9]{5,25}',str(video)):
        return f'https://www.tiktok.com/@{handle}/video/{video}'
    return None


def enqueue(db,video,handle,origin,now=None,enabled=None):
    url=public_url(handle,video)
    if not url or origin not in ('case','backfill'):return False
    if not db.execute(f'SELECT 1 FROM video_cases c WHERE c.video=? AND {CASE_VISIBLE} LIMIT 1',(video,)).fetchone():return False
    if enabled is None:enabled=db.execute('SELECT collect FROM comment_sample_config WHERE id=1').fetchone()[0]
    if not enabled:return False
    now=now if now is not None else time.time()
    return bool(db.execute("INSERT OR IGNORE INTO comment_sample_jobs(video,url,origin,state,created,updated) VALUES(?,?,?,'queued',?,?)",(video,url,origin,now,now)).rowcount)


class SampleService:
    def __init__(self,hub,clock=time.time):
        self.hub=hub;self.clock=clock
        with hub.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS comment_sample_config(id INTEGER PRIMARY KEY CHECK(id=1),secret BLOB,
              collect INTEGER NOT NULL DEFAULT 0, ai INTEGER NOT NULL DEFAULT 0, daily INTEGER NOT NULL DEFAULT 20,
              ai_daily INTEGER NOT NULL DEFAULT 5, pages INTEGER NOT NULL DEFAULT 2, replies INTEGER NOT NULL DEFAULT 2,
              collect_error TEXT NOT NULL DEFAULT '',ai_error TEXT NOT NULL DEFAULT '',updated REAL,
              backfill_until REAL NOT NULL DEFAULT 0);
            INSERT OR IGNORE INTO comment_sample_config(id) VALUES(1);
            CREATE TABLE IF NOT EXISTS comment_sample_scope(id INTEGER PRIMARY KEY CHECK(id=1),since REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS comment_sample_jobs(video TEXT PRIMARY KEY,url TEXT NOT NULL,origin TEXT NOT NULL,
              state TEXT NOT NULL,ai_state TEXT NOT NULL DEFAULT 'pending',created REAL NOT NULL,updated REAL NOT NULL,
              started REAL, requests INTEGER NOT NULL DEFAULT 0, pages INTEGER NOT NULL DEFAULT 0,
              reply_pages INTEGER NOT NULL DEFAULT 0, stop_reason TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',
              ai_error TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',topics TEXT NOT NULL DEFAULT '[]',finished REAL);
            CREATE INDEX IF NOT EXISTS comment_sample_jobs_queue ON comment_sample_jobs(state,created);
            CREATE INDEX IF NOT EXISTS comment_sample_ai_queue ON comment_sample_jobs(ai_state,updated);
            CREATE TABLE IF NOT EXISTS comment_sample_text(video TEXT NOT NULL,cid TEXT NOT NULL,parent TEXT NOT NULL,
              text TEXT NOT NULL,published INTEGER,observed REAL NOT NULL,ordinal INTEGER NOT NULL,
              PRIMARY KEY(video,cid));
            CREATE TABLE IF NOT EXISTS comment_sample_usage(day TEXT PRIMARY KEY,requests INTEGER NOT NULL DEFAULT 0,
              ai_calls INTEGER NOT NULL DEFAULT 0,reported_credits INTEGER NOT NULL DEFAULT 0,unreported INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS comment_sample_snapshot_lookup ON apify_snapshots(video,account);
            CREATE TABLE IF NOT EXISTS comment_sample_research(video TEXT PRIMARY KEY,state TEXT NOT NULL,
              payload TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT '',updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS comment_sample_research_queue ON comment_sample_research(state,updated);
            ''')

    def day(self,now=None):return datetime.fromtimestamp(self.clock() if now is None else now,CN).date().isoformat()

    def recover(self):
        with self.hub.db() as db:
            if db.execute("UPDATE comment_sample_jobs SET state='attention',error='服务中断，采集结果或计费未知；未自动重试' WHERE state='running'").rowcount:
                db.execute("UPDATE comment_sample_config SET collect_error='上一次采集结果未知，确认供应商记录后再恢复队列' WHERE id=1")
            a=db.execute("UPDATE comment_sample_jobs SET ai_state='attention',ai_error='服务中断，AI 请求结果未知；未自动重试' WHERE ai_state='running'").rowcount
            b=db.execute("UPDATE comment_sample_research SET state='attention',error='服务中断，补充标注结果未知；未自动重试' WHERE state='running'").rowcount
            if a or b:db.execute("UPDATE comment_sample_config SET ai_error='上一次 AI 请求结果未知，核对后再恢复队列' WHERE id=1")

    def status(self,admin):
        with self.hub.db() as db:
            cfg=db.execute('SELECT (secret IS NOT NULL) configured,collect,ai,daily,ai_daily,pages,replies,collect_error,ai_error,updated FROM comment_sample_config').fetchone()
            use=db.execute('SELECT requests,ai_calls,reported_credits,unreported FROM comment_sample_usage WHERE day=?',(self.day(),)).fetchone()
            counts={r[0]:r[1] for r in db.execute(f'SELECT state,count(*) FROM comment_sample_jobs j WHERE {IN_CASE_LIBRARY} GROUP BY state')}
            ai_counts={r[0]:r[1] for r in db.execute(f"SELECT ai_state,count(*) FROM comment_sample_jobs j WHERE state IN ('ready','partial') AND {IN_CASE_LIBRARY} GROUP BY ai_state")}
            has_ai=bool(db.execute('SELECT 1 FROM a6_settings WHERE id=1').fetchone())
            remaining=bool(db.execute(f'SELECT 1 FROM video_cases c WHERE {CASE_VISIBLE} AND NOT EXISTS(SELECT 1 FROM comment_sample_jobs j WHERE j.video=c.video) LIMIT 1').fetchone())
        return dict(cfg)|{'admin':admin,'ai_configured':has_ai,'usage':dict(use) if use else {},'counts':counts,'ai_counts':ai_counts,'backfill_remaining':remaining}

    def backfill(self,db,now):
        cutoff=db.execute('SELECT backfill_until FROM comment_sample_config WHERE id=1').fetchone()[0]
        if not cutoff:return 0
        rows=db.execute(f'''SELECT c.video,c.handle FROM video_cases c WHERE {CASE_VISIBLE} AND c.created<=?
          AND NOT EXISTS(SELECT 1 FROM comment_sample_jobs j WHERE j.video=c.video) ORDER BY c.created DESC,c.id LIMIT ?''',(cutoff,MAX_BACKFILL)).fetchall()
        if len(rows)<MAX_BACKFILL:db.execute('UPDATE comment_sample_config SET backfill_until=0 WHERE id=1')
        return sum(enqueue(db,r['video'],r['handle'],'backfill',now,True) for r in rows)

    def budget(self,db,kind,now):
        day=self.day(now);db.execute('INSERT OR IGNORE INTO comment_sample_usage(day) VALUES(?)',(day,))
        col,limit=('requests','daily') if kind=='collect' else ('ai_calls','ai_daily')
        ok=db.execute(f'UPDATE comment_sample_usage SET {col}={col}+1 WHERE day=? AND ((SELECT {limit} FROM comment_sample_config WHERE id=1)=0 OR {col}<(SELECT {limit} FROM comment_sample_config WHERE id=1))',(day,)).rowcount
        return day if ok else None

    def claim(self,kind):
        now=self.clock()
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            cfg=dict(db.execute('SELECT * FROM comment_sample_config WHERE id=1').fetchone())
            if not cfg[kind] or cfg[kind+'_error']:return None
            eligible_scope='j.created >= COALESCE((SELECT since FROM comment_sample_scope WHERE id=1),0)'
            if kind=='collect':
                use=db.execute('SELECT requests FROM comment_sample_usage WHERE day=?',(self.day(now),)).fetchone()
                if not cfg['secret'] or (cfg['daily'] and (use[0] if use else 0)+cfg['pages']+cfg['replies']>cfg['daily']):return None
                if not db.execute(f"SELECT 1 FROM comment_sample_jobs j WHERE origin='backfill' AND state='queued' AND {IN_CASE_LIBRARY} LIMIT 1").fetchone():
                    self.backfill(db,now)
                r=db.execute(f"SELECT j.* FROM comment_sample_jobs j WHERE state='queued' AND {eligible_scope} AND {IN_CASE_LIBRARY} ORDER BY CASE origin WHEN 'backfill' THEN 0 ELSE 1 END,created,video LIMIT 1").fetchone()
            else:
                setting=db.execute('SELECT secret FROM a6_settings WHERE id=1').fetchone()
                if not setting:return None
                cfg['secret']=setting[0]
                r=db.execute(f"SELECT j.* FROM comment_sample_jobs j WHERE ai_state='pending' AND state IN ('ready','partial') AND {eligible_scope} AND {IN_CASE_LIBRARY} ORDER BY updated,video LIMIT 1").fetchone()
                cfg['supplement']=not r
                if not r:
                    r=db.execute(f"""SELECT j.* FROM comment_sample_research s JOIN comment_sample_jobs j USING(video)
                       WHERE s.state='queued' AND j.ai_state='ready' AND {eligible_scope} AND {IN_CASE_LIBRARY}
                       ORDER BY s.updated,j.video LIMIT 1""").fetchone()
            if not r:return None
            try:key=self.hub.cipher.decrypt(bytes(cfg.pop('secret'))).decode('ascii')
            except (InvalidToken,UnicodeError,TypeError,ValueError):
                db.execute(f'UPDATE comment_sample_config SET {kind}_error=? WHERE id=1',('密钥无法解密，请重新保存并启用',));return None
            if kind=='ai':
                if not self.budget(db,'ai',now):return None
                if cfg['supplement']:db.execute("UPDATE comment_sample_research SET state='running',updated=? WHERE video=?",(now,r['video']))
                else:db.execute("UPDATE comment_sample_jobs SET ai_state='running' WHERE video=?",(r['video'],))
            else:db.execute("UPDATE comment_sample_jobs SET state='running',started=COALESCE(started,?) WHERE video=?",(now,r['video']))
            return dict(r),cfg,key

    def claim_single(self,kind,video):
        """A separately authorized single-video run, independent of the bulk queue."""
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute(f'SELECT j.* FROM comment_sample_jobs j WHERE j.video=? AND {IN_CASE_LIBRARY}',(video,)).fetchone()
            if not row:return None
            now=self.clock()
            if kind=='collect':
                if row['state']!='queued' or row['requests']:return None
                secret=db.execute('SELECT secret FROM comment_sample_config WHERE id=1').fetchone()
            else:
                if row['state'] not in ('ready','partial') or row['ai_state']!='pending':return None
                if not db.execute('SELECT 1 FROM comment_sample_text WHERE video=? LIMIT 1',(video,)).fetchone():return None
                secret=db.execute('SELECT secret FROM a6_settings WHERE id=1').fetchone()
            if not secret or not secret[0]:return None
            key=self.hub.cipher.decrypt(bytes(secret[0])).decode('ascii')
            if kind=='collect':
                db.execute("UPDATE comment_sample_jobs SET state='running',started=COALESCE(started,?) WHERE video=?",(now,video))
            else:
                if not self.budget(db,'ai',now):return None
                db.execute("UPDATE comment_sample_jobs SET ai_state='running' WHERE video=?",(video,))
            return dict(row),{'single':video,'pages':1,'replies':0,'supplement':False},key

    def reserve(self,video,cfg):
        if self.hub.stop.is_set():return None
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            live=db.execute(f"SELECT 1 FROM comment_sample_jobs j WHERE video=? AND {IN_CASE_LIBRARY}",(video,)).fetchone()
            s=db.execute('SELECT collect,collect_error,updated FROM comment_sample_config').fetchone()
            if not live:return None
            if cfg.get('single')!=video and (not s[0] or s[1] or s[2]!=cfg['updated']):return None
            day=self.budget(db,'collect',self.clock())
            if day:
                db.execute('UPDATE comment_sample_usage SET unreported=unreported+1 WHERE day=?',(day,))
                db.execute('UPDATE comment_sample_jobs SET requests=requests+1 WHERE video=?',(video,))
            return day

    def save_page(self,video,raw,parent,day,credits,max_rows):
        now=self.clock()
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if credits is not None:db.execute('UPDATE comment_sample_usage SET reported_credits=reported_credits+?,unreported=unreported-1 WHERE day=?',(credits,day))
            col='reply_pages' if parent else 'pages'
            db.execute(f'UPDATE comment_sample_jobs SET {col}={col}+1,updated=? WHERE video=?',(now,video))
            count=db.execute('SELECT count(*) FROM comment_sample_text WHERE video=? AND (parent<>\'\')=?',(video,bool(parent))).fetchone()[0]
            threads=[]
            for r in raw:
                if not isinstance(r,dict) or str(r.get('aweme_id',video))!=video or r.get('no_show') is True:continue
                cid=str(r.get('cid',''));text=r.get('text')
                if not re.fullmatch(r'[0-9]{5,25}',cid) or not isinstance(text,str) or not text.strip():continue
                likes=r.get('digg_count')
                rank=-likes if type(likes) is int and 0<=likes<2**63 else 1
                published=r.get('create_time')
                n=db.execute('INSERT OR IGNORE INTO comment_sample_text VALUES(?,?,?,?,?,?,?)',(video,cid,parent or '',text.strip()[:420],published if type(published) is int and 0<published<2**32 else None,now,rank)).rowcount
                count+=n
                if not parent and n and type(r.get('reply_comment_total')) is int and r['reply_comment_total']>0:threads.append((rank,cid))
            db.execute("""DELETE FROM comment_sample_text WHERE video=? AND (parent<>'')=? AND cid NOT IN
                (SELECT cid FROM comment_sample_text WHERE video=? AND (parent<>'')=? ORDER BY ordinal,cid LIMIT ?)""",
                (video,bool(parent),video,bool(parent),max_rows))
            return min(count,max_rows),threads

    def fetch_page(self,client,key,row,day,cursor=None,parent=None):
        video=row['video']
        with feedback.bound(self.hub,'comment_collect',video):
            with feedback.step('reply_page' if parent else 'comment_page') as attempt:
                raw,next_cursor,credits=page(client,key,row['url'],cursor,parent=parent)
                attempt.credits(credits)
            with feedback.step('reply_save' if parent else 'comment_save'):
                count,new=self.save_page(video,raw,parent,day,credits,MAX_REPLIES if parent else MAX_TOP)
        return count,new,next_cursor

    def collect_one(self,client,*,only_video=None):
        claimed=self.claim_single('collect',only_video) if only_video else self.claim('collect')
        if not claimed:return False
        r,cfg,key=claimed;video=r['video'];threads=[];cursor=None;state='ready';error='';halt=False
        stop='按单条授权取一页主评论' if only_video else '按管理员设定抽样，非全量、未指定评论者国家'
        try:
            for _ in range(cfg['pages']):
                day=self.reserve(video,cfg)
                if not day:
                    stop='暂停或达到每日请求上限；保留已取得样本';state='partial';break
                count,new,cursor=self.fetch_page(client,key,r,day,cursor=cursor)
                threads.extend(new)
                if cursor is None:break
            if state=='ready':
                with self.hub.db() as db:
                    kept={x[0] for x in db.execute("SELECT cid FROM comment_sample_text WHERE video=? AND parent=''",(video,))}
                ranked=[cid for _,cid in sorted(set(threads)) if cid in kept]
                for parent in ranked[:cfg['replies']]:
                    day=self.reserve(video,cfg)
                    if not day:
                        stop='暂停或达到每日请求上限；保留已取得样本';state='partial';break
                    count,_,_=self.fetch_page(client,key,r,day,parent=parent)

        except RemoteError as exc:
            state='attention';error=str(exc);halt=exc.halt
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            n=db.execute('SELECT count(*) FROM comment_sample_text WHERE video=?',(video,)).fetchone()[0]
            actual=db.execute('SELECT requests FROM comment_sample_jobs WHERE video=?',(video,)).fetchone()[0]
            if not actual and not n and state=='partial':state='queued'
            elif not n and state=='ready':state='empty';stop='该次未取得可用评论，不代表视频没有评论'
            elif n and state=='attention':state='partial'
            db.execute('UPDATE comment_sample_jobs SET state=?,stop_reason=?,error=?,updated=?,finished=? WHERE video=?',(state,stop,error,self.clock(),None if state=='queued' else self.clock(),video))
            if halt and not only_video:db.execute('UPDATE comment_sample_config SET collect_error=? WHERE id=1',(error,))
        return state!='queued'

    def ai_one(self,client,*,only_video=None):
        claimed=self.claim_single('ai',only_video) if only_video else self.claim('ai')
        if not claimed:return False
        r,cfg,key=claimed;video=r['video'];state='ready';topics=[];research=None;error='';halt=False
        supplement=cfg['supplement']
        pending=("j.ai_state='ready' AND EXISTS(SELECT 1 FROM comment_sample_research s WHERE s.video=j.video AND s.state='running')"
                 if supplement else "j.ai_state='running'")
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            eligible=db.execute(f"SELECT 1 FROM comment_sample_jobs j WHERE video=? AND {pending} AND {IN_CASE_LIBRARY} AND (? OR EXISTS(SELECT 1 FROM comment_sample_config WHERE ai=1 AND ai_error=''))",(video,bool(only_video))).fetchone()
            if not eligible or self.hub.stop.is_set():
                if supplement:db.execute("UPDATE comment_sample_research SET state='queued' WHERE video=? AND state='running'",(video,))
                else:db.execute("UPDATE comment_sample_jobs SET ai_state='pending' WHERE video=? AND ai_state='running'",(video,))
                return False
            rows=[dict(x) for x in db.execute('SELECT cid,parent,text FROM comment_sample_text WHERE video=? ORDER BY parent<>\'\',ordinal,cid',(video,))]
        try:
            if rows:
                with feedback.bound(self.hub,'comment_research' if supplement else 'comment_ai',video), feedback.step('ai_call'):
                    topics,research=analyse(client,key,rows)
                if not research:
                    with feedback.bound(self.hub,'comment_research',video), feedback.step('ai_validate') as attempt:
                        attempt.mark('attention')
        except RemoteError as exc:
            state='attention';error=str(exc);halt=exc.halt
        with feedback.bound(self.hub,'comment_research' if supplement else 'comment_ai',video), feedback.step('ai_save'), self.hub.db() as db:
            if not supplement:
                db.execute('UPDATE comment_sample_jobs SET ai_state=?,ai_error=?,model=?,topics=?,updated=? WHERE video=?',(state,error,MODEL,json.dumps(topics,ensure_ascii=False),self.clock(),video))
            if supplement or state=='ready' and rows:
                db.execute('''INSERT INTO comment_sample_research(video,state,payload,error,updated) VALUES(?,?,?,?,?)
                  ON CONFLICT(video) DO UPDATE SET state=excluded.state,payload=excluded.payload,error=excluded.error,updated=excluded.updated''',
                  (video,'ready' if research else 'attention',json.dumps(research or {},ensure_ascii=False),
                   '' if research else error or 'AI 未返回可核对的多维标注，已保留原主题；未自动重试',self.clock()))
            if halt and not only_video:db.execute('UPDATE comment_sample_config SET ai_error=? WHERE id=1',(error,))
        return True

    def loop(self,kind):
        import logging
        with httpx.Client(timeout=httpx.Timeout(12.0,connect=5.0),follow_redirects=False,trust_env=False) as client:
            while not self.hub.stop.is_set():
                try:done=(self.collect_one if kind=='collect' else self.ai_one)(client)
                except Exception:
                    # Avoid leaking URLs, vendor response bodies or credentials in exception logs.
                    logging.getLogger(__name__).error('Comment sample worker interrupted: %s',kind)
                    column='state' if kind=='collect' else 'ai_state';error='error' if kind=='collect' else 'ai_error'
                    msg='处理中断，结果可能未知；队列已暂停，请核对供应商记录后恢复后续任务'
                    try:
                        with self.hub.db() as db:
                            db.execute('BEGIN IMMEDIATE')
                            db.execute(f"UPDATE comment_sample_jobs SET {column}='attention',{error}=? WHERE {column}='running'",(msg,))
                            if kind=='ai':db.execute("UPDATE comment_sample_research SET state='attention',error=? WHERE state='running'",(msg,))
                            db.execute(f'UPDATE comment_sample_config SET {kind}_error=? WHERE id=1',(msg,))
                    except Exception:
                        # Fail closed until restart recovery if even the halt cannot be committed.
                        return
                    self.hub.stop.wait(8)
                    continue
                self.hub.stop.wait(2 if done else 8)


def attach(app,hub,user,body):
    svc=SampleService(hub);app.state.comment_samples=svc;hub.comment_samples_ready=True

    @app.get(PREFIX+'/config')
    def config(request:Request):return svc.status(user(request)['role']=='admin')

    @app.post(PREFIX+'/config')
    async def configure(request:Request):
        u=user(request,True);d=await body(request);action=d.get('action');now=svc.clock();added=0
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM comment_sample_config').fetchone()
            if action=='save':
                key=d.get('key','')
                if not isinstance(key,str) or key and not re.fullmatch(r'[!-~]{10,500}',key):raise HTTPException(400,'请输入有效的 ScrapeCreators API Key（不含空格）')
                if not key and not r['secret']:raise HTTPException(400,'请先填入 API Key')
                caps=[]
                for name,low,high in [('daily',0,100),('ai_daily',0,30),('pages',1,3),('replies',0,3)]:
                    n=d.get(name,r[name]);
                    if type(n) is not int or not low<=n<=high:raise HTTPException(400,f'{name} 需为 {low} 到 {high} 的整数')
                    caps.append(n)
                if caps[0] and caps[0]<caps[2]+caps[3]:raise HTTPException(400,'每日请求上限不能小于每条视频可能需要的请求数')
                secret=hub.cipher.encrypt(key.encode('ascii')) if key else r['secret']
                db.execute('UPDATE comment_sample_config SET secret=?,daily=?,ai_daily=?,pages=?,replies=?,collect=0,ai=0,updated=? WHERE id=1',(secret,*caps,now))
            elif action=='enable':
                if d.get('confirm_paid') is not True or not r['secret']:raise HTTPException(400,'请先保存密钥并明确确认采集费用')
                db.execute("UPDATE comment_sample_config SET collect=1,collect_error='',updated=? WHERE id=1",(now,))
                if not r['collect']:
                    db.execute('UPDATE comment_sample_config SET backfill_until=? WHERE id=1',(now,))
                    added=svc.backfill(db,now)
            elif action=='disable':db.execute('UPDATE comment_sample_config SET collect=0,updated=? WHERE id=1',(now,))
            elif action=='backfill':
                if not r['collect'] or r['collect_error'] or d.get('confirm_paid') is not True:raise HTTPException(400,'请先恢复采集并确认费用')
                db.execute('DELETE FROM comment_sample_scope')
                db.execute('UPDATE comment_sample_config SET backfill_until=? WHERE id=1',(now,))
                added=svc.backfill(db,now)
            elif action=='enable_ai':
                if d.get('confirm_ai') is not True or not db.execute('SELECT 1 FROM a6_settings WHERE id=1').fetchone():raise HTTPException(400,'请先配置 A6API 并确认传输公开评论文本及费用')
                db.execute("UPDATE comment_sample_config SET ai=1,ai_error='' WHERE id=1")
            elif action=='disable_ai':db.execute('UPDATE comment_sample_config SET ai=0 WHERE id=1')
            else:raise HTTPException(400,'配置操作无效')
            hub.log(db,u['id'],'comment_samples_'+action,'team')
        return svc.status(True)|{'queued_now':added}

    @app.post(PREFIX+'/{video}/research')
    async def supplement(video:str,request:Request):
        u=user(request,True);d=await body(request)
        if d.get('confirm_ai') is not True:raise HTTPException(400,'请确认额外 AI 请求的费用及公开文本外发')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            j=db.execute(f'SELECT j.ai_state FROM comment_sample_jobs j WHERE j.video=? AND {IN_CASE_LIBRARY}',(video,)).fetchone()
            if not j:raise HTTPException(404,'此视频没有可用的团队案例样本')
            saved=db.execute('SELECT state FROM comment_sample_research WHERE video=?',(video,)).fetchone()
            if saved:return {'state':saved['state'],'queued_now':False}
            cfg=db.execute('SELECT ai,ai_error FROM comment_sample_config WHERE id=1').fetchone()
            if not cfg['ai'] or cfg['ai_error'] or not db.execute('SELECT 1 FROM a6_settings WHERE id=1').fetchone():
                raise HTTPException(409,'评论 AI 当前未启用或已暂停；先核对「数据接入」，本次未排队')
            if j['ai_state']!='ready' or not db.execute('SELECT 1 FROM comment_sample_text WHERE video=? LIMIT 1',(video,)).fetchone():
                raise HTTPException(409,'仅可为已有旧版 AI 结果的样本单次补标。未完成或结果待核对的任务不会重提。')
            db.execute("INSERT INTO comment_sample_research(video,state,updated) VALUES(?,'queued',?)",(video,svc.clock()))
            hub.log(db,u['id'],'comment_research_supplement',video)
        return {'state':'queued','queued_now':True}

    @app.get(PREFIX)
    def listing(request:Request,offset:int=0,video:str=''):
        user(request)
        if not 0<=offset<=100000 or video and not re.fullmatch(r'[0-9]{5,25}',video):raise HTTPException(400,'查询参数无效')
        with hub.db() as db:
            where=f' WHERE {IN_CASE_LIBRARY}'+(' AND j.video=?' if video else '');args=(video,) if video else ()
            count=db.execute('SELECT count(*) FROM comment_sample_jobs j'+where,args).fetchone()[0]
            rows=db.execute("SELECT video,url,state,ai_state,origin,created,pages,reply_pages,error,ai_error,(SELECT count(*) FROM comment_sample_text t WHERE t.video=j.video) AS samples FROM comment_sample_jobs j"+where+" ORDER BY created DESC,video LIMIT 20 OFFSET ?",(*args,offset)).fetchall()
        return {'items':[dict(r) for r in rows],'total':count}

    @app.get(PREFIX+'/{video}')
    def detail(video:str,request:Request):
        user(request)
        with hub.db() as db:
            r=db.execute(f'SELECT j.* FROM comment_sample_jobs j WHERE video=? AND {IN_CASE_LIBRARY}',(video,)).fetchone()
            if not r:raise HTTPException(404,'此视频还没有补采记录，或不在团队样本范围内')
            rows=[dict(x) for x in db.execute('SELECT cid,parent,text,published,observed FROM comment_sample_text WHERE video=? ORDER BY parent<>\'\',ordinal,cid',(video,))]
            mark=db.execute("SELECT payload FROM comment_sample_research WHERE video=? AND state='ready'",(video,)).fetchone()
        research=read_pack(mark['payload'],rows) if mark and r['ai_state']=='ready' else None
        if research:
            research={k:{'description':SIGNALS[k],**row_counts({cid for g in groups for cid in g['ids']},rows),
                         'groups':[dict(g,**row_counts(set(g['ids']),rows)) for g in groups]} for k,groups in research['signals'].items()}
        by_id={x['cid']:x for x in rows};top=sum(not x['parent'] for x in rows);replies=len(rows)-top
        def fraction(ids):
            take={x for x in ids if x in by_id}
            return {'comments':sum(not by_id[x]['parent'] for x in take),'replies':sum(bool(by_id[x]['parent']) for x in take),'ids':sorted(take)}
        topics=[{'label':t['label'],'support':fraction(t['support']),'counter':fraction(t['counter'])} for t in json.loads(r['topics'])]
        return dict(r)|{'topics':topics,'comments':top,'replies':replies,'samples':rows,'research':research}
