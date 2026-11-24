"""Intelligence-only exception inbox. Diagnostics inherit the task's actual access."""
import re
from typing import NamedTuple

from fastapi import HTTPException, Request

import task_feedback as feedback


def safe_error(value):
    text=str(value or '').strip()
    if not text:return '未记录具体报错，请查看原任务或联系管理员。'
    if text.startswith(('{','[')) and ('":"' in text.replace(' ','') or '"' in text):
        return '上游返回了未公开的错误详情，请按任务编号排查。'
    text=re.split(r'\s*(?:错误摘要|响应原文|请求体|响应正文|提示词|response body|raw response|prompt)\s*[：:]',text,maxsplit=1,flags=re.I)[0]
    text=re.sub(r'(?i)\b(?:authorization|cookie|set-cookie)\s*["\']?\s*[:=][^\r\n]*','[请求凭据已隐藏]',text)
    text=re.sub(r'(?i)\b(bearer\s+|(?:x-api-key|api[_ -]?key|secret[_ -]?key|token|secret|password|sessionid|csrf)["\']?\s*[=:]\s*)[^\s,;]+',r'\1[已隐藏]',text)
    text=re.sub(r'(?i)(?:https?://|(?:[a-z]:[\\/]|\\\\))[^\s<>"，。；]+','[地址已隐藏]',text)
    return text[:800]


class Source(NamedTuple):
    type: str
    kind: str
    provider: str
    table: str
    id: str
    state: str
    error: str
    updated: str
    where: str
    join: str = ''
    title: str = "''"
    case_id: str = 'NULL'
    stage: str = 'NULL'
    code: str = 'NULL'
    shared: bool = False


ISSUE="e.state IN ('attention','failed','unknown')"
OWNER='e.owner=:owner'
ACCOUNT='a.owner=:owner'
# Same team-visible boundary as the existing case and comment detail routes.
TEAM='''c.removed_at IS NULL AND EXISTS (SELECT 1 FROM video_case_members m
         JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=c.id)'''
CASE='JOIN video_cases c ON c.id=e.case_id LEFT JOIN video_case_checkpoints k ON k.job=e.id'
COMMENT_CASE="JOIN video_cases c ON c.video=e.video AND c.platform='TikTok'"
SOURCES=(
    Source('script_labels','文案 AI 分类','A6API','script_enrichment','e.item','e.state','e.error','e.updated',f'{OWNER} AND {ISSUE}',
           'LEFT JOIN script_library l ON l.id=e.item','coalesce(l.video,e.item)'),
    Source('script_transcript','文案口播提取','本地识别','script_transcriptions','e.item','e.state','e.error','e.updated',f'{OWNER} AND {ISSUE}',
           'LEFT JOIN script_library l ON l.id=e.item','coalesce(l.video,e.item)'),
    Source('script_create','脚本创作','A6API','script_creative_tasks','e.id','e.state','e.error','e.updated',f'{OWNER} AND {ISSUE}',title='e.title'),
    Source('apify_group','账号采集','Apify','grouped_runs','e.id','e.state','e.error','e.updated',f'{OWNER} AND {ISSUE}',
           title="CASE WHEN e.automatic=1 THEN '自动合并采集' ELSE '手动合并采集' END"),
    Source('apify_run','视频采集','Apify','apify_runs','e.id','e.state','e.error','e.updated',f'{ACCOUNT} AND {ISSUE}',
           'JOIN apify_accounts a ON a.id=e.account','a.handle'),
    Source('video_enrichment','视频补数','Kalodata','video_enrichment_jobs','e.id','e.state','e.error','e.updated',f'{ACCOUNT} AND {ISSUE}',
           'JOIN apify_accounts a ON a.id=e.account','e.video'),
    Source('kalodata','Kalodata 查询','Kalodata','kalodata_jobs','e.id','e.state','e.error','e.updated',f'{OWNER} AND {ISSUE}',title='e.target'),
    Source('own_goods_lookup','自营商品取数','TikTok Shop / Kalodata','own_goods_lookup','e.id','e.state','e.error','e.updated',
           f'''{ISSUE} AND (e.owner=:owner OR g.owner=:owner OR
               EXISTS (SELECT 1 FROM users u WHERE u.id=:owner AND u.role='admin'))''',
           'JOIN own_goods g ON g.id=e.goods','g.name',code='e.error_code'),
    *(Source(key,label,provider,'video_case_jobs','e.id','e.state','e.error','e.updated',f"{TEAM} AND {ISSUE} AND e.kind='{kind}'",
             CASE,'c.video','c.id','k.stage','e.error_code',True)
      for key,kind,label,provider in (
         ('case_metadata','metadata','案例视频采集','Apify'),('case_metrics','kalodata','案例指标采集','Kalodata'),
         ('case_analysis','analysis','案例视频 AI 分析','A6API'),('case_text','ai','案例文字 AI 整理','A6API'),
         ('case_transcript','transcript','案例口播提取','本地识别'))),
    Source('comment_collect','评论与回复补采','ScrapeCreators','comment_sample_jobs','e.video','e.state','e.error','coalesce(e.finished,e.updated)',
           f"{TEAM} AND ({ISSUE} OR (e.state='partial' AND trim(e.error)<>''))",COMMENT_CASE,'e.video','c.id',shared=True),
    Source('comment_ai','评论 AI 提炼','A6API','comment_sample_jobs','e.video','e.ai_state','e.ai_error','e.updated',
           f"{TEAM} AND e.ai_state IN ('attention','failed','unknown')",COMMENT_CASE,'e.video','c.id',shared=True),
    Source('comment_research','评论 AI 证据标注','A6API','comment_sample_research','e.video','e.state','e.error','e.updated',
           f'{TEAM} AND {ISSUE}',COMMENT_CASE,'e.video','c.id',shared=True),
)
BY_TYPE={s.type:s for s in SOURCES}
LIMIT=200


def source_rows(db, source, owner, task=None):
    s=source
    exact=f' AND {s.id}=:task' if task is not None else ''
    return db.execute(f'''SELECT {s.id} id,{s.state} state,{s.error} error,{s.updated} updated,{s.title} title,
                         {s.case_id} case_id,{s.stage} saved_stage,{s.code} saved_code
                         FROM {s.table} e {s.join} WHERE ({s.where}){exact}
                         ORDER BY {s.updated} DESC,{s.id} DESC LIMIT :limit''',
                      {'owner':owner,'task':task,'limit':1 if task is not None else LIMIT}).fetchall()


def attach(app,hub,user):
    @app.get('/api/intelligence/exceptions')
    def list_exceptions(request:Request):
        u=user(request)
        items=[]
        with hub.db() as db:
            rows=[(s,r) for s in SOURCES for r in source_rows(db,s,u['id'])]
            latest=feedback.latest_failures(db,[(s.type,r['id']) for s,r in rows])
            for s,r in rows:
                details=latest.get((s.type,r['id']))
                error=r['error']
                status=feedback.outcome(r['state'],error,details)
                # These messages describe remote terminal task status, not a network error.
                if not details and s.provider=='Apify' and re.search(r'(?:任务结束：|任务未成功（)(?:FAILED|ABORTED|TIMED-OUT)', error or ''):
                    status='failed'
                items.append({'id':str(r['id']),'type':s.type,'kind':s.kind,'provider':s.provider,
                              'state':r['state'],'feedback_state':status,'error':safe_error(error),'updated':r['updated'],
                              'title':str(r['title'] or '')[:200],'case_id':r['case_id'],'shared':s.shared,
                              'feedback':details,'saved_stage':safe_error(r['saved_stage']) if r['saved_stage'] else None,
                              'saved_code':r['saved_code'] if feedback.CODE.fullmatch(str(r['saved_code'])) else None})
        items.sort(key=lambda r:r['updated'] or 0,reverse=True)
        return {'items':items,'types':[{'type':s.type,'kind':s.kind} for s in SOURCES],
                'limit_per_type':LIMIT,'scope':'current_user_and_team_cases'}

    @app.get('/api/intelligence/exceptions/{kind}/{task_id}/feedback')
    def read_feedback(kind:str,task_id:str,request:Request):
        u=user(request)
        feedback.valid_task(task_id)
        source=BY_TYPE.get(kind)
        with hub.db() as db:
            if not source or not source_rows(db,source,u['id'],task_id):
                raise HTTPException(404,'任务不存在或已不在异常列表')
            return {'items':feedback.timeline(db,kind,task_id)}
