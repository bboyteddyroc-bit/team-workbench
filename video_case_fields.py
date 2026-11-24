"""One field-level resolver for drawer, gallery, AI input and script hand-off.
Manual presence (including clear) > actual Kalodata > existing public/local evidence > AI.
Metrics, identity, publish dates and verbatim transcripts are never invented by AI.
"""
from datetime import datetime,timezone

ANALYSIS=('summary','event','category','content_type','replicability','replication_actions','hook_example','hook_template','suitable_products','production_threshold','prerequisites','opening','audience_scenario','expression','ending','notes','transcript_en','transcript_zh')
KEYS=('title','publisher','published_at','transcript','merchant_visible')+ANALYSIS


def projection(row):
    source=row.get('source',{});kd=source.get('kalodata',{}) or {};human=row.get('human',{});ai=row.get('ai',{}).get('fields',{});result={}
    # Explicit documented mappings only. A product category is NOT inferred from a
    # title/GMV by the provider adapter, and ai_video is NOT merchant visibility.
    from video_case_commercial import date_text
    published_kd=date_text(kd.get('publish_date'))
    facts={'title':kd.get('title'),'publisher':kd.get('handle'),'published_at':published_kd}
    public={'title':source.get('title'),'publisher':row.get('handle'),'transcript':row.get('transcript')}
    published=source.get('published')
    if type(published) in (int,float):
        try:public['published_at']=datetime.fromtimestamp(published,timezone.utc).isoformat()
        except (ValueError,OSError,OverflowError):pass
    for key in KEYS:
        value='';origin='未提供';evidence='';suggested=False
        if key in human:value=human[key];origin='人工修订'
        elif facts.get(key) not in (None,''):
            value=facts[key];origin='Kalodata';evidence='/video/detail · '+str(kd.get('period_start',''))+' — '+str(kd.get('period_end',''))
        elif public.get(key) not in (None,''):
            value=public[key];origin=row.get('transcript_source') or '本地口播证据' if key=='transcript' else source.get('origin') or ('链接作者' if key=='publisher' else '来源资料')
        elif key in ANALYSIS:
            akey='product_category' if key=='category' else key
            value=ai.get(akey) or '';origin='AI建议 · 待审核' if value else '未提供';suggested=bool(value)
            evidence=row.get('ai',{}).get('evidence',{}).get(akey,'') if value else ''
        if key=='published_at' and origin=='Kalodata':evidence+='；平台市场时间，未附UTC偏移，不擅自换算'
        if key=='merchant_visible' and key not in human:evidence='Kalodata视频接口不提供商家可见性，不由AI猜测'
        if not value and key in ANALYSIS and key not in human:evidence='Kalodata视频接口未提供此拆解字段；需视频/口播证据支持AI补缺'
        result[key]={'value':value,'source':origin,'evidence':evidence,'suggested':suggested,'missing':value in (None,'')}
    return result


def ai_plan(row):
    resolved=projection(row);missing=[];facts={}
    for key,item in resolved.items():
        if not item['suggested'] and not item['missing']:facts[key]={'value':item['value'],'source':item['source']}
        if key in ANALYSIS and key not in row.get('human',{}) and (item['missing'] or item['suggested']):missing.append('product_category' if key=='category' else key)
    return facts,missing
