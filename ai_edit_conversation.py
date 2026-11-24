"""Conversation-led AI editing. Requirement discussion never starts media work.
A separate, fingerprint-bound final confirmation authorizes one execution pipeline.
"""
import json
import secrets
import socket
import time
import urllib.error
import urllib.request
from fastapi import Request, HTTPException
import asr
from ai_editing import packed, digest, text, clean_brief, Unknown, Limited
from editor import record_version
from ai_edit_duration import POLICY

DEFAULT_BRIEF={'product':'','audience':'','reason':'','facts':'','avoid':'','target':30,'ratio':'9:16','language':'en','sound':'original'}

def initialize(hub):
    with hub.db() as db:
        cols={r['name'] for r in db.execute('PRAGMA table_info(ai_edit_jobs)')}
        if 'stage' not in cols:db.execute("ALTER TABLE ai_edit_jobs ADD COLUMN stage TEXT NOT NULL DEFAULT ''")
        db.execute('CREATE TABLE IF NOT EXISTS ai_edit_candidates(job_id TEXT NOT NULL,pass INTEGER NOT NULL,plan TEXT NOT NULL,PRIMARY KEY(job_id,pass))')
        db.execute('CREATE TABLE IF NOT EXISTS ai_edit_observations(job_id TEXT NOT NULL,name TEXT NOT NULL,body TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(job_id,name))')
        db.execute('CREATE TABLE IF NOT EXISTS ai_edit_answers(job_id TEXT PRIMARY KEY,answer TEXT NOT NULL,finish_reason TEXT NOT NULL,updated REAL NOT NULL)')

def confirmation(service,body,owner,admin):
    sources=service.sources(body['sources'],owner,admin) if body.get('sources') else []
    return digest({'brief':body.get('brief'),'sources':sources,'instructions':body.get('instructions',''),'messages':body.get('messages',[]),'contract':body.get('contract'),'inspection_policy':INSPECTION_POLICY,'execution_policy':POLICY,'requirement_policy':'requirement-origin-v2'})

def request_json(hub, system, context):
    from assistant_chat import ENDPOINT, MODEL, parse_answer
    key=asr.configured_key(hub)
    if not key:raise ValueError('请先在 AI 助理设置中配置 A6API Gemini 3.8 Flash')
    model_context={k:v for k,v in context.items() if k!='_job_id'}
    payload={'model':MODEL,'messages':[{'role':'system','content':system},{'role':'user','content':packed(model_context)}],'max_tokens':6000,'temperature':.2,'stream':False}
    request=urllib.request.Request(ENDPOINT,data=packed(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
    try:
        with urllib.request.urlopen(request,timeout=120) as response:raw=response.read(400000)
    except urllib.error.HTTPError as exc:
        if exc.code==429:raise Limited('A6API Gemini 3.8 Flash 明确限流，请稍后主动重试；不会自动重复对话') from None
        if 400<=exc.code<500:raise ValueError(f'A6API Gemini 3.8 Flash 拒绝需求对话（HTTP {exc.code}），未重试') from None
        raise Unknown('需求对话服务异常，是否受理未知；未自动重提') from None
    except (OSError,socket.timeout):raise Unknown('需求对话连接中断，结果未知；请核对提供商记录后再发新消息') from None
    try:
        data=json.loads(raw)
        reason=data.get('choices',[{}])[0].get('finish_reason')
        answer=parse_answer(data).strip()
        if context.get('_job_id'):
            with hub.db() as db:db.execute('INSERT OR REPLACE INTO ai_edit_answers VALUES(?,?,?,?)',(context['_job_id'],answer[:200000],str(reason or ''),time.time()))
        if reason in ('length','max_tokens'):raise ValueError('需求回答被截断，原文已保留，未自动重提；未允许开工')
        from ai_edit_response import discussion_answer
        return discussion_answer(answer,context)
    except (TypeError,KeyError,IndexError,json.JSONDecodeError):raise ValueError('需求服务响应结构无效，未自动重提；已有要求未覆盖') from None

from ai_edit_requirements import SYSTEM, clean_contract, blockers, compliance
from ai_edit_vision import POLICY as INSPECTION_POLICY


def stage(service,jid,value):
    service.cancelled(jid)
    with service.hub.db() as db:db.execute('UPDATE ai_edit_jobs SET stage=?,updated=? WHERE id=?',(value,time.time(),jid))

def perform(service,row,snap):
    owner=row['owner'];admin=row['role']=='admin';jid=row['id']
    if row['kind']=='discuss':
        stage(service,jid,'正在整理需求（不分析视频）')
        response=request_json(service.hub,SYSTEM,{'_job_id':jid,'previous_contract':snap.get('contract'),'previous_brief':snap.get('brief',DEFAULT_BRIEF),'previous_instructions':snap.get('instructions',''),'history':snap.get('messages',[])[-24:],'selected_sources':snap.get('source_info',[]),'latest_user_message':snap['message']})
        if not isinstance(response,dict) or set(response)-{'reply','brief','instructions','contract','missing','ready'}:raise ValueError('需求回答字段无效')
        reply=text(response.get('reply',''),6000)
        if not reply:raise ValueError('需求回答为空')
        raw=response.get('brief')
        if not isinstance(raw,dict) or set(raw)-set(DEFAULT_BRIEF):raise ValueError('需求字段无效')
        brief={**DEFAULT_BRIEF,**raw}
        for key,limit in [('product',100),('audience',300),('reason',300),('facts',2000),('avoid',1000)]:brief[key]=text(brief[key],limit)
        missing=response.get('missing',[])
        if not isinstance(missing,list) or len(missing)>20:raise ValueError('待确认要求无效')
        missing=[text(v,400) for v in missing]
        contract=clean_contract(response.get('contract'))
        if snap.get('require_general_contract') and contract is None:raise ValueError('需求回答缺少通用需求总结，未允许开工')
        if snap.get('contract') and contract is None:raise ValueError('本次回答遗漏已确认需求总结，未覆盖旧要求')
        missing=list(dict.fromkeys(missing+blockers(contract)))
        ready=response.get('ready') is True and not missing
        if ready:brief=clean_brief(brief)
        instructions=text(response.get('instructions',''),6000)
        messages=(snap.get('messages',[])+[{'role':'user','text':snap['message']},{'role':'assistant','text':reply}])[-40:]
        result={'brief':brief,'instructions':instructions,'messages':messages,'requirements_ready':ready,'missing':missing,'conversation':True,'requirements_version':digest([brief,instructions,messages,contract])}
        if contract is not None:
            from ai_edit_provenance import ledger
            result['contract']=contract
            result['requirement_ledger']=ledger(contract,messages,snap.get('requirement_ledger'))
        return result
    stage(service,jid,'分析所选素材与口播')
    analysis=service.analyze(snap,owner,admin,jid)
    snap={**snap,'analysis':analysis,'adjustment':'完整确认要求：'+snap.get('instructions','')}
    if snap.get('inspection_authorized'):
        from ai_edit_vision import save
        save(service,jid,'本地分析',{'sources':analysis,'method':'sampled-images-asr','note':'仅技术采样与ASR，尚不等于语义理解'})
    inspection=None
    if snap.get('inspection_authorized'):
        from ai_edit_native_video import inspect
        stage(service,jid,'直读已授权视频和声音，建立素材地图')
        inspection=inspect(service,snap,owner,admin,jid)
        snap['inspection']=inspection
    stage(service,jid,'生成剪辑方案（A6API Gemini 3.8 Flash）')
    plan=service.plan(snap,owner,admin,jid)
    result={'analysis':analysis,'plan':plan,'plan_hash':digest(plan),'execution_status':'needs_review','execution_requirements':snap['requirements_version']}
    if inspection is not None:result.update(inspection=inspection,inspection_policy=INSPECTION_POLICY,review_status='not_started')
    from ai_edit_duration import diagnose, budget
    def keep_candidate(candidate,pass_no):
        service.cancelled(jid)
        with service.hub.db() as db:db.execute('INSERT INTO ai_edit_candidates VALUES(?,?,?)',(jid,pass_no,packed(candidate)))
    keep_candidate(plan,1)
    report=diagnose(plan,snap)
    report['issues']+=compliance(plan,snap)
    result['planning_passes']=1
    # The second request is a correction of a KNOWN response, never a retry of an unknown one.
    if report['issues'] and snap.get('duration_repair_authorized') is True and budget(snap)['source_capacity_seconds']>=snap['brief']['target']-max(.5,snap['brief']['target']*.1):
        stage(service,jid,'时长未达标，执行已授权的一次修正（2/2）')
        revised=service.plan({**snap,'plan':plan,'duration_repair':report},owner,admin,jid)
        keep_candidate(revised,2)
        plan=revised;report=diagnose(plan,snap);report['issues']+=compliance(plan,snap)
        result.update(plan=plan,plan_hash=digest(plan),planning_passes=2)
    result['duration_check']=report
    if report['issues']:
        result['execution_message']=f"目标 {snap['brief']['target']:g} 秒，当前候选 {plan['duration']:.2f} 秒。已完成 {result['planning_passes']} 次规划，尚未通过时长/重复区间校验，未导出。并非要求你降低目标：可补充素材或明确可用镜头后再确认；候选与诊断已保留。"
        return result
    if snap.get('inspection_authorized'):
        from ai_edit_vision import review
        stage(service,jid,'复核实际选段与确认要求')
        result['preflight_review']=review(service,{**snap,'plan':plan},owner,admin,jid)
        if result['preflight_review']['blocking_issues']:
            if result['planning_passes']==1 and snap.get('duration_repair_authorized'):
                stage(service,jid,'选段复核发现问题，使用唯一一次修正额度')
                correction={**report,'issues':result['preflight_review']['blocking_issues']}
                plan=service.plan({**snap,'plan':plan,'duration_repair':correction},owner,admin,jid)
                keep_candidate(plan,2)
                report=diagnose(plan,snap);report['issues']+=compliance(plan,snap)
                result.update(plan=plan,plan_hash=digest(plan),planning_passes=2,duration_check=report)
                if report['issues']:
                    result['execution_message']='选段复核后的修正仍未通过确定性检查，已暂停导出，候选已保存。'
                    return result
                result['execution_message']='已修正选段复核问题；实际成片仍需复查，不等于已全部通过。'
            else:
                result['execution_message']='选段复核发现明确不符合要求，修正额度已用完或未授权，已暂停导出。请查看复查记录。'
                return result
    stage(service,jid,'创建新工程并排队导出')
    result['_engine_body']=service.engine_body(plan,snap,owner,admin)
    result['execution_status']='export_queued'
    result['execution_message']='工程已创建，已排队导出；视频可用后才显示完成。'
    return result

def commit_execution(service,db,row,data,result):
    engine=result.pop('_engine_body',None)
    if engine is not None:
        eid=secrets.token_hex(12);export=secrets.token_hex(12);now=time.time()
        db.execute('INSERT INTO edit_projects VALUES(?,?,?,?,?,?)',(eid,row['owner'],row['title'] if 'title' in row.keys() else 'AI 对话剪辑',packed(engine),1,now))
        for shot in result['plan']['shots']:db.execute('INSERT OR IGNORE INTO project_tasks VALUES(?,?,?,?)',(eid,shot['source_id'],row['owner'],now))
        record_version(db,eid)
        db.execute('INSERT INTO ai_edit_applied VALUES(?,?,?,?) ON CONFLICT(owner,project_id,plan_hash) DO UPDATE SET edit_id=excluded.edit_id',(row['owner'],row['project_id'],result['plan_hash'],eid))
        engine['export_name']=data.get('brief',{}).get('product','AI剪辑')[:60]+'-AI剪辑'
        db.execute('INSERT INTO edit_exports(id,owner,project_id,body,state,created,updated,request_key) VALUES(?,?,?,?,?,?,?,?)',(export,row['owner'],eid,packed(engine),'queued',now,now,'ai-conversation-'+row['id']))
        result.update(edit_project_id=eid,export_id=export)
    if data.get('plan'):data['history']=(data.get('history',[])+[data['plan']])[-8:]
    data.update(result)

def attach(app,hub,user,body,service):
    initialize(hub)

    @app.post('/api/ai-edit/conversations')
    async def create(request:Request):
        u=user(request);data=await body(request);key=data.get('request_key')
        if not isinstance(key,str) or not 8<=len(key)<=100:raise HTTPException(400,'创建标识无效')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT project_id FROM ai_edit_creates WHERE owner=? AND request_key=?',(u['id'],key)).fetchone()
            if prior:row=service.owned(db,prior['project_id'],u['id'])
            else:
                pid=secrets.token_hex(12);now=time.time()
                content={'conversation':True,'sources':[],'brief':DEFAULT_BRIEF,'instructions':'','messages':[],'requirements_ready':False,'missing':[]}
                db.execute('INSERT INTO ai_edit_projects VALUES(?,?,?,?,?,?,?)',(pid,u['id'],'新对话剪辑',packed(content),1,now,now))
                db.execute('INSERT INTO ai_edit_creates VALUES(?,?,?,?)',(u['id'],key,pid,'conversation'))
                row=service.owned(db,pid,u['id'])
        return service.serialize(row,u['role']=='admin')

    @app.post('/api/ai-edit/projects/{pid}/conversation-sources')
    async def sources(pid:str,request:Request):
        u=user(request);incoming=await body(request)
        try:
            ids=incoming.get('sources')
            if ids!=[]:service.sources(ids,u['id'],u['role']=='admin')
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE');row=service.owned(db,pid,u['id'])
                if row['revision']!=incoming.get('revision'):raise HTTPException(409,'项目版本已更新，请重新载入')
                if db.execute("SELECT 1 FROM ai_edit_jobs WHERE project_id=? AND state IN ('queued','running','retry_wait')",(pid,)).fetchone():raise HTTPException(409,'任务中不能修改素材，请先等待或取消')
                content=json.loads(row['body']);changed=content.get('sources')!=ids;content['sources']=ids;content['conversation']=True
                if changed:
                    content['requirements_ready']=False
                    for key in ('analysis','plan','plan_hash','export_id','execution_status','execution_message','execution_requirements'):content.pop(key,None)
                    content['messages']=(content.get('messages',[])+[{'role':'assistant','text':'素材范围已更新。请确认新的素材是否仍按上述要求制作；最终确认前不会分析或生成。'}])[-40:]
                db.execute('UPDATE ai_edit_projects SET body=?,revision=revision+1,updated=? WHERE id=?',(packed(content),time.time(),pid))
                row=service.owned(db,pid,u['id'])
            return service.serialize(row,u['role']=='admin')
        except ValueError as exc:raise HTTPException(400,str(exc)) from None

    async def submit(pid,request,kind):
        u=user(request);incoming=await body(request);key=incoming.get('request_key')
        if not isinstance(key,str) or not 8<=len(key)<=100:raise HTTPException(400,'请求标识无效')
        try:
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE');row=service.owned(db,pid,u['id'])
                prior=db.execute('SELECT id,project_id,kind FROM ai_edit_jobs WHERE owner=? AND request_key=?',(u['id'],key)).fetchone()
                if prior:
                    if prior['project_id']!=pid or prior['kind']!=kind:raise HTTPException(409,'请求标识已用于其他操作')
                    return {'id':prior['id'],'reused':True}
                if incoming.get('revision')!=row['revision']:raise HTTPException(409,'需求版本已变化，请重新载入')
                if incoming.get('consent') is not True:raise HTTPException(400,'请确认此次模型调用及可能费用')
                if not asr.configured_key(hub):raise HTTPException(400,'请在 AI 助理设置中配置 A6API Gemini 3.8 Flash')
                if db.execute("SELECT 1 FROM ai_edit_jobs WHERE owner=? AND state IN ('queued','running','retry_wait')",(u['id'],)).fetchone():raise HTTPException(409,'已有任务进行中，请等待或取消')
                if db.execute("SELECT 1 FROM ai_edit_jobs WHERE owner=? AND state='unknown'",(u['id'],)).fetchone() and incoming.get('acknowledge_unknown') is not True:raise HTTPException(409,'存在结果未知的请求。先核对记录；确认新调用可能重复计费后再继续')
                content=json.loads(row['body']);snap={**content,'revision':row['revision']}
                snap['source_info']=service.sources(content['sources'],u['id'],u['role']=='admin') if content.get('sources') else []
                if kind=='discuss':
                    snap['require_general_contract']=incoming.get('general_requirements') is True
                    snap['message']=text(incoming.get('message',''),6000)
                    if not snap['message']:raise ValueError('请描述创作要求')
                    # Pending user turn is stored in job input for recovery and displayed separately.
                else:
                    if not content.get('requirements_ready') or not snap['source_info']:raise ValueError('请先在对话中补齐需求并选择素材')
                    clean_brief(content['brief'])
                    contract=clean_contract(content.get('contract'))
                    if blockers(contract):raise ValueError('需求仍含待确认/不支持或保真修改约束，不能执行')
                    if incoming.get('inspection_authorized') is True and incoming.get('inspection_policy')!=INSPECTION_POLICY:raise HTTPException(409,'素材理解规则已变化，请刷新确认卡')
                    if contract and incoming.get('inspection_authorized') is not True:raise ValueError('通用需求执行必须明确授权素材理解与成片复查')
                    snap['inspection_authorized']=incoming.get('inspection_authorized') is True
                    snap['inspection_policy']=INSPECTION_POLICY if snap['inspection_authorized'] else None
                    if incoming.get('duration_repair_authorized') is True and incoming.get('execution_policy')!=POLICY:raise HTTPException(409,'修正规则已变化，请刷新确认卡')
                    snap['duration_repair_authorized']=incoming.get('duration_repair_authorized') is True
                    snap['execution_policy']=POLICY
                    if confirmation(service,content,u['id'],u['role']=='admin')!=incoming.get('confirmation_hash'):raise HTTPException(409,'需求或素材发生变化，请重新阅读确认卡')
                    rv=content.get('requirements_version')
                    if content.get('execution_requirements')==rv and content.get('export_id'):
                        return {'id':content.get('execution_job_id',''),'reused':True}
                    if content.get('execution_status')=='needs_review' and content.get('execution_requirements')==rv:raise HTTPException(409,'上次方案未达标。请先对话调整需求，再次确认')
                    if contract:
                        from ai_edit_provenance import seal
                        snap['requirement_authority']=seal(content,incoming['confirmation_hash'],key)
                        content['requirement_authority']=snap['requirement_authority']
                jid=secrets.token_hex(12);now=time.time()
                db.execute('INSERT INTO ai_edit_jobs(id,owner,project_id,kind,request_key,input,state,stage,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,u['id'],pid,kind,key,packed(snap),'queued','等待整理需求' if kind=='discuss' else '等待执行',now,now))
                if kind=='execute':
                    if content.get('export_id'):
                        content['previous_results']=(content.get('previous_results',[])+[{'edit_project_id':content.get('edit_project_id'),'export_id':content['export_id'],'requirements_version':content.get('execution_requirements')}])[-8:]
                    for field in ('export_id','execution_status','execution_message','inspection','inspection_policy','review_status','final_review','preflight_review'):content.pop(field,None)
                    content['execution_job_id']=jid
                else:content['requirements_ready']=False
                db.execute('UPDATE ai_edit_projects SET body=? WHERE id=?',(packed(content),pid))
            return {'id':jid,'reused':False}
        except ValueError as exc:raise HTTPException(400,str(exc)) from None

    @app.post('/api/ai-edit/projects/{pid}/discuss')
    async def discuss(pid:str,request:Request):return await submit(pid,request,'discuss')

    @app.post('/api/ai-edit/projects/{pid}/execute')
    async def execute(pid:str,request:Request):return await submit(pid,request,'execute')
