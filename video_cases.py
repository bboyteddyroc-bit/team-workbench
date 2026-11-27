"""Shared video cases: immutable provenance, explicit processing consent, member-owned ideas.
Personal is a collection filter, NOT private storage. Explicit automatic-save consent queues paid work.
"""
import ipaddress
import json
import logging
import re
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urljoin, urlunsplit
import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from apify_submit_diagnostics import SubmissionTrace
import task_feedback as feedback

FEEDBACK_KINDS={'metadata':'case_metadata','kalodata':'case_metrics','analysis':'case_analysis','transcript':'case_transcript','ai':'case_text'}
PREFIX='/api/intelligence/cases'
HUMAN_FIELDS={'title':300,'summary':3000,'category':100,'content_type':100,'transcript':30000,'opening':3000,'audience_scenario':3000,'expression':6000,'ending':3000}
HUMAN_FIELDS.update({'category':300,'content_type':300,'event':300,'replicability':3000,'replication_actions':4000,'hook_example':3000,'hook_template':3000,'suitable_products':2000,'production_threshold':500,'prerequisites':3000,'notes':3000,'merchant_visible':100,'transcript_en':30000,'transcript_zh':30000,'publisher':300,'published_at':100,'manual_views':100,'manual_likes':100,'manual_comments':100,'manual_collects':100,'manual_shares':100,'manual_gmv':100,'manual_gmv_currency':10,'manual_metric_basis':300})
IDEA_FIELDS=('reason','borrow','adaptation','conditions','hypothesis','result','imitation','feedback','optimize','video_analysis','speech_analysis','product_fit','execution','suggestions')
ACTIVE=('queued','submitting','running','waiting')
TT_HOSTS={'www.tiktok.com','tiktok.com','m.tiktok.com','vm.tiktok.com','vt.tiktok.com'}


def normalize(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=2000:raise ValueError('请填写有效视频链接')
    value=value.strip();p=urlsplit(value)
    if p.scheme not in ('http','https') or p.username or p.password or p.port not in (None,80,443):raise ValueError('仅支持公开平台的 http/https 视频链接')
    host=(p.hostname or '').lower()
    if host in TT_HOSTS:
        match=re.fullmatch(r'/@([A-Za-z0-9._]{1,64})/video/(\d{5,25})/?',p.path)
        if match:
            handle,video=match.groups();handle=handle.lower()
            return {'key':'tiktok:'+video,'platform':'TikTok','video':video,'handle':handle,'url':f'https://www.tiktok.com/@{handle}/video/{video}'}
        if host in ('vm.tiktok.com','vt.tiktok.com') or re.fullmatch(r'/t/[A-Za-z0-9]+/?',p.path):
            raise ValueError('请先在浏览器打开短链接，复制包含 /@账号/video/视频ID 的完整链接')
        raise ValueError('请填写 TikTok 单条视频完整链接，不是账号主页')
    allowed={'www.youtube.com':'YouTube','youtube.com':'YouTube','youtu.be':'YouTube','www.instagram.com':'Instagram','instagram.com':'Instagram','www.douyin.com':'抖音','www.xiaohongshu.com':'小红书','www.bilibili.com':'Bilibili'}
    if host not in allowed or p.path in ('','/'):raise ValueError('当前支持 TikTok 完整链接；YouTube、Instagram、抖音、小红书、Bilibili 可先保存资料，暂不自动解析')
    canonical=urlunsplit(('https',host,p.path,p.query,''))
    return {'key':canonical,'platform':allowed[host],'video':'','handle':'','url':canonical}


def clean_fields(data,limits):
    if not isinstance(data,dict):raise HTTPException(400,'字段必须是对象')
    out={}
    for k,limit in limits.items():
        if k in data:
            if not isinstance(data[k],str) or len(data[k])>limit:raise HTTPException(400,'字段格式或长度不正确：'+k)
            out[k]=data[k].strip()
    if 'tags' in data:
        tags=data['tags']
        if not isinstance(tags,list) or len(tags)>20 or any(not isinstance(x,str) or not 1<=len(x.strip())<=30 for x in tags):raise HTTPException(400,'标签最多20个，每个1–30字')
        out['tags']=list(dict.fromkeys(x.strip() for x in tags))
    if 'tag_groups' in data:
        from video_case_presentation import validate_tag_groups
        try:out['tag_groups']=validate_tag_groups(data['tag_groups'])
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
    if 'manual_gmv_currency' in out and out['manual_gmv_currency'] and not re.fullmatch(r'[A-Z]{3}',out['manual_gmv_currency']):raise HTTPException(400,'GMV币种请填USD等三位大写代码')
    return out


def initialize(hub):
    with hub.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS video_cases(id TEXT PRIMARY KEY,canonical TEXT UNIQUE NOT NULL,platform TEXT NOT NULL,video TEXT NOT NULL,handle TEXT NOT NULL,url TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT '{}',human TEXT NOT NULL DEFAULT '{}',ai TEXT NOT NULL DEFAULT '{}',transcript TEXT NOT NULL DEFAULT '',transcript_source TEXT NOT NULL DEFAULT '',
          revision INTEGER NOT NULL DEFAULT 1,library_id TEXT,created_by TEXT NOT NULL,updated_by TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS video_case_members(case_id TEXT NOT NULL,owner TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(case_id,owner));
        CREATE TABLE IF NOT EXISTS video_case_ideas(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,owner TEXT NOT NULL,content TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,created REAL NOT NULL,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS video_case_clip_reviews(case_id TEXT NOT NULL,field TEXT NOT NULL,claim TEXT NOT NULL,start REAL NOT NULL,end REAL NOT NULL,reviewer TEXT NOT NULL, PRIMARY KEY(case_id,field));
        CREATE TABLE IF NOT EXISTS video_case_jobs(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,owner TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,request_key TEXT NOT NULL,
          remote_id TEXT,dataset TEXT,error TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(owner,request_key));
        CREATE UNIQUE INDEX IF NOT EXISTS video_case_one_job ON video_case_jobs(case_id,kind) WHERE state IN ('queued','submitting','running','waiting');
        CREATE TABLE IF NOT EXISTS video_case_task_links(task_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,idea_id TEXT,idea_snapshot TEXT NOT NULL);
        ''')
        db.execute('CREATE INDEX IF NOT EXISTS video_case_jobs_history ON video_case_jobs(case_id,created DESC)')
        db.execute('CREATE TABLE IF NOT EXISTS video_case_checkpoints(job TEXT PRIMARY KEY,stage TEXT NOT NULL,updated REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS video_case_reviews(case_id TEXT PRIMARY KEY,owner TEXT NOT NULL,reviewed REAL NOT NULL,ai_generated REAL NOT NULL DEFAULT 0)')
        if 'options' not in {r[1] for r in db.execute('PRAGMA table_info(video_case_jobs)')}:
            db.execute("ALTER TABLE video_case_jobs ADD COLUMN options TEXT NOT NULL DEFAULT '{}'")
        if 'removed_at' not in {r[1] for r in db.execute('PRAGMA table_info(video_cases)')}:
            db.execute('ALTER TABLE video_cases ADD COLUMN removed_at REAL')
        from video_case_recovery import initialize as recovery_schema
        recovery_schema(db)
        from video_case_weekly import initialize as weekly_schema
        weekly_schema(db)


def require_case(db,cid):
    r=db.execute('''SELECT c.* FROM video_cases c WHERE c.id=? AND c.removed_at IS NULL AND EXISTS
      (SELECT 1 FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=c.id)''',(cid,)).fetchone()
    if not r:raise HTTPException(404,'案例不存在或已从团队移除')
    return dict(r)


def reuse_local(db,row):
    """Only public/shared snapshots. Never copy owner-private Kalodata results."""
    if row['platform']!='TikTok':return
    snap=db.execute('''SELECT s.*,a.handle FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account
      JOIN users u ON u.id=a.owner AND u.enabled=1 WHERE s.video=? AND a.deleted_at IS NULL ORDER BY s.collected DESC LIMIT 1''',(row['video'],)).fetchone()
    if snap:
        source={k:snap[k] for k in ('title','published','cover','views','likes','comments','collects','shares','collected')}
        source.update(origin='账号监测快照',account=snap['account'])
        old=json.loads(row['source'])
        if (source['collected'] or 0)>=(old.get('collected') or 0):
            # Kalodata's selected-range estimates must not be overwritten by cumulative snapshots.
            if old.get('kalodata'):source['kalodata']=old['kalodata']
            if old.get('primary_provider')=='Kalodata':
                source['primary_provider']='Kalodata'
                if old.get('title'):source['title']=old['title']
            db.execute('UPDATE video_cases SET source=? WHERE id=?',(json.dumps(source,ensure_ascii=False),row['id']))
    lib=db.execute('SELECT * FROM script_library WHERE video=?',(row['video'],)).fetchone()
    if lib:
        db.execute('UPDATE video_cases SET library_id=? WHERE id=?',(lib['id'],row['id']))
        if not row['transcript'] and lib['transcript_original']:
            db.execute('UPDATE video_cases SET transcript=?,transcript_source=? WHERE id=?',(lib['transcript_original'],lib['transcript_source'] or '已有文案档案',row['id']))


def idea_reference(db,cid,iid):
    row=require_case(db,cid)
    idea=db.execute('''SELECT i.content,u.username FROM video_case_ideas i JOIN users u ON u.id=i.owner AND u.enabled=1 WHERE i.id=? AND i.case_id=?''',(iid,cid)).fetchone() if iid else None
    if iid and not idea:raise HTTPException(404,'成员想法不存在')
    human=json.loads(row['human']);ai=json.loads(row['ai']).get('fields',{});source=json.loads(row['source'])
    from video_case_fields import projection
    fields=projection({**row,'human':human,'source':source,'ai':json.loads(row['ai'])})
    reference={'video':row['video'],'description':source.get('title',''),'transcript_original':human.get('transcript') or row['transcript'],
      'transcript_source':'人工校对' if human.get('transcript') else row['transcript_source'],
      'product_category':human.get('category',ai.get('product_category','')),'tags':human.get('tags',ai.get('tags',[]))}
    for k in ('content_type','opening','audience_scenario','expression','ending'):reference[k]=human.get(k,ai.get(k,''))
    reference.update(description=fields['title']['value'],transcript_original=fields['transcript']['value'],product_category=fields['category']['value'])
    for k in ('content_type','opening','audience_scenario','expression','ending'):reference[k]=fields[k]['value']
    reference['field_sources']={k:v['source'] for k,v in fields.items() if not v['missing']}
    return {'case_id':cid,'url':row['url'],'idea_id':iid,'case_revision':row['revision'],'reference':reference,'member_idea':json.loads(idea['content']) if idea else {},'notice':'成员复用假设，未验证；不是新产品事实'}


class Cases:
    def __init__(self,hub,monitor,kalodata=None):self.hub,self.monitor,self.kalodata=hub,monitor,kalodata
    def recover(self):
        with self.hub.db() as db:
            db.execute("UPDATE video_case_jobs SET state='attention',error='进程中断，结果可能未知；未自动重试，请核对原记录',updated=? WHERE state='submitting' OR (state='running' AND (kind<>'metadata' OR remote_id IS NULL))",(time.time(),))
    def fail(self,jid,message,code=None):
        with self.hub.db() as db:db.execute("UPDATE video_case_jobs SET state='attention',error=?,error_code=?,next_attempt=NULL,updated=? WHERE id=?",(message[:600],str(code or '')[:40],time.time(),jid))
    def checkpoint(self,jid,stage):
        with self.hub.db() as db:db.execute('INSERT OR REPLACE INTO video_case_checkpoints(job,stage,updated) VALUES(?,?,?)',(jid,stage,time.time()))
    def analysis(self,job,case):
        import asr
        from video_case_analysis import prepare,request_native_video,clean,save_answer
        from script_board import save_evidence, vetted_components
        from video_consent import approved
        with feedback.step('ai_preflight','blocked'):
            if not approved(job.get('options','{}')):raise ValueError('旧任务没有授权发送完整视频和声音；请重新确认后发起新分析')
            key=asr.configured_key(self.hub)
            if not key:raise ValueError('未配置A6API Gemini 3.8 Flash；已保留Kalodata结果，未获取视频或调用AI')
        self.checkpoint(job['id'],'准备视频分析')
        prepared=prepare(self.hub,self.kalodata,case,job['id'],lambda stage:self.checkpoint(job['id'],stage))
        if prepared['transcript']:
            with self.hub.db() as db:
                db.execute("UPDATE video_cases SET transcript=?,transcript_source=? WHERE id=? AND length(trim(transcript))=0",(prepared['transcript'],prepared['transcript_source'],case['id']))
                if prepared.get('timing'):
                    save_evidence(db,'case',case['id'],prepared['transcript'],timing=prepared['timing'])
        source=json.loads(case['source']);human=json.loads(case['human'])
        from video_case_fields import projection,ai_plan
        projected={**case,'source':source,'human':human,'ai':json.loads(case['ai'])}
        projected['transcript']=prepared['transcript'] or case.get('transcript','')
        resolved=projection(projected);facts,missing_fields=ai_plan(projected)
        transcript=resolved['transcript']['value']
        title=resolved['title']['value']
        if not prepared['images'] and not transcript and not title:
            raise ValueError('没有可分析的画面、口播或标题；'+('; '.join(prepared['warnings'])[:400] or '请人工补充资料'))
        self.checkpoint(job['id'],'证据已就绪')
        context={'title':title,'kalodata':source.get('kalodata',{}),'transcript':transcript,'warnings':prepared['warnings'],'image_count':len(prepared['images']),'duration_seconds':prepared.get('duration_seconds'),'sampled_times':[round(at,3) for at,_ in prepared['images']],'authoritative_fields':facts,'missing_fields':missing_fields}
        answer_path=self.hub.directory/'case-analysis'/case['id']/(job['id']+'-answer.txt')
        video_path=prepared.get('native_video_path')
        if not video_path:
            # The media steps retain the underlying failure; this message explains why AI was not sent.
            raise ValueError('未取得可用完整视频，未发送 AI；请核对来源后处理')
        self.checkpoint(job['id'],'AI分析提交中；重启不重提')
        with feedback.step('ai_call'):
            raw=request_native_video(context,video_path,key,answer_path=answer_path,consent=True)
        with feedback.step('ai_validate'):
            save_answer(self.hub,case['id'],job['id'],raw)
            fields,evidence,uncertain=clean(raw,transcript,True,native_video=True)
        # Provider/human fields are not duplicated into the AI draft, even if the model ignores the plan.
        fields={k:v for k,v in fields.items() if k in missing_fields or k in ('tags','tag_groups')}
        evidence={k:v for k,v in evidence.items() if k in fields}
        fields.pop('merchant_visible',None)
        packed={'fields':fields,'evidence':evidence,'uncertainties':prepared['warnings']+uncertain,'generated_at':time.time(),'basis':'A6API Gemini 接收完整视频画面与音轨；模型理解与口播可能出错，需人工核实','policy':'case-review-v2'}
        with feedback.step('ai_save'), self.hub.db() as db:
            db.execute('UPDATE video_cases SET ai=?,updated=? WHERE id=?',(json.dumps(packed,ensure_ascii=False),time.time(),case['id']))
            if prepared['transcript']:db.execute("UPDATE video_cases SET transcript=?,transcript_source=? WHERE id=? AND length(trim(transcript))=0",(prepared['transcript'],prepared['transcript_source'],case['id']))
        self.checkpoint(job['id'],'AI初填完成，待人工审核')
    def tick(self,lane=None):
        if lane not in (None,'data','media'):raise ValueError('Invalid case lane')
        lane_clause=" AND j.kind='kalodata'" if lane=='data' else " AND j.kind<>'kalodata'" if lane=='media' else ''
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            r=db.execute('''SELECT j.* FROM video_case_jobs j JOIN users u ON u.id=j.owner AND u.enabled=1
              WHERE (j.state='queued' OR (j.state='waiting' AND j.next_attempt<=?) OR (j.state='running' AND j.kind='metadata' AND j.remote_id IS NOT NULL))'''+lane_clause+" ORDER BY CASE WHEN j.kind='kalodata' THEN 0 ELSE 1 END,j.updated LIMIT 1",(time.time(),)).fetchone()
            if not r:return
            job=dict(r);case=dict(db.execute('SELECT * FROM video_cases WHERE id=?',(job['case_id'],)).fetchone())
            if job['state']=='waiting':
                if time.time()>=(job['wait_deadline'] or 0):
                    from video_case_recovery import defer
                    defer(db,job['id']);return
                job['state']='queued'
            if job['state']=='queued':db.execute("UPDATE video_case_jobs SET state='submitting',updated=? WHERE id=?",(time.time(),job['id']))
        with feedback.bound(self.hub,FEEDBACK_KINDS.get(job['kind']),job['id']):
            self.process(job,case)

    def process(self,job,case):
        try:
            if job['kind']=='metadata':self.metadata(job,case)
            else:
                with self.hub.db() as db:db.execute("UPDATE video_case_jobs SET state='running',updated=? WHERE id=?",(time.time(),job['id']))
                if job['kind']=='kalodata':
                    from video_case_kalodata import fetch as fetch_kalodata
                    self.checkpoint(job['id'],'按视频ID获取平台指标；不等待视频下载与AI')
                    with feedback.step('case_metrics'):
                        result=fetch_kalodata(self.kalodata,case,json.loads(job['options']))
                    with feedback.step('data_save'), self.hub.db() as db:
                        # Merge into the latest source after the external call, preserving concurrent updates.
                        latest=json.loads(db.execute('SELECT source FROM video_cases WHERE id=?',(case['id'],)).fetchone()[0])
                        latest['kalodata']=result;latest['primary_provider']='Kalodata'
                        if result['title']:latest['title']=result['title']
                        db.execute('UPDATE video_cases SET source=?,updated=? WHERE id=?',(json.dumps(latest,ensure_ascii=False,allow_nan=False),time.time(),case['id']))
                        if json.loads(job['options']).get('auto_analysis'):
                            child=uuid.uuid4().hex;now=time.time()
                            db.execute("INSERT OR IGNORE INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'analysis','queued',?,?,?,?)",(child,case['id'],job['owner'],'auto-analysis:'+job['id'],now,now,json.dumps(__import__('video_consent').from_parent(job['options'],job['id']))))
                elif job['kind']=='analysis':self.analysis(job,case)
                elif job['kind']=='transcript':
                    from script_automation import transcribe
                    from script_board import save_evidence
                    with feedback.step('transcript'):
                        text,source,*timing=transcribe(case['handle'],case['video'],timing=True)
                    with feedback.step('data_save'), self.hub.db() as db:
                        db.execute('UPDATE video_cases SET transcript=?,transcript_source=?,updated=? WHERE id=?',(text,source,time.time(),case['id']))
                        if timing:
                            save_evidence(db,'case',case['id'],text,timing=timing[0])
                elif job['kind']=='ai':
                    import asr
                    from script_enrichment import request_enrichment
                    human=json.loads(case['human']);source=json.loads(case['source']);text=human.get('transcript') or case['transcript'] or source.get('title','')
                    from video_case_fields import projection,ai_plan
                    resolved_row={**case,'source':source,'human':human,'ai':json.loads(case['ai'])}
                    resolved=projection(resolved_row);_,missing_fields=ai_plan(resolved_row)
                    text=resolved['transcript']['value'] or resolved['title']['value']
                    with feedback.step('ai_preflight','blocked'):
                        key=asr.configured_key(self.hub)
                        if not key:raise ValueError('未配置 A6API Gemini 3.8 Flash 服务')
                    with feedback.step('ai_call'):
                        result=request_enrichment(text,resolved['title']['value'],key)
                    components=result.pop('components',[])
                    result['summary']=result.get('expression','') or source.get('title','')[:300]
                    result['basis']='文字分析：逐字稿与发布文案；未分析画面，推断需人工核对' if (human.get('transcript') or case['transcript']) else '仅发布文案分析；未获得逐字稿，不代表真实口播或画面'
                    # Description-only text must not masquerade as a spoken transcript.
                    if not (human.get('transcript') or case['transcript']):result.pop('transcript_en',None);result.pop('transcript_zh',None)
                    result={k:v for k,v in result.items() if k in missing_fields or k in ('tags','tag_groups','basis')}
                    with feedback.step('ai_save'), self.hub.db() as db:
                        db.execute('UPDATE video_cases SET ai=?,updated=? WHERE id=?',(json.dumps({'fields':result,'generated_at':time.time()},ensure_ascii=False),time.time(),case['id']))
                        if resolved['transcript']['value'] and components:
                            from script_board import save_evidence
                            save_evidence(db,'case',case['id'],text,components=components)
                with feedback.step('save_task'), self.hub.db() as db:
                    db.execute("UPDATE video_case_jobs SET state='ready',error='',error_code='',next_attempt=NULL,updated=? WHERE id=?",(time.time(),job['id']))
        except Exception as exc:
            from exception_center import safe_error
            from kalodata_integration import QueryError
            msg=safe_error(str(exc)) if isinstance(exc,(ValueError,QueryError)) else '处理失败或结果未知，请核对原任务；未自动重试'
            if isinstance(exc,QueryError) and exc.waiting_media and job['kind']=='analysis':
                from video_case_recovery import defer
                with self.hub.db() as db:defer(db,job['id'])
                self.checkpoint(job['id'],'等待供应商视频缓存')
                return
            if job['kind']=='metadata' and json.loads(job['options']).get('auto_analysis'):
                with self.hub.db() as db:
                    now=time.time()
                    db.execute("UPDATE video_case_jobs SET state='attention',error=?,error_code=?,next_attempt=NULL,updated=? WHERE id=?",(msg[:600],str((exc.code or exc.reason) if isinstance(exc,QueryError) else '')[:40],now,job['id']))
                    db.execute("INSERT OR IGNORE INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'analysis','queued',?,?,?,?)",(uuid.uuid4().hex,case['id'],job['owner'],'auto-analysis:'+job['id'],now,now,json.dumps(__import__('video_consent').from_parent(job['options'],job['id']))))
            else:
                self.fail(job['id'],msg,(exc.code or exc.reason) if isinstance(exc,QueryError) else None)
            # Media analysis is a separate operation, not a retry of a failed data query.
            if job['kind']=='kalodata' and json.loads(job['options']).get('auto_analysis'):
                with self.hub.db() as db:
                    now=time.time();child=uuid.uuid4().hex
                    db.execute("INSERT OR IGNORE INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'analysis','queued',?,?,?,?)",(child,case['id'],job['owner'],'auto-analysis:'+job['id'],now,now,json.dumps({**__import__('video_consent').from_parent(job['options'],job['id']),'metadata_failed':True})))
    def queue_analysis(self,job,case):
        with self.hub.db() as db:
            now=time.time()
            db.execute("INSERT OR IGNORE INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'analysis','queued',?,?,?,?)",(uuid.uuid4().hex,case['id'],job['owner'],'auto-analysis:'+job['id'],now,now,json.dumps(__import__('video_consent').from_parent(job['options'],job['id']))))
    def metadata(self,job,case):
        binding='case:'+job['id']
        if job['state']=='queued':
            # Bind once before submission; never rotate an unknown submission.
            with feedback.step('apify_submit','unknown'), SubmissionTrace(self.hub.directory,binding) as trace:
                data=self.monitor.submit_actor(trace,params={'timeout':300,'maxItems':1,'maxTotalChargeUsd':2},json={'postURLs':[case['url']],'shouldDownloadVideos':False,'shouldDownloadCovers':False,'aiVideoDescription':False,'aiVideoSummary':False})
                rid=data.get('id');dataset=data.get('defaultDatasetId')
                if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9]{5,100}',rid):raise ValueError('采集提交结果无法识别；未重试，请核对 Apify 控制台')
                trace.received_run_id()
                with self.hub.db() as db:
                    changed=db.execute("UPDATE video_case_jobs SET remote_id=?,dataset=?,state='running',updated=? WHERE id=?",(rid,dataset,time.time(),job['id']))
                    if changed.rowcount!=1:raise RuntimeError('Apify case job row not updated')
                trace.saved()
            return
        if not re.fullmatch(r'[A-Za-z0-9]{5,100}',job['remote_id'] or ''):raise ValueError('远程任务编号无效')
        # Historical jobs have no pool binding and used the old direct credential.
        with self.hub.db() as db:bound=bool(db.execute('SELECT 1 FROM apify_key_bindings WHERE run=?',(binding,)).fetchone())
        pool_args={'_pool_run':binding} if bound else {}
        with feedback.step('apify_poll') as attempt:
            data=self.monitor.request('GET','/actor-runs/'+job['remote_id'],**pool_args)['data'];state=data.get('status')
            if state in ('READY','RUNNING','TIMING-OUT','ABORTING'):attempt.mark('waiting')
            elif state in ('FAILED','ABORTED','TIMED-OUT'):attempt.mark('failed')
        with self.hub.db() as db:db.execute('UPDATE video_case_jobs SET updated=? WHERE id=?',(time.time(),job['id']))
        if state in ('READY','RUNNING','TIMING-OUT','ABORTING'):return
        if state!='SUCCEEDED':raise ValueError('Apify 任务未成功（'+(state if state in ('FAILED','ABORTED','TIMED-OUT') else '状态未识别')+'）；未重新提交')
        with feedback.step('apify_dataset'):
            dataset=data.get('defaultDatasetId') or job['dataset']
            if not isinstance(dataset,str) or not re.fullmatch(r'[A-Za-z0-9]{5,100}',dataset):raise ValueError('数据集编号无效')
            items=self.monitor.request('GET','/datasets/'+dataset+'/items',params={'clean':'true','limit':10},**pool_args)
            if not isinstance(items,list):raise ValueError('视频数据格式无效')
            item=next((i for i in items if isinstance(i,dict) and str(i.get('id'))==case['video']),None)
            if not item:raise ValueError('未返回目标视频；可能下架、私密或受平台限制，不替换为其他视频')
        from apify_monitor import cover_url
        def num(k):
            v=item.get(k)
            return v if type(v) in (int,float) and 0<=v<1e15 else None
        meta=item.get('videoMeta') or {}
        source={'origin':'Apify 单视频采集','title':str(item.get('text') or '')[:10000],'published':num('createTime'),'cover':cover_url(item),'duration':meta.get('duration') if type(meta.get('duration')) in (int,float) else None,'collected':time.time()}
        source.update({k:num(v) for k,v in {'views':'playCount','likes':'diggCount','comments':'commentCount','collects':'collectCount','shares':'shareCount'}.items()})
        with self.hub.db() as db:
            latest=json.loads(db.execute('SELECT source FROM video_cases WHERE id=?',(case['id'],)).fetchone()[0])
            from product_intel import products, record
            for product in products(item):
                record(db,case['video'],case['handle'],product,'Apify')
            if not db.execute('SELECT 1 FROM intel_goods_video WHERE video=?',(case['video'],)).fetchone():
                from product_intel import enqueue
                enqueue(db,'video',case['video'])
            if latest.get('kalodata'):
                source['kalodata']=latest['kalodata'];source['primary_provider']='Kalodata'
            db.execute('UPDATE video_cases SET source=?,updated=? WHERE id=?',(json.dumps(source,ensure_ascii=False),time.time(),case['id']))
            db.execute("UPDATE video_case_jobs SET state='ready',error='',error_code='',next_attempt=NULL,updated=? WHERE id=?",(time.time(),job['id']))
            if json.loads(job['options']).get('auto_analysis'):
                now=time.time()
                db.execute("INSERT OR IGNORE INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'analysis','queued',?,?,?,?)",(uuid.uuid4().hex,case['id'],job['owner'],'auto-analysis:'+job['id'],now,now,json.dumps(__import__('video_consent').from_parent(job['options'],job['id']))))
    def data_loop(self):
        # Separate single serial data lane: slow media/ASR/AI cannot block the next link's metrics.
        # 1 request at a time, <=1 new request/second; no retries/paid call in GET handlers.
        while not self.hub.stop.is_set():
            try:
                from video_case_weekly import dispatch
                dispatch(self.hub)
                self.tick('data')
            except Exception:logging.getLogger(__name__).exception('案例数据快通道检查失败')
            self.hub.stop.wait(1)
    def loop(self):
        while not self.hub.stop.is_set():
            try:self.tick('media')
            except Exception:logging.getLogger(__name__).exception('案例处理检查失败')
            self.hub.stop.wait(5)


def attach(app,hub,user,body):
    initialize(hub);service=Cases(hub,app.state.apify_monitor,app.state.kalodata);app.state.video_cases=service
    def detail(db,cid,uid,summary=None):
        row=require_case(db,cid) if summary is None else summary['rows'][cid]
        for k in ('source','human','ai'):row[k]=json.loads(row[k])
        if summary is None:
            row['has_preview']=(hub.directory/'case-analysis'/cid/'source.mp4').is_file()
            row['mine']=bool(db.execute('SELECT 1 FROM video_case_members WHERE case_id=? AND owner=?',(cid,uid)).fetchone())
            row['collectors']=[dict(r) for r in db.execute('SELECT u.username,m.created FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=? ORDER BY m.created',(cid,))]
            row['ideas']=[]
            for r in db.execute('SELECT i.*,u.username FROM video_case_ideas i JOIN users u ON u.id=i.owner AND u.enabled=1 WHERE case_id=? ORDER BY i.created',(cid,)):
                i=dict(r);i['content']=json.loads(i['content']);i['is_owner']=i.pop('owner')==uid;row['ideas'].append(i)
            row['jobs']=[dict(r) for r in db.execute('SELECT id,kind,state,error,owner,created,updated,wait_count,next_attempt,wait_deadline,error_code FROM video_case_jobs WHERE case_id=? ORDER BY created DESC LIMIT 30',(cid,))]
            for j in row['jobs']:
                j['is_owner']=j.pop('owner')==uid
                checkpoint=db.execute('SELECT stage FROM video_case_checkpoints WHERE job=?',(j['id'],)).fetchone()
                j['stage']=checkpoint[0] if checkpoint else ''
            review=db.execute('SELECT reviewed,ai_generated FROM video_case_reviews WHERE case_id=?',(cid,)).fetchone()
        else:
            row['mine']=cid in summary['mine'];row['collectors']=summary['collectors'].get(cid,[])
            row['idea_count']=summary['ideas'].get(cid,0);row['task_count']=summary['tasks'].get(cid,0)
            row['jobs']=summary['jobs'].get(cid,[]);review=summary['reviews'].get(cid)
        row['can_remove']=row['created_by']==uid
        row.pop('removed_at',None)
        generated=row['ai'].get('generated_at',0)
        substantive=any(v for k,v in row['ai'].get('fields',{}).items() if k not in ('notes','tags','tag_groups','basis'))
        row['review_status']='数据不足' if generated and not substantive else '已审核' if review and review['reviewed']>=row['updated'] and review['ai_generated']>=generated else '待审核' if generated else '待分析'
        from video_case_presentation import metric_projection,tag_projection,TAG_CATEGORIES
        from video_case_fields import projection
        row['fields']=projection(row)
        if summary is None:
            row['clip_reviews']={v['field']:dict(v) for v in db.execute('SELECT field,claim,start,end FROM video_case_clip_reviews WHERE case_id=?',(cid,)) if row['fields'].get(v['field'],{}).get('value')==v['claim']}
        from video_case_commercial import projection as commercial_projection
        from video_case_data_status import projection as data_status
        if summary is None:row['commercial']=commercial_projection(row)
        row['data_status']=data_status(row)
        row['metrics']=metric_projection(row);row['tagging']=tag_projection(row);row['tag_categories']=TAG_CATEGORIES
        row['case_number']='VC-'+cid[:8].upper()
        if summary is None:row['tasks']=[dict(r) for r in db.execute('SELECT t.id,t.title,t.state,n.number FROM video_case_task_links l JOIN script_creative_tasks t ON t.id=l.task_id LEFT JOIN script_creative_numbers n ON n.task_id=t.id WHERE l.case_id=? ORDER BY t.created DESC',(cid,))]
        row['cover_url']=PREFIX+'/'+cid+'/cover' if row['source'].get('cover') or (hub.directory/'case-covers'/(cid+'.img')).is_file() else None
        row.pop('canonical',None);row.pop('created_by',None);row.pop('updated_by',None)
        return row
    @app.get(PREFIX)
    def listing(request:Request,scope:str='team',q:str='',offset:int=0,limit:int=48):
        u=user(request)
        if scope not in ('team','mine') or offset<0 or not 1<=limit<=100 or len(q)>200:raise HTTPException(400,'筛选参数无效')
        with hub.db() as db:
            where="c.removed_at IS NULL AND EXISTS (SELECT 1 FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=c.id)";params=[]
            if scope=='mine':where+=' AND (EXISTS (SELECT 1 FROM video_case_members m WHERE m.case_id=c.id AND m.owner=?) OR EXISTS (SELECT 1 FROM video_case_ideas i WHERE i.case_id=c.id AND i.owner=?))';params.extend([u['id'],u['id']])
            if q:
                where+=" AND (c.human LIKE ? OR c.source LIKE ? OR c.ai LIKE ? OR c.handle LIKE ? OR c.url LIKE ? OR EXISTS (SELECT 1 FROM video_case_ideas i JOIN users iu ON iu.id=i.owner AND iu.enabled=1 WHERE i.case_id=c.id AND i.content LIKE ?))";params.extend(['%'+q+'%']*6)
            total=db.execute('SELECT COUNT(*) FROM video_cases c WHERE '+where,params).fetchone()[0]
            ids=[r[0] for r in db.execute('SELECT c.id FROM video_cases c WHERE '+where+' ORDER BY c.updated DESC,c.id LIMIT ? OFFSET ?',(*params,limit,offset))]
            # Bound all related reads to the selected page; preserve detail semantics.
            summary={'rows':{},'mine':set(),'collectors':{},'ideas':{},'tasks':{},'jobs':{},'reviews':{}}
            if ids:
                marks=','.join('?' for _ in ids)
                summary['rows']={r['id']:dict(r) for r in db.execute(f'SELECT * FROM video_cases WHERE id IN ({marks})',ids)}
                for r in db.execute(f'SELECT m.case_id,m.owner,u.username,m.created,u.enabled FROM video_case_members m JOIN users u ON u.id=m.owner WHERE m.case_id IN ({marks}) ORDER BY m.created',ids):
                    if r['owner']==u['id']:summary['mine'].add(r['case_id'])
                    if r['enabled']:summary['collectors'].setdefault(r['case_id'],[]).append({'username':r['username'],'created':r['created']})
                summary['ideas']={r['case_id']:r['n'] for r in db.execute(f'SELECT i.case_id,COUNT(*) n FROM video_case_ideas i JOIN users u ON u.id=i.owner AND u.enabled=1 WHERE i.case_id IN ({marks}) GROUP BY i.case_id',ids)}
                summary['tasks']={r['case_id']:r['n'] for r in db.execute(f'SELECT l.case_id,COUNT(*) n FROM video_case_task_links l JOIN script_creative_tasks t ON t.id=l.task_id LEFT JOIN script_creative_numbers n ON n.task_id=t.id WHERE l.case_id IN ({marks}) GROUP BY l.case_id',ids)}
                summary['reviews']={r['case_id']:r for r in db.execute(f'SELECT case_id,reviewed,ai_generated FROM video_case_reviews WHERE case_id IN ({marks})',ids)}
                # A case's latest Kalodata job might fall below the first three displayed jobs.
                for cid in ids:
                    # Per-case indexed LIMIT stops at 30 instead of transferring every historical row.
                    rows=db.execute('''SELECT j.id,j.kind,j.state,j.error,j.owner,j.created,j.updated,j.wait_count,j.next_attempt,j.wait_deadline,j.error_code,c.stage FROM video_case_jobs j LEFT JOIN video_case_checkpoints c ON c.job=j.id WHERE j.case_id=? ORDER BY j.created DESC LIMIT 30''',(cid,))
                    jobs=summary['jobs'].setdefault(cid,[])
                    for r in rows:
                        j=dict(r);j['is_owner']=j.pop('owner')==u['id'];j['stage']=j['stage'] or '';jobs.append(j)
            items=[]
            for cid in ids:
                row=detail(db,cid,u['id'],summary);row['latest_jobs']=row.pop('jobs');row.pop('transcript');row['ai'].get('fields',{}).pop('transcript_en',None);row['ai'].get('fields',{}).pop('transcript_zh',None);row['human'].pop('transcript',None)
                for key in ('transcript','transcript_en','transcript_zh'):
                    row['fields'].pop(key,None);row['human'].pop(key,None);row['ai'].get('fields',{}).pop(key,None)
                row.pop('commercial',None);items.append(row)
        return {'items':items,'total':total,'offset':offset,'limit':limit,'scope':scope}
    @app.post(PREFIX)
    async def add(request:Request):
        u=user(request);data=await body(request);urls=data.get('urls')
        if not isinstance(urls,list) or not 1<=len(urls)<=100:raise HTTPException(400,'每次添加1–100条链接')
        try:values=[normalize(v) for v in urls]
        except (ValueError,TypeError):raise HTTPException(400,'链接无效。TikTok 请使用含 /@账号/video/视频ID 的完整链接；其他已支持平台仅保存资料') from None
        automatic=data.get('auto_process',False)
        if type(automatic) is not bool:raise HTTPException(400,'自动处理参数无效')
        if automatic and (data.get('confirm_automation') is not True or data.get('share_with_team') is not True):raise HTTPException(400,'请确认Apify、每周一次Kalodata、视频下载、AI分析费用及团队共享')
        from video_consent import approved
        if automatic and not approved(data):raise HTTPException(400,'请明确确认发送完整视频和声音至 A6API')
        reason=data.get('reason','')
        if not isinstance(reason,str) or len(reason)>3000:raise HTTPException(400,'收藏理由最多3000字')
        result=[]
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for v in values:
                row=db.execute('SELECT * FROM video_cases WHERE canonical=?',(v['key'],)).fetchone();existing=bool(row);now=time.time()
                if not row:
                    cid=uuid.uuid4().hex
                    db.execute('INSERT INTO video_cases(id,canonical,platform,video,handle,url,created_by,updated_by,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,v['key'],v['platform'],v['video'],v['handle'],v['url'],u['id'],u['id'],now,now))
                    row=db.execute('SELECT * FROM video_cases WHERE id=?',(cid,)).fetchone()
                if row['removed_at'] is not None:
                    raise HTTPException(409,'该视频案例已从团队移除，请联系原添加人处理，未重新采集')
                cid=row['id'];added=db.execute('INSERT OR IGNORE INTO video_case_members VALUES(?,?,?)',(cid,u['id'],now)).rowcount
                reuse_local(db,dict(row))
                if reason.strip() and added:db.execute('INSERT INTO video_case_ideas VALUES(?,?,?,?,1,?,?)',(uuid.uuid4().hex,cid,u['id'],json.dumps({'reason':reason.strip()},ensure_ascii=False),now,now))
                queued=False
                if automatic and not existing and v['platform']=='TikTok':
                    from video_case_weekly import enroll
                    waiting=db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE kind IN ('metadata','analysis') AND state IN ('queued','submitting','running','waiting')").fetchone()[0]
                    daily=db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE kind='metadata' AND owner=? AND created>?",(u['id'],now-86400)).fetchone()[0]
                    from video_consent import POLICY
                    jid=uuid.uuid4().hex;options={'auto_analysis':True,'native_video_consent':True,'native_video_policy':POLICY};error='';state='queued'
                    if waiting>=100 or daily>=100:state='attention';error='自动处理达到安全队列上限，链接已保存；请稍后主动处理'
                    db.execute('INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options,error) VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,cid,u['id'],'metadata',state,'auto-case:'+cid,now,now,json.dumps(options),error))
                    enroll(db,cid,u['id'],now)
                    queued=state=='queued'
                if not existing and v['platform']=='TikTok' and getattr(hub,'comment_samples_ready',False):
                    from comment_samples import enqueue as enqueue_comments
                    enqueue_comments(db,v['video'],v['handle'],'case',now)
                result.append({'id':cid,'existing':existing,'auto_queued':queued})
            hub.log(db,u['id'],'video_cases_added',str(len(result)))
        return {'items':result,'notice':'已保存；Apify单视频采集及AI分析后台处理；每周五北京时间08:00对新增案例查询一次Kalodata。重复案例不重跑。' if automatic else '已保存；评论按团队采集设置处理'}
    @app.get(PREFIX+'/{cid}')
    def get(cid:str,request:Request):
        u=user(request)
        with hub.db() as db:return detail(db,cid,u['id'])
    @app.post(PREFIX+'/{cid}')
    async def edit(cid:str,request:Request):
        u=user(request);data=await body(request);updates=clean_fields(data.get('fields',{}),HUMAN_FIELDS)
        if not updates:raise HTTPException(400,'没有可保存内容')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');r=require_case(db,cid)
            if data.get('revision')!=r['revision']:raise HTTPException(409,'资料已被其他成员更新，请重新打开后再保存')
            fields=json.loads(r['human']);fields.update(updates)
            db.execute('UPDATE video_cases SET human=?,revision=revision+1,updated_by=?,updated=? WHERE id=?',(json.dumps(fields,ensure_ascii=False),u['id'],time.time(),cid))
        return {'ok':True}
    @app.post(PREFIX+'/{cid}/clip-review')
    async def review_clip(cid:str,request:Request):
        import math
        import subprocess
        u=user(request);data=await body(request)
        field=data.get('field');start=data.get('start');end=data.get('end')
        if field not in ('summary','opening','expression','ending','replication_actions') or not all(type(v) in (int,float) and math.isfinite(v) for v in (start,end)) or not 0<=start<end<=1200:
            raise HTTPException(400,'请设置有效的片段起止时间')
        with hub.db() as db:require_case(db,cid)
        path=hub.directory/'case-analysis'/cid/'source.mp4'
        try:
            duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(path)],timeout=8))
        except (OSError,ValueError,subprocess.SubprocessError):
            raise HTTPException(409,'原片不可用，无法核对时间范围') from None
        if end>duration+0.001:raise HTTPException(400,'结束时间超过原片时长')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=detail(db,cid,u['id'])
            claim=row['fields'][field]['value']
            if not claim or claim!=data.get('claim') or row['revision']!=data.get('revision'):raise HTTPException(409,'案例已更新，请重新打开')
            db.execute('INSERT OR REPLACE INTO video_case_clip_reviews VALUES(?,?,?,?,?,?)',(cid,field,claim,start,end,u['id']))
            db.execute('UPDATE video_cases SET revision=revision+1 WHERE id=?',(cid,))
        return {'revision':row['revision']+1}
    @app.post(PREFIX+'/{cid}/review')
    async def review(cid:str,request:Request):
        u=user(request);data=await body(request)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');row=require_case(db,cid)
            generated=json.loads(row['ai']).get('generated_at',0)
            if row['revision']!=data.get('revision') or generated!=data.get('ai_generated'):raise HTTPException(409,'详情或AI结果已更新，请重新审核')
            fields=json.loads(row['ai']).get('fields',{})
            if not generated or not any(v for k,v in fields.items() if k not in ('notes','tags','tag_groups','basis')):raise HTTPException(400,'尚无有效AI初填结果或数据不足，不能标为已审核')
            db.execute('INSERT OR REPLACE INTO video_case_reviews VALUES(?,?,?,?)',(cid,u['id'],time.time(),generated))
        return {'ok':True}
    @app.post(PREFIX+'/{cid}/remove')
    async def remove_case(cid:str,request:Request):
        u=user(request);data=await body(request)
        if data.get('confirm') is not True:raise HTTPException(400,'请确认从团队案例库移除')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');row=require_case(db,cid)
            if row['created_by']!=u['id']:raise HTTPException(403,'只能移除自己添加的视频案例')
            if db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND state IN ('submitting','running')",(cid,)).fetchone():raise HTTPException(409,'案例任务正在执行，请等待结束后再移除')
            now=time.time()
            db.execute("UPDATE video_case_jobs SET state='cancelled',error='案例已移除，未执行的任务已取消',next_attempt=NULL,updated=? WHERE case_id=? AND state IN ('queued','waiting')",(now,cid))
            db.execute("UPDATE video_case_weekly_enrollment SET state='skipped' WHERE case_id=? AND state='pending'",(cid,))
            db.execute('UPDATE video_cases SET removed_at=?,updated=? WHERE id=?',(now,now,cid))
            hub.log(db,u['id'],'video_case_removed',cid)
        return {'ok':True}
    @app.post(PREFIX+'/{cid}/collect')
    async def collect(cid:str,request:Request):
        u=user(request);data=await body(request)
        if type(data.get('saved')) is not bool:raise HTTPException(400,'收藏参数无效')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');require_case(db,cid)
            if data['saved']:db.execute('INSERT OR IGNORE INTO video_case_members VALUES(?,?,?)',(cid,u['id'],time.time()))
            else:db.execute('DELETE FROM video_case_members WHERE case_id=? AND owner=?',(cid,u['id']))
        return {'ok':True}
    @app.post(PREFIX+'/{cid}/ideas')
    async def idea(cid:str,request:Request):
        u=user(request);data=await body(request);fields=clean_fields(data.get('fields',{}),dict.fromkeys(IDEA_FIELDS,6000))
        if not any(fields.values()):raise HTTPException(400,'请至少填写一项想法')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');require_case(db,cid);now=time.time();iid=data.get('id')
            if iid:
                old=db.execute('SELECT * FROM video_case_ideas WHERE id=? AND case_id=? AND owner=?',(iid,cid,u['id'])).fetchone()
                if not old:raise HTTPException(404,'只能修改自己的想法')
                if data.get('revision')!=old['revision']:raise HTTPException(409,'想法已更新，请重新打开')
                db.execute('UPDATE video_case_ideas SET content=?,revision=revision+1,updated=? WHERE id=?',(json.dumps(fields,ensure_ascii=False),now,iid))
            else:
                iid=uuid.uuid4().hex;db.execute('INSERT INTO video_case_ideas VALUES(?,?,?,?,1,?,?)',(iid,cid,u['id'],json.dumps(fields,ensure_ascii=False),now,now))
            db.execute('INSERT OR IGNORE INTO video_case_members VALUES(?,?,?)',(cid,u['id'],now))
            db.execute('UPDATE video_cases SET updated=? WHERE id=?',(now,cid))
        return {'id':iid}
    @app.post(PREFIX+'/{cid}/process')
    async def process(cid:str,request:Request):
        u=user(request);data=await body(request);kind=data.get('kind');key=data.get('request_key')
        if kind not in ('metadata','kalodata','analysis','transcript','ai') or not isinstance(key,str) or not 8<=len(key)<=100:raise HTTPException(400,'处理参数无效')
        if data.get('confirm') is not True:raise HTTPException(400,'请确认费用、下载与发送数据范围')
        options={}
        if kind=='analysis':
            from video_consent import approved,POLICY
            if not approved(data):raise HTTPException(400,'请明确确认发送完整视频和声音至 A6API')
            options={'native_video_consent':True,'native_video_policy':POLICY}
        if kind=='kalodata':
            from video_case_kalodata import period
            days=data.get('days',30)
            if type(days) is not int or days not in (7,30):raise HTTPException(400,'仅支持近7或30个完整自然日')
            if data.get('share_with_team') is not True:raise HTTPException(400,'请确认本次新查询结果在案例库向团队共享；不读取私人查询历史')
            options=period(days)
            if data.get('auto_analysis') is True:
                from video_consent import approved,POLICY
                if not approved(data):raise HTTPException(400,'自动分析需确认发送完整视频和声音至 A6API')
                options.update(auto_analysis=True,native_video_consent=True,native_video_policy=POLICY)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');row=require_case(db,cid)
            old=db.execute('SELECT * FROM video_case_jobs WHERE owner=? AND request_key=?',(u['id'],key)).fetchone()
            if old:
                old_options=json.loads(old['options'])
                if old['case_id']!=cid or old['kind']!=kind or (kind=='kalodata' and (old_options.get('days')!=options['days'] or bool(old_options.get('auto_analysis'))!=bool(options.get('auto_analysis')))) or (kind=='analysis' and not __import__('video_consent').approved(old_options)):raise HTTPException(409,'请求标识冲突')
                return {'id':old['id'],'state':old['state']}
            active=db.execute("SELECT id,state FROM video_case_jobs WHERE case_id=? AND kind=? AND state IN ('queued','submitting','running','waiting')",(cid,kind)).fetchone()
            if active:return dict(active)
            previous=db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND kind=? AND state='attention'",(cid,kind)).fetchone()
            if previous and data.get('acknowledge_unknown') is not True:raise HTTPException(409,'存在需核对记录；请先核对，确认新请求可能重复计费')
            if kind in ('metadata','kalodata','analysis','transcript') and row['platform']!='TikTok':raise HTTPException(400,'当前仅支持 TikTok 资料调取与口播提取')
            if kind=='kalodata':
                from kalodata_integration import QueryError
                try:configured=bool(service.kalodata.secret())
                except QueryError as exc:raise HTTPException(503,str(exc)) from None
                if not configured:raise HTTPException(503,'请管理员在数据接入中配置 Kalodata 密钥')
                cached=json.loads(row['source']).get('kalodata',{})
                if cached.get('period_start')==options['period_start'] and cached.get('period_end')==options['period_end'] and cached.get('collected',0)>time.time()-900:
                    ready=db.execute("SELECT id,state FROM video_case_jobs WHERE case_id=? AND kind='kalodata' AND state='ready' ORDER BY updated DESC LIMIT 1",(cid,)).fetchone()
                    if ready:return dict(ready)
                if db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE kind='kalodata' AND state IN ('queued','submitting','running','waiting')").fetchone()[0]>=10:raise HTTPException(429,'案例查询队列已满，请等待已有任务')
                if db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE kind='kalodata' AND owner=? AND created>?",(u['id'],time.time()-86400)).fetchone()[0]>=50:raise HTTPException(429,'已达到每人每日50次案例查询上限')
            if kind=='metadata' and not service.monitor.config.available():raise HTTPException(400,'Apify 账号池没有可用密钥，请管理员核验')
            if kind=='transcript':
                from script_automation import local_asr_ready
                if not local_asr_ready():raise HTTPException(400,'缺少本地语音模型或下载工具；未排队')
            if kind=='analysis':
                import asr
                if not asr.configured_key(hub):raise HTTPException(400,'未配置A6API Gemini 3.8 Flash服务')
            if kind=='ai':
                import asr
                if not asr.configured_key(hub):raise HTTPException(400,'未配置 A6API Gemini 3.8 Flash 服务')
                if not (json.loads(row['human']).get('transcript') or row['transcript'] or json.loads(row['source']).get('title')):raise HTTPException(400,'请先获取发布文案或填写逐字稿')
            jid=uuid.uuid4().hex;now=time.time();db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated) VALUES(?,?,?,?,'queued',?,?,?)",(jid,cid,u['id'],kind,key,now,now))
            if options:db.execute('UPDATE video_case_jobs SET options=? WHERE id=?',(json.dumps(options),jid))
            hub.log(db,u['id'],'video_case_processing',kind+':'+cid)
        return {'id':jid,'state':'queued'}
    @app.post(PREFIX+'/{cid}/jobs/{jid}/cancel-wait')
    def cancel_wait(cid:str,jid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');require_case(db,cid)
            job=db.execute('SELECT owner,state FROM video_case_jobs WHERE id=? AND case_id=?',(jid,cid)).fetchone()
            if not job or job['owner']!=u['id']:raise HTTPException(404,'任务不存在或不属于你')
            if job['state']=='cancelled':return {'ok':True}
            if job['state']!='waiting':raise HTTPException(409,'任务不在等待状态，未中断正在执行的请求')
            db.execute("UPDATE video_case_jobs SET state='cancelled',next_attempt=NULL,error='已停止自动检查；保留已取得的资料',updated=? WHERE id=?",(time.time(),jid))
            hub.log(db,u['id'],'video_case_cancel_wait',jid)
        return {'ok':True}
    @app.post(PREFIX+'/{cid}/refresh-local')
    def refresh_local(cid:str,request:Request):
        user(request)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');row=require_case(db,cid);reuse_local(db,row)
        return {'ok':True}
    @app.post(PREFIX+'/{cid}/library')
    def library(cid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');row=require_case(db,cid)
            old=db.execute('SELECT id,removed_at FROM script_library WHERE video=?',(row['video'],)).fetchone() if row['video'] else None
            if not old and row['library_id']:old=db.execute('SELECT id,removed_at FROM script_library WHERE id=?',(row['library_id'],)).fetchone()
            if old and old['removed_at'] is not None:raise HTTPException(409,'该文案已移除，未重新创建')
            if old:db.execute('UPDATE video_cases SET library_id=? WHERE id=?',(old['id'],cid));return {'id':old['id'],'existing':True,'video':row['video']}
            source=json.loads(row['source']);human=json.loads(row['human']);ai=json.loads(row['ai']).get('fields',{});iid=uuid.uuid4().hex;now=time.time()
            from video_case_fields import projection
            resolved=projection({**row,'source':source,'human':human,'ai':json.loads(row['ai'])});text=resolved['transcript']['value']
            db.execute('''INSERT INTO script_library(id,video,account_handle,video_url,description,cover,snapshot,reasons,transcript_original,transcript_source,transcript_status,
              product_category,content_type,opening,audience_scenario,expression,ending,tags,created,updated,created_by,updated_by)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(iid,row['video'] or None,row['handle'],row['url'],resolved['title']['value'],source.get('cover'),json.dumps(source),json.dumps(['视频案例库人工关联；非数据达标认定'],ensure_ascii=False),text or None,'人工校对' if human.get('transcript') else row['transcript_source'],'已提取' if text else '未提取',resolved['category']['value'],resolved['content_type']['value'],resolved['opening']['value'],resolved['audience_scenario']['value'],resolved['expression']['value'],resolved['ending']['value'],json.dumps(human.get('tags') or ai.get('tags',[]),ensure_ascii=False),now,now,u['id'],u['id']))
            db.execute('UPDATE script_library SET auto_enrichment_excluded=1 WHERE id=?',(iid,))
            db.execute('UPDATE video_cases SET library_id=? WHERE id=?',(iid,cid))
        return {'id':iid,'existing':False,'video':row['video']}
    @app.get(PREFIX+'/{cid}/still')
    def case_still(cid:str,ms:int,request:Request):
        from fastapi.responses import Response
        from case_shots import still
        user(request)
        with hub.db() as db: row=require_case(db,cid)
        path=hub.directory/'case-analysis'/row['id']/'source.mp4'
        if not 0<=ms<=1200000 or not path.is_file():raise HTTPException(404,'暂无可用截图')
        return Response(still(path,path.stat().st_mtime_ns,ms),media_type='image/jpeg',headers={'Cache-Control':'private, max-age=300'})

    @app.get(PREFIX+'/{cid}/shots')
    def shots(cid:str,request:Request):
        from case_shots import detect
        user(request)
        with hub.db() as db: row=require_case(db,cid)
        path=hub.directory/'case-analysis'/row['id']/'source.mp4'
        if not path.is_file():raise HTTPException(404,'案例暂无本地预览')
        return {'shots':detect(path,path.stat().st_mtime_ns)}

    @app.get(PREFIX+'/{cid}/preview')
    def preview(cid:str,request:Request):
        user(request)
        with hub.db() as db: row=require_case(db,cid)
        path=hub.directory/'case-analysis'/row['id']/'source.mp4'
        if not path.is_file():raise HTTPException(404,'案例暂无本地预览')
        return FileResponse(path,media_type='video/mp4',headers={'Cache-Control':'private, no-store'})

    @app.get(PREFIX+'/{cid}/cover')
    def cover(cid:str,request:Request):
        user(request)
        with hub.db() as db:row=require_case(db,cid)
        directory=hub.directory/'case-covers';directory.mkdir(exist_ok=True);path=directory/(cid+'.img')
        # The monitor already persists public covers. Reuse them before a new CDN request,
        # especially when the original signed URL has expired. Only canonical numeric IDs.
        if not path.exists() and re.fullmatch(r'\d{5,25}',row['video'] or ''):
            for ext,kind in (('.jpg','image/jpeg'),('.png','image/png'),('.webp','image/webp')):
                cached=hub.directory/'apify-covers'/(row['video']+ext)
                if cached.is_file() and 0<cached.stat().st_size<=4_000_000:
                    signature=cached.read_bytes()[:12]
                    if (ext=='.jpg' and signature.startswith(b'\xff\xd8\xff')) or (ext=='.png' and signature.startswith(b'\x89PNG\r\n\x1a\n')) or (ext=='.webp' and signature[:4]==b'RIFF' and signature[8:12]==b'WEBP'):
                        return FileResponse(cached,media_type=kind,headers={'Cache-Control':'private, max-age=604800'})
        if not path.exists():
            source=json.loads(row['source']);url=source.get('cover')
            if not isinstance(url,str):raise HTTPException(404,'没有封面')
            content=None
            try:
                # No arbitrary user URL, no cookies, bounded streaming and validated public CDN hosts.
                for _ in range(4):
                    p=urlsplit(url);host=p.hostname or ''
                    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or not any(host.endswith('.'+s) for s in ('tiktokcdn.com','tiktokcdn-us.com','tiktokcdn-eu.com','muscdn.com','byteoversea.com','ibytedtos.com','byteimg.com')):raise ValueError()
                    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
                    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError()
                    with httpx.Client(timeout=15,trust_env=False,follow_redirects=False) as client:
                        with client.stream('GET',url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.tiktok.com/'}) as res:
                            if res.is_redirect:url=urljoin(url,res.headers['location']);continue
                            res.raise_for_status();chunks=[];size=0
                            for chunk in res.iter_bytes():
                                size+=len(chunk)
                                if size>4_000_000:raise ValueError()
                                chunks.append(chunk)
                            content=b''.join(chunks)
                    break
                if not content or not (content.startswith((b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n')) or (content[:4]==b'RIFF' and content[8:12]==b'WEBP')):raise ValueError()
                path.write_bytes(content)
            except (ValueError,OSError,httpx.HTTPError):raise HTTPException(404,'封面暂不可用；资料仍保留') from None
        content=path.read_bytes()[:12];kind='image/png' if content.startswith(b'\x89PNG') else 'image/webp' if content[:4]==b'RIFF' else 'image/jpeg'
        return FileResponse(path,media_type=kind,headers={'Cache-Control':'private, max-age=604800'})
    return service
