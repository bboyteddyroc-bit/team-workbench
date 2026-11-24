"""Shared case display projection: typed tag groups and field-level metric provenance.
Pure/local only: never imports private query history or invents a missing metric.
"""
import math

TAG_CATEGORIES=[
    {'id':'product','label':'商品品类','color':'blue'},
    {'id':'format','label':'内容玩法','color':'teal'},
    {'id':'appeal','label':'核心吸引点','color':'amber'},
    {'id':'scene','label':'场景与节点','color':'rose'},
    {'id':'production','label':'制作特征','color':'neutral'},
    {'id':'other','label':'其他标签','color':'neutral'},
]
VOCAB={
'product':['饮具','杯具','工具','五金工具','收纳','家居收纳','服饰配件','围巾','个护','美妆','数码','厨具','家居','食品','宠物用品'],
'format':['结构演示','多色展示','使用演示','实物演示','前后对比','拆礼物反应','实测挑战','教程','开箱','清单推荐','街头互动','多场景佩戴','场景演示','对比','演示','开箱演示'],
'appeal':['新奇设计','趣味反差','情绪反应','问题解决','视觉反差','悬念揭晓','趣味礼物','搞笑礼物'],
'scene':['圣诞送礼','圣诞氛围','节日季','母亲节','生日送礼','送礼','旅行','厨房','办公','户外','圣诞节','黑五'],
'production':['手部出镜','真人出镜','无口播','多场景','单场景','手持近景','屏幕字幕','路人反应'],
}


def validate_tag_groups(value):
    if not isinstance(value,dict) or set(value)-{x['id'] for x in TAG_CATEGORIES}:raise ValueError('标签类别无效')
    result={}
    for group,items in value.items():
        if not isinstance(items,list) or len(items)>8 or any(not isinstance(x,str) or not 1<=len(x.strip())<=30 for x in items):raise ValueError('每类最多8个标签，每个1–30字')
        result[group]=list(dict.fromkeys(x.strip() for x in items))
    if sum(map(len,result.values()))>24:raise ValueError('每个案例最多24个标签')
    return result


def tag_projection(row):
    human=row.get('human',{});ai=row.get('ai',{}).get('fields',{})
    if 'tag_groups' in human:
        return {'groups':human['tag_groups'],'origin':'人工分类','suggested':False}
    if 'tags' not in human and isinstance(ai.get('tag_groups'),dict):
        try:return {'groups':validate_tag_groups(ai['tag_groups']),'origin':'AI建议 · 待审核','suggested':True}
        except ValueError:pass
    # Migrate presentation only: classify exact existing labels, never manufacture factual tags.
    tags=human.get('tags',ai.get('tags',[]));groups={x['id']:[] for x in TAG_CATEGORIES}
    for tag in tags if isinstance(tags,list) else []:
        if not isinstance(tag,str):continue
        group=next((k for k,words in VOCAB.items() if tag in words),'other')
        if tag not in groups[group] and len(groups[group])<8:groups[group].append(tag)
    # Use short existing category/format/event values only, not semantic guesses from a synopsis.
    for group,hkey,akey in [('product','category','product_category'),('format','content_type','content_type'),('scene','event','event')]:
        text=human.get(hkey,ai.get(akey,''))
        if not groups[group] and isinstance(text,str) and 0<len(text)<=30 and not any(x in text for x in ('未知','不确定','未证实','无依据','没有')):
            groups[group].append(text)
    return {'groups':{k:v for k,v in groups.items() if v},'origin':'已有标签分类建议 · 待确认','suggested':'tag_groups' not in human}


METRICS=[('views','播放量','manual_views','period_views','views'),('likes','点赞','manual_likes','likes','likes'),
('shares','分享','manual_shares','shares','shares'),('collects','收藏','manual_collects',None,'collects'),
('comments','评论','manual_comments','comments','comments'),('gmv','GMV','manual_gmv','gmv',None)]


def numeric(value):
    if isinstance(value,bool) or value is None:return None
    try:
        n=float(value)
        return n if math.isfinite(n) and 0<=n<1e16 else None
    except (ValueError,TypeError):return None


def metric_projection(row):
    human=row.get('human',{});source=row.get('source',{});kd=source.get('kalodata',{}) or {};items=[]
    for key,label,hkey,kkey,skey in METRICS:
        value=None;text='';origin='未提供';scope='';collected=None;currency=None
        if hkey in human:
            text=human[hkey];value=numeric(text);origin='人工核实';scope=human.get('manual_metric_basis','未注明人工口径')
            currency=(human.get('manual_gmv_currency') or None) if key=='gmv' else None
        elif kkey and numeric(kd.get(kkey)) is not None:
            value=numeric(kd[kkey]);origin='Kalodata';collected=kd.get('collected')
            period=f"{kd.get('period_start','?')} — {kd.get('period_end','?')}（UTC）"
            scope=('区间播放 · ' if key=='views' else '第三方区间估算 · ' if key=='gmv' else '查询区间 '+period+'；互动口径以供应商为准')
            if key in ('views','gmv'):scope+=period
            if key=='gmv':currency=kd.get('currency') or None
        elif skey and numeric(source.get(skey)) is not None:
            value=numeric(source[skey]);origin=source.get('origin') or '公开视频快照';scope='累计快照，非Kalodata区间数据';collected=source.get('collected')
        if key=='collects' and value is None and not text:scope='Kalodata详情不提供收藏；需已有公开视频快照或人工核实'
        if key=='gmv' and value is None and not text:scope='未取得估算GMV，不补零'
        items.append({'key':key,'label':label,'value':value,'text':text,'source':origin,'scope':scope,'collected':collected,'currency':currency,'missing':value is None and not text})
    return items
