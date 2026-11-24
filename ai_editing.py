"""Owner-scoped, opt-in AI editing. Models propose data, never executable tools.
All accepted plans create a NEW existing-editor project; manual edits are never overwritten.
"""
import base64
import hashlib
import json
import math
import secrets
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
import asr
from editor import probe, run, record_version

ACTIVE = ('queued', 'running', 'retry_wait')
MAX_SOURCES = 5
MAX_SECONDS = 600

def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()

def finite(value, low, high):
    if isinstance(value, bool): raise ValueError('时间参数无效')
    try: value = float(value)
    except (ValueError, TypeError): raise ValueError('时间参数无效') from None
    if not math.isfinite(value) or not low <= value <= high: raise ValueError('时间参数超出范围')
    return value

def text(value, limit=500):
    if not isinstance(value, str) or len(value) > limit: raise ValueError('文字内容过长或格式无效')
    return value.strip()

def clean_brief(raw):
    if not isinstance(raw, dict): raise ValueError('请填写内容方向')
    result = {k: text(raw.get(k, ''), n) for k, n in [('product',100),('audience',300),('reason',300),('facts',2000),('avoid',1000)]}
    # Legacy commerce fields are optional; the conversation contract holds general intent.
    result['target'] = finite(raw.get('target',30), 3, 180)
    result['ratio'] = raw.get('ratio','9:16')
    result['language'] = raw.get('language','en')
    result['sound'] = raw.get('sound','original')
    if result['ratio'] not in ('9:16','16:9','1:1') or result['language'] not in asr.LANGUAGES or result['sound'] not in ('original','mute'):
        raise ValueError('画幅、语言或原声设置无效')
    return result

class Cancelled(Exception): pass
class Unknown(Exception): pass
class Limited(Exception): pass

class AIEditing:
    def __init__(self, hub, editor):
        self.hub, self.editor = hub, editor
        self.root = hub.directory / 'ai_edits'
        self.root.mkdir(exist_ok=True)
        with hub.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS ai_edit_projects(
              id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,
              revision INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS ai_edit_owner ON ai_edit_projects(owner,updated);
            CREATE TABLE IF NOT EXISTS ai_edit_creates(owner TEXT NOT NULL,request_key TEXT NOT NULL,project_id TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(owner,request_key));
            CREATE TABLE IF NOT EXISTS ai_edit_jobs(
              id TEXT PRIMARY KEY,owner TEXT NOT NULL,project_id TEXT NOT NULL,kind TEXT NOT NULL,
              request_key TEXT NOT NULL,input TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',
              cancel INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,due REAL NOT NULL DEFAULT 0,
              created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(owner,request_key));
            CREATE TABLE IF NOT EXISTS ai_edit_applied(
              owner TEXT NOT NULL,project_id TEXT NOT NULL,plan_hash TEXT NOT NULL,edit_id TEXT NOT NULL,
              PRIMARY KEY(owner,project_id,plan_hash));
            ''')

    def sources(self, ids, owner, admin):
        if not isinstance(ids,list) or not 1 <= len(ids) <= MAX_SOURCES or any(not isinstance(s,str) for s in ids) or len(set(ids)) != len(ids):
            raise ValueError('试运行支持选择 1–5 条不同视频')
        result=[]
        for sid in ids:
            if not isinstance(sid,str) or len(sid)>100: raise ValueError('素材标识无效')
            path=self.editor.source(owner,admin,sid)
            duration,streams=probe(path)
            if not .1 <= duration <= MAX_SECONDS or not any(s['codec_type']=='video' for s in streams): raise ValueError('素材须为 10 分钟以内视频')
            stat=path.stat()
            # Fingerprint is private and opaque; no local paths are sent to the model or client.
            fingerprint=digest([str(path.resolve()),stat.st_size,stat.st_mtime_ns])
            result.append({'id':sid,'duration':duration,'fingerprint':fingerprint,'has_audio':any(s['codec_type']=='audio' for s in streams)})
        if sum(s['duration'] for s in result)>MAX_SECONDS: raise ValueError('本次试运行累计素材不超过 10 分钟')
        return result

    def owned(self, db, pid, owner):
        row=db.execute('SELECT * FROM ai_edit_projects WHERE id=? AND owner=?',(pid,owner)).fetchone()
        if not row: raise HTTPException(404,'AI 剪辑项目不存在')
        return row

    def serialize(self,row,admin=False):
        body=json.loads(row['body'])
        if body.get('sources'): self.sources(body['sources'],row['owner'],admin)
        with self.hub.db() as db:
            jobs=[{k:r[k] for k in ('id','kind','state','error','cancel','attempts','updated','stage')} for r in db.execute('SELECT * FROM ai_edit_jobs WHERE project_id=? AND owner=? ORDER BY created DESC LIMIT 12',(row['id'],row['owner']))]
            applied=db.execute('SELECT edit_id FROM ai_edit_applied WHERE owner=? AND project_id=? AND plan_hash=?',(row['owner'],row['id'],body.get('plan_hash',''))).fetchone()
        body['current_plan_edit_id']=applied['edit_id'] if applied else None
        from ai_edit_duration import POLICY
        body['execution_policy']=POLICY
        from ai_edit_vision import POLICY as INSPECTION_POLICY, MAX_CALLS
        body['inspection_policy_available']=INSPECTION_POLICY
        body['max_execution_model_calls']=MAX_CALLS
        with self.hub.db() as db:
            observations=db.execute('SELECT o.name,o.body FROM ai_edit_observations o JOIN ai_edit_jobs j ON j.id=o.job_id WHERE j.owner=? AND (j.id=? OR j.id=?) ORDER BY o.updated',(row['owner'],body.get('execution_job_id',''),body.get('review_job_id',''))).fetchall()
        body['observations']=[{'name':o['name'],'body':json.loads(o['body'])} for o in observations]
        with self.hub.db() as db:
            candidates=db.execute('SELECT c.pass,c.plan FROM ai_edit_candidates c JOIN ai_edit_jobs j ON j.id=c.job_id WHERE j.owner=? AND j.id=? ORDER BY c.pass',(row['owner'],body.get('execution_job_id',''))).fetchall()
        body['execution_candidates']=[{'pass':c['pass'],'plan':json.loads(c['plan'])} for c in candidates]
        if body.get('conversation'):
            from ai_edit_conversation import confirmation
            body['confirmation_hash']=confirmation(self,body,row['owner'],admin)
        if body.get('export_id'):
            with self.hub.db() as db:
                export=db.execute('SELECT state,error FROM edit_exports WHERE id=? AND owner=?',(body['export_id'],row['owner'])).fetchone()
            body['export_status']=dict(export) if export else {'state':'failed','error':'导出记录不存在'}
        if jobs and jobs[0]['kind']=='discuss' and jobs[0]['state'] in ('queued','running','retry_wait','unknown','failed'):
            with self.hub.db() as db:
                pending=db.execute('SELECT input FROM ai_edit_jobs WHERE id=?',(jobs[0]['id'],)).fetchone()
            body['pending_message']=json.loads(pending['input']).get('message','')
        return {'id':row['id'],'title':row['title'],'revision':row['revision'],'created':row['created'],'updated':row['updated'],'body':body,'jobs':jobs,'input_hash':digest({'sources':body.get('sources'),'brief':body.get('brief'),'analysis':body.get('analysis')})}

    def check_sources(self, snap,owner,admin):
        current=self.sources(snap['sources'],owner,admin)
        if current!=snap['source_info']: raise ValueError('素材发生变化，请重新保存并分析')
        return current

    def cancelled(self,jid):
        with self.hub.db() as db: row=db.execute('SELECT cancel FROM ai_edit_jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['cancel'] or self.hub.stop.is_set(): raise Cancelled()

    def analyze(self, snap, owner, admin, jid):
        from media_work import MEDIA_LOCK
        with MEDIA_LOCK:
            self.check_sources(snap,owner,admin)
            result=[]
            for source in snap['source_info']:
                self.cancelled(jid)
                sid=source['id'];path=self.editor.source(owner,admin,sid)
                # Bounded coverage of beginning/middle/end; still samples, not full video understanding.
                import editor_media_cache
                from ai_edit_duration import sample_times
                frames=[]
                from ai_edit_vision import overview_times
                times=overview_times(source['duration'],sum(s['duration'] for s in snap['source_info'])) if snap.get('inspection_authorized') else sample_times(source['duration'])
                for at in times:
                    actual=editor_media_cache.frame_time(path,at)
                    try:image=editor_media_cache.thumbnail(path,actual,run,shutil.which('ffmpeg'))
                    except ValueError:raise ValueError(f'素材 {sid} 在 {actual:.3f} 秒抽帧失败；本地分析阶段停止，尚未调用剪辑规划') from None
                    if not any(abs(f['at']-actual)<.001 for f in frames):frames.append({'at':actual})
                language='';segments=[];warning=''
                if source['has_audio']:
                    if not asr.status()['model_ready']: warning='本地语音模型未就绪，未下载模型；请管理员准备后重新分析'
                    else:
                        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
                            wav=Path(tmp)/'speech.wav'
                            try:run([shutil.which('ffmpeg'),'-v','error','-y','-i',str(path),'-vn','-ac','1','-ar','16000',str(wav)],timeout=180)
                            except ValueError:raise ValueError(f'素材 {sid} 提取语音失败；本地分析阶段停止，尚未调用剪辑规划') from None
                            try: language,segments=asr.transcribe(wav)
                            except Exception: warning='口播识别失败；可查看画面，但需人工核对语句和字幕'
                else: warning='素材没有音轨'
                if source['has_audio'] and not segments and not warning: warning='未识别到清晰口播，请人工核对'
                result.append({**source,'language':language,'segments':segments,'frames':frames,'warning':warning})
            self.cancelled(jid)
            return result

    def plan(self,snap,owner,admin,jid):
        from assistant_chat import ENDPOINT, MODEL, parse_answer
        import editor_media_cache
        self.check_sources(snap,owner,admin)
        key=asr.configured_key(self.hub)
        if not key: raise ValueError('尚未配置 A6API Gemini 3.8 Flash，请在现有 AI 助理设置中配置')
        content=[]
        from ai_edit_duration import budget
        from ai_edit_provenance import observation_context
        previous=snap.get('plan')
        previous_data={'duration':previous['duration'],'shots':previous['shots']} if previous else None
        context={'brief':snap['brief'],'contract':snap.get('contract'),'requirement_authority':snap.get('requirement_authority'),'instructions':snap.get('instructions',''),'inspection':observation_context(snap.get('inspection')),'sources':snap['analysis'],'previous_plan':previous_data,'adjustment':snap.get('adjustment',''),'duration_budget':budget(snap),'duration_repair':snap.get('duration_repair')}
        content.append({'type':'text','text':packed(context)})
        for source in snap['analysis']:
            path=self.editor.source(owner,admin,source['id'])
            for frame in source['frames']:
                self.cancelled(jid)
                if snap.get('inspection_authorized'):
                    from ai_edit_vision import frame as inspection_frame
                    image=inspection_frame(self,path,frame['at'])
                else:image=editor_media_cache.thumbnail(path,frame['at'],run,shutil.which('ffmpeg'))
                content.extend([{'type':'text','text':f"source_id={source['id']}; source_time={frame['at']}"},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(image.read_bytes()).decode()}}])
        from ai_edit_requirements import PLANNER
        system=PLANNER
        payload={'model':MODEL,'messages':[{'role':'system','content':system},{'role':'user','content':content}],'max_tokens':6500,'temperature':.3,'stream':False}
        self.cancelled(jid)
        request=urllib.request.Request(ENDPOINT,data=packed(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
        try:
            with urllib.request.urlopen(request,timeout=150) as response: raw=response.read(600000)
        except urllib.error.HTTPError as exc:
            if exc.code==429: raise Limited('AI 服务明确限流，等待后有限重试') from None
            if 400 <= exc.code < 500: raise ValueError(f'AI 服务拒绝请求（HTTP {exc.code}），未自动重提') from None
            raise Unknown('AI 服务端异常，是否受理未知；未自动重提，请先核对提供商记录') from None
        except (OSError, socket.timeout):
            raise Unknown('AI 请求超时或连接中断，结果未知；未自动重提，请先核对提供商记录') from None
        try:
            response=json.loads(raw)
            if response.get('choices',[{}])[0].get('finish_reason') in ('length','max_tokens'): raise ValueError('AI 方案被截断，未自动重提')
            answer=parse_answer(response).strip()
            from ai_edit_response import object_answer
            plan=object_answer(answer)
            plan=self.validate_plan(plan,snap)
            usage=response.get('usage')
            if isinstance(usage,dict): plan['usage']={k:v for k,v in usage.items() if k in ('prompt_tokens','completion_tokens','total_tokens') and isinstance(v,(int,float))}
            return plan
        except (KeyError,TypeError,IndexError,json.JSONDecodeError): raise ValueError('AI 返回格式无效，未自动修复或重复计费；可手动编辑方案或主动重新请求') from None

    def validate_plan(self,raw,snap):
        if not isinstance(raw,dict) or set(raw)-{'summary','shots','risks','usage'}: raise ValueError('方案字段无效')
        shots=raw.get('shots')
        if not isinstance(shots,list) or not 1<=len(shots)<=30: raise ValueError('方案须包含 1–30 个片段')
        sources={s['id']:s for s in snap['source_info']}; clean=[];at=0
        for shot in shots:
            if not isinstance(shot,dict) or set(shot)-{'source_id','start','end','purpose','reason','title'}: raise ValueError('镜头字段无效')
            sid=shot.get('source_id')
            if not isinstance(sid,str) or sid not in sources: raise ValueError('方案引用了未选中的素材')
            duration=sources[sid]['duration'];start=round(finite(shot.get('start'),0,duration)*24)/24
            end=min(math.floor(duration*24)/24,round(finite(shot.get('end'),0,duration+.001)*24)/24)
            if end-start<.125: raise ValueError('片段至少保留 3 帧')
            clean.append({'source_id':sid,'start':start,'end':end,'at':at,'purpose':text(shot.get('purpose',''),80),'reason':text(shot.get('reason',''),600),'title':text(shot.get('title',''),100)})
            at=round((at+end-start)*24)/24
        if at>600: raise ValueError('方案过长')
        risks=raw.get('risks',[])
        if not isinstance(risks,list) or len(risks)>40: raise ValueError('风险说明无效')
        risks=[text(r,500) for r in risks]
        if abs(at-snap['brief']['target'])>max(.5,snap['brief']['target']*.1): risks.append(f"方案时长 {at:.2f} 秒偏离目标 {snap['brief']['target']:g} 秒；应用前需确认")
        if any(s.get('warning') for s in snap.get('analysis',[])): risks.append('部分素材口播不完整或不可识别，请人工核对')
        risks.append('采样画面与ASR可能遗漏动作或识别错误；未确定内容需预览核对，不能将推断当事实。')
        for i,shot in enumerate(clean):
            if any(p['source_id']==shot['source_id'] and min(p['end'],shot['end'])-max(p['start'],shot['start'])>.1 for p in clean[:i]):
                risks.append('同一素材存在重复使用的时间区间，请确认是否有意重复。')
        return {'summary':text(raw.get('summary',''),1500),'shots':clean,'risks':list(dict.fromkeys(risks)),'duration':at}

    def engine_body(self,plan,snap,owner,admin):
        if snap.get('analysis'):
            self.check_sources({'sources':snap['sources'],'source_info':[{k:a[k] for k in ('id','duration','fingerprint','has_audio')} for a in snap['analysis']]},owner,admin)
        captions=[];clips=[]
        for shot in plan['shots']:
            start,end,at=shot['start'],shot['end'],shot['at']
            clips.append({'task_id':shot['source_id'],'start':start,'end':end,'at':at,'track':'video-main','volume':1 if snap['brief']['sound']=='original' else 0,'speed':1})
            if shot['title']: captions.append({'text':shot['title'],'start':at,'end':min(at+3,at+end-start),'track':'caption-title','x':.5,'y':.18})
            source=next((s for s in snap.get('analysis',[]) if s['id']==shot['source_id']),{})
            if source.get('language')==snap['brief']['language'] and (snap.get('contract') or {}).get('captions','asr')!='none':
                for row in source.get('segments',[]):
                    # Never display a whole sentence over a trimmed fragment of that sentence.
                    if row['start']>=start-.04 and row['end']<=end+.04 and row['end']>row['start']:
                        captions.append({'text':row['text'][:300],'start':max(at,at+row['start']-start),'end':min(at+end-start,at+row['end']-start),'track':'caption-main','lang':source['language']})
        return self.editor.validate({'ratio':snap['brief']['ratio'],'target_duration':snap['brief']['target'],'clips':clips,'captions':captions,'main_track':'video-main'},owner,admin)

    def recover(self):
        with self.hub.db() as db:
            db.execute("UPDATE ai_edit_jobs SET state=CASE WHEN kind IN ('plan','execute','discuss','review') THEN 'unknown' ELSE 'failed' END,error='服务重启中断；外部结果未知时不会自动重提',updated=? WHERE state='running'",(time.time(),))

    def loop(self):
        while not self.hub.stop.is_set():
            try: self.tick()
            except Exception:
                import logging
                logging.getLogger(__name__).exception('AI edit worker failed')
            self.hub.stop.wait(2)

    def tick(self):
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT j.*,u.role,u.enabled FROM ai_edit_jobs j JOIN users u ON u.id=j.owner WHERE j.state IN ('queued','retry_wait') AND j.due<=? ORDER BY j.created LIMIT 1",(time.time(),)).fetchone()
            if not row:return
            db.execute("UPDATE ai_edit_jobs SET state='running',attempts=attempts+1,updated=? WHERE id=?",(time.time(),row['id']))
        state,error='ready',''
        try:
            if not row['enabled']: raise ValueError('成员账号已停用')
            self.cancelled(row['id'])
            snap=json.loads(row['input']);admin=row['role']=='admin'
            if row['kind']=='review':
                from ai_edit_vision import perform_review
                result=perform_review(self,row,snap)
            elif row['kind'] in ('discuss','execute'):
                from ai_edit_conversation import perform
                result=perform(self,row,snap)
            else:result=self.analyze(snap,row['owner'],admin,row['id']) if row['kind']=='analyze' else self.plan(snap,row['owner'],admin,row['id'])
            self.cancelled(row['id'])
            if snap.get('sources'):self.check_sources(snap,row['owner'],admin)
            with self.hub.db() as db:
                db.execute('BEGIN IMMEDIATE')
                current=self.owned(db,row['project_id'],row['owner']);data=json.loads(current['body'])
                cancelled=db.execute('SELECT cancel FROM ai_edit_jobs WHERE id=?',(row['id'],)).fetchone()
                if cancelled['cancel']:raise Cancelled()
                if current['revision']!=snap['revision']: raise ValueError('项目版本已变化，结果未覆盖新内容')
                if row['kind']=='discuss':
                    data.update(result)
                    data.pop('pending_message',None)
                    db.execute('UPDATE ai_edit_projects SET title=? WHERE id=?',((result['brief'].get('product') or '对话剪辑')[:60]+' · AI 剪辑',row['project_id']))
                elif row['kind']=='review':data.update(result)
                elif row['kind']=='execute':
                    from ai_edit_conversation import commit_execution
                    commit_execution(self,db,row,data,result)
                elif row['kind']=='analyze': data['analysis']=result;data.pop('plan',None)
                else:
                    old=data.get('plan')
                    if old:data['history']=(data.get('history',[])+[old])[-8:]
                    data['plan']=result;data['plan_hash']=digest(result)
                db.execute('UPDATE ai_edit_projects SET body=?,revision=revision+1,updated=? WHERE id=?',(packed(data),time.time(),row['project_id']))
        except Cancelled: state,error='cancelled','已取消；若外部请求已发送，取消不保证退款'
        except Unknown as exc: state,error='unknown',str(exc)
        except Limited as exc:
            state='retry_wait' if row['attempts']<2 and row['kind'] in ('plan',) else 'failed';error=str(exc) if state=='retry_wait' else '连续限流，已停止自动重试'
        except Exception as exc:
            state,error='failed',str(exc) if isinstance(exc,(ValueError,HTTPException)) else '任务失败，请检查素材或联系管理员'
        with self.hub.db() as db:
            db.execute('UPDATE ai_edit_jobs SET state=?,error=?,due=?,updated=? WHERE id=?',(state,error,time.time()+60,time.time(),row['id']))


def attach(app,hub,user,body):
    service=AIEditing(hub,app.state.editor);app.state.ai_editing=service
    from ai_edit_conversation import attach as attach_conversation
    attach_conversation(app,hub,user,body,service)

    def snapshot(row,u):
        data=json.loads(row['body'])
        return {**data,'revision':row['revision'],'source_info':service.sources(data.get('sources'),u['id'],u['role']=='admin')}

    @app.get('/api/ai-edit/projects')
    def listing(request:Request):
        u=user(request)
        with hub.db() as db: rows=db.execute('SELECT id,title,revision,created,updated FROM ai_edit_projects WHERE owner=? ORDER BY updated DESC LIMIT 100',(u['id'],)).fetchall()
        return [dict(r) for r in rows]

    @app.get('/api/ai-edit/projects/{pid}')
    def detail(pid:str,request:Request):
        u=user(request)
        try:
            with hub.db() as db: row=service.owned(db,pid,u['id'])
            return service.serialize(row,u['role']=='admin')
        except ValueError as exc: raise HTTPException(400,str(exc)) from None

    @app.post('/api/ai-edit/projects')
    async def save(request:Request):
        u=user(request);data=await body(request)
        try:
            brief=clean_brief(data.get('brief'));ids=data.get('sources');service.sources(ids,u['id'],u['role']=='admin')
            title=text(data.get('title') or brief['product']+' · AI 剪辑',80)
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE');pid=data.get('id')
                if pid:
                    row=service.owned(db,pid,u['id'])
                    if row['revision']!=data.get('revision'): raise HTTPException(409,'项目已更新，请重新载入')
                    if db.execute("SELECT 1 FROM ai_edit_jobs WHERE project_id=? AND state IN ('queued','running','retry_wait')",(pid,)).fetchone(): raise HTTPException(409,'任务执行中，请先取消或等待')
                    old=json.loads(row['body']);content={'brief':brief,'sources':ids}
                    if old.get('sources')==ids:
                        if old.get('analysis'): content['analysis']=old['analysis']
                        if old.get('brief')==brief: content=old
                    if content.get('analysis'):
                        now_sources=service.sources(ids,u['id'],u['role']=='admin')
                        if any(a['fingerprint']!=s['fingerprint'] for a,s in zip(content['analysis'],now_sources)):
                            content={'brief':brief,'sources':ids}
                    db.execute('UPDATE ai_edit_projects SET title=?,body=?,revision=revision+1,updated=? WHERE id=?',(title,packed(content),time.time(),pid))
                else:
                    key=data.get('request_key');signature=digest([title,brief,ids])
                    if not isinstance(key,str) or not 8<=len(key)<=100:raise HTTPException(400,'请提供创建请求标识')
                    prior=db.execute('SELECT * FROM ai_edit_creates WHERE owner=? AND request_key=?',(u['id'],key)).fetchone()
                    if prior:
                        if prior['signature']!=signature:raise HTTPException(409,'创建标识对应的内容不一致，请先检查项目列表')
                        return service.serialize(service.owned(db,prior['project_id'],u['id']),u['role']=='admin')
                    pid=secrets.token_hex(12);now=time.time()
                    db.execute('INSERT INTO ai_edit_projects VALUES(?,?,?,?,?,?,?)',(pid,u['id'],title,packed({'brief':brief,'sources':ids}),1,now,now))
                    db.execute('INSERT INTO ai_edit_creates VALUES(?,?,?,?)',(u['id'],key,pid,signature))
                row=service.owned(db,pid,u['id'])
            return service.serialize(row,u['role']=='admin')
        except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc)) from None

    @app.post('/api/ai-edit/projects/{pid}/jobs')
    async def enqueue(pid:str,request:Request):
        u=user(request);data=await body(request);kind=data.get('kind');key=data.get('request_key')
        if kind not in ('analyze','plan') or not isinstance(key,str) or not 8<=len(key)<=100: raise HTTPException(400,'任务类型或请求标识无效')
        try:
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE');row=service.owned(db,pid,u['id'])
                old=db.execute('SELECT id,project_id,kind FROM ai_edit_jobs WHERE owner=? AND request_key=?',(u['id'],key)).fetchone()
                if old:
                    if old['project_id']!=pid or old['kind']!=kind: raise HTTPException(409,'请求标识已用于其他任务')
                    return {'id':old['id']}
                if row['revision']!=data.get('revision'):raise HTTPException(409,'项目版本已更新，请重新载入')
                if db.execute("SELECT 1 FROM ai_edit_jobs WHERE owner=? AND state IN ('queued','running','retry_wait')",(u['id'],)).fetchone():raise HTTPException(409,'已有任务执行中，请等待或取消')
                snap=snapshot(row,u)
                if kind=='plan':
                    if data.get('consent') is not True:raise HTTPException(400,'请明确确认外部模型调用及可能的费用')
                    if not snap.get('analysis'):raise HTTPException(400,'请先完成本地分析')
                    if any(s['fingerprint']!=a['fingerprint'] for s,a in zip(snap['source_info'],snap['analysis'])):raise HTTPException(409,'素材变化，请重新分析')
                    expected=digest({'sources':snap['sources'],'brief':snap['brief'],'analysis':snap['analysis']})
                    if data.get('input_hash')!=expected:raise HTTPException(409,'确认范围发生变化，请重新确认')
                    if not asr.configured_key(hub):raise HTTPException(400,'请先在 AI 助理设置中配置 A6API Gemini 3.8 Flash')
                    if db.execute("SELECT 1 FROM ai_edit_jobs WHERE owner=? AND state='unknown'",(u['id'],)).fetchone() and data.get('acknowledge_unknown') is not True:raise HTTPException(409,'存在结果未知的 AI 请求；请核对记录并明确确认新调用风险')
                    snap['adjustment']=text(data.get('adjustment',''),1500)
                jid=secrets.token_hex(12);now=time.time()
                db.execute('INSERT INTO ai_edit_jobs(id,owner,project_id,kind,request_key,input,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(jid,u['id'],pid,kind,key,packed(snap),'queued',now,now))
            return {'id':jid}
        except ValueError as exc:raise HTTPException(400,str(exc)) from None

    @app.post('/api/ai-edit/projects/{pid}/cancel')
    async def cancel(pid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            service.owned(db,pid,u['id'])
            db.execute("UPDATE ai_edit_jobs SET cancel=1,state=CASE WHEN state IN ('queued','retry_wait') THEN 'cancelled' ELSE state END,updated=? WHERE owner=? AND project_id=? AND state IN ('queued','running','retry_wait')",(time.time(),u['id'],pid))
        return {'ok':True}

    @app.post('/api/ai-edit/projects/{pid}/plan')
    async def save_plan(pid:str,request:Request):
        u=user(request);data=await body(request)
        try:
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE');row=service.owned(db,pid,u['id'])
                if row['revision']!=data.get('revision'):raise HTTPException(409,'方案版本已更新，请重新载入')
                if db.execute("SELECT 1 FROM ai_edit_jobs WHERE project_id=? AND state IN ('queued','running','retry_wait')",(pid,)).fetchone():raise HTTPException(409,'请等待任务完成后修改方案')
                snap=snapshot(row,u);plan=service.validate_plan(data.get('plan'),snap)
                if snap.get('plan'):snap['history']=(snap.get('history',[])+[snap['plan']])[-8:]
                snap.pop('revision');snap.pop('source_info');snap['plan']=plan;snap['plan_hash']=digest(plan)
                db.execute('UPDATE ai_edit_projects SET body=?,revision=revision+1,updated=? WHERE id=?',(packed(snap),time.time(),pid))
                row=service.owned(db,pid,u['id'])
            return service.serialize(row,u['role']=='admin')
        except ValueError as exc:raise HTTPException(400,str(exc)) from None

    @app.post('/api/ai-edit/projects/{pid}/apply')
    async def apply(pid:str,request:Request):
        u=user(request);data=await body(request)
        try:
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE');row=service.owned(db,pid,u['id']);snap=snapshot(row,u)
                ph=snap.get('plan_hash')
                if not ph or ph!=data.get('plan_hash'):raise HTTPException(409,'确认的方案版本不一致')
                old=db.execute('SELECT edit_id FROM ai_edit_applied WHERE owner=? AND project_id=? AND plan_hash=?',(u['id'],pid,ph)).fetchone()
                if old:return {'id':old['edit_id'],'reused':True}
                if row['revision']!=data.get('revision'):raise HTTPException(409,'项目版本已变化')
                if data.get('confirm') is not True:raise HTTPException(400,'请确认字幕、切点和商品事实后再应用')
                raw=snap['plan'];sanitized={k:raw[k] for k in ('summary','shots','risks')}
                sanitized['shots']=[{k:v for k,v in s.items() if k!='at'} for s in raw['shots']]
                plan=service.validate_plan(sanitized,snap)
                content=service.engine_body(plan,snap,u['id'],u['role']=='admin');eid=secrets.token_hex(12);now=time.time()
                db.execute('INSERT INTO edit_projects VALUES(?,?,?,?,?,?)',(eid,u['id'],row['title'],packed(content),1,now))
                for s in plan['shots']:db.execute('INSERT OR IGNORE INTO project_tasks VALUES(?,?,?,?)',(eid,s['source_id'],u['id'],now))
                record_version(db,eid)
                db.execute('INSERT INTO ai_edit_applied VALUES(?,?,?,?)',(u['id'],pid,ph,eid))
                content_body=json.loads(row['body']);content_body['edit_project_id']=eid
                db.execute('UPDATE ai_edit_projects SET body=?,revision=revision+1,updated=? WHERE id=?',(packed(content_body),now,pid))
            return {'id':eid,'reused':False}
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
