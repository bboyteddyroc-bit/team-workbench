"""Product filming-method cards, projected entirely from locally saved evidence."""
from collections import defaultdict
from statistics import median
import re

from product_research_tags import contains, norm, uncertain, supported_alias

# Require a demonstrated action, not simply a similar product name or demographic.
ACTIONS = (
    ('凌乱到整洁', ('凌乱到整洁','杂乱到整洁','收纳前后','收整前后','messy to tidy','clutter to clean')),
    ('窄缝收纳', ('窄缝收纳','塞进窄缝','放入窄缝','fits into a narrow gap')),
    ('容量实测', ('容量实测','装满测试','容量测试','capacity test')),
    ('安装演示', ('安装演示','安装教程','installation demo')),
    ('满载提起', ('满载提起','满载提手','满载搬运','carry when full')),
)
NEEDS = {
    '窄缝收纳': ('商品适用宽度',('厘米','cm','英寸','inches','毫米','mm')),
    '满载提起': ('满载提起的承重条件',('承重','load capacity','weight capacity')),
    '容量实测': ('可核实的容量',('容量','升','liters','litres')),
}
TITLES = [('fit','商品适配'),('demand','用户需求与购买意图'),('scene','使用场景与触发时刻'),
          ('barrier','购买阻力与内容缺口'),('performance','拍法表现'),('shots','可复用镜头')]


def specific_actions(text):
    return [name for name,aliases in ACTIONS if not uncertain(text) and any(contains(norm(text),a) for a in aliases)]


def peer_baseline(db,v):
    stamp=v['snap_time']
    if not stamp or not v['snap_age_band'] or v['views_snapshot'] is None:return None
    lo,hi={'0–7天':(0,7),'8–30天':(8,30),'31–90天':(31,90)}[v['snap_age_band']]
    rows=db.execute("""SELECT s.video,s.views FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account
      JOIN users u ON u.id=a.owner AND u.enabled=1 WHERE a.deleted_at IS NULL AND a.handle=? COLLATE NOCASE
      AND s.video<>? AND s.views>=0 AND s.collected BETWEEN ? AND ? AND s.published IS NOT NULL
      AND CAST(s.collected/86400 AS INTEGER)-CAST(s.published/86400 AS INTEGER) BETWEEN ? AND ?
      ORDER BY s.collected DESC""",(v['handle'],v['video'],stamp-7*86400,stamp,lo,hi))
    distinct={}
    for video,views in rows: distinct.setdefault(video,views)
    if len(distinct)<3:return None
    return {'median':median(distinct.values()),'count':len(distinct)}


def evidence(v,source,text,**extra):
    return dict(case_id=v['id'],video=v['video'],title=v['title'],source=source,text=text,url=v['url'],thumb=v['thumb'],**extra)


def line(label,value,detail,items,**counts):
    return dict(label=label,value=str(value),detail=detail,evidence=items,**counts)


def method_reports(data,goods,profile,rollup,format_key):
    groups=defaultdict(list)
    for record in data:
        v=record[0];content=v['video_content']; methods=set()
        for key in ('opening','content_type','replication_actions'):
            methods.update(specific_actions(content.get(key,{}).get('value','')))
        approved=[t for t in v['tags'] if t['kind']=='内容玩法' and t['decision']!='rejected']
        blocked={norm(t['label']) for t in v['tags'] if t['decision']=='rejected'}
        if not methods:methods.update(t['label'] for t in approved)
        fallback=format_key(content.get('content_type',{}).get('value',''))
        if not methods and fallback and len(fallback)<=25:methods.add(fallback)
        methods={m for m in methods if norm(m) not in blocked}
        for name in sorted(methods or {'待识别拍法'}):groups[name].append(record)
    if not groups:groups['待匹配拍法']=[]
    groups[None]=data
    reports=[]
    for name,entries in sorted(groups.items(),key=lambda kv:(kv[0] is not None,(kv[0] or '').startswith('待'),-len(kv[1]),kv[0] or '')):
        videos=[r[0] for r in entries]
        comparable=[r for r in entries if r[0]['included']]
        byvid={v['id']:v for v in videos}
        signals=rollup(comparable)
        cards={k:[] for k,_ in TITLES}
        for tag in profile['tags']:
            if tag['decision']=='rejected':continue
            cards['fit'].append(line(tag['label'],'人工确认' if tag['decision']=='confirmed' else '档案标签',tag['kind'],
                [dict(title=goods['name'],source='商品档案',text=tag['source'])]))
        if name in NEEDS:
            label,words=NEEDS[name];facts=goods.get('facts') or ''
            stated=bool(supported_alias(facts,words))
            cards['fit'].append(line(label,'有规格记录' if stated else '待补规格','须对照原镜头核实条件',
                 [dict(title=goods['name'],source='规格与事实',text=facts)] if stated else []))
        if videos:
            cards['fit'].append(line('案例关联依据',f'{len(videos)} 条','逐条核对商品关系',
                [evidence(v,v['match']['label'],v['match']['reason']) for v in videos]))
        for card,keys in [('demand',('looking','pain','buy_intent','bought')),('scene',('scene','people')),('barrier',('barrier','question'))]:
            for k in keys:
                s=signals[k]
                for role,title in [('comments','主评论'),('replies','回复')]:
                    n=s[role]
                    if not n['total']:continue
                    quotes=[]; matched_videos=set(); matched_accounts=set()
                    for v,records,annotation in comparable:
                        if not annotation:continue
                        ids={cid for g in annotation['signals'][k] for cid in g['ids']}
                        labels=defaultdict(list)
                        for group in annotation['signals'][k]:
                            for cid in group['ids']:labels[cid].append(group['label'])
                        for q in records:
                            if q['cid'] not in ids or bool(q['parent'])!=(role=='replies'):continue
                            matched_videos.add(v['id'])
                            if v['handle']:matched_accounts.add(v['handle'].casefold())
                            if name is None or len(quotes)<3:
                                quotes.append(evidence(v,title+' · '+s['label'],q['text'],cid=q['cid'],meaning='、'.join(labels[q['cid']]),translation=annotation.get('translations',{}).get(q['cid'],'')))
                    eligible=sum(bool(annotation and any(bool(q['parent'])==(role=='replies') for q in records)) for _,records,annotation in comparable)
                    detail=f"{title} · 视频覆盖 {len(matched_videos)/eligible:.0%}（{len(matched_videos)}/{eligible}），涉及 {len(matched_accounts)} 位达人"
                    if n['hits'] and k in ('buy_intent','question','bought'):
                        detail+='。按关联视频的评论统计，请核对原话指向的商品。'
                    cards[card].append(line(s['label'],f"{n['hits']}/{n['total']}",detail,quotes,hits=n['hits'],total=n['total']))
        for v in videos:
            for section,field in [('scene','audience_scenario'),('shots','opening'),('shots','expression'),('shots','ending')]:
                f=v['video_content'].get(field)
                if not f:continue
                label={'audience_scenario':'视频描述的场景','opening':'开场','expression':'演示','ending':'收尾'}[field]
                e=evidence(v,f['source'],f['value']+(' · '+f['evidence'] if f['evidence'] else ''))
                stamp=re.search(r'(?<!\d)(\d{1,2}):([0-5]\d)(?:[.](\d{1,3}))?',f['evidence'])
                if stamp:e['time']=int(stamp[1])*60+int(stamp[2])+float('0.'+(stamp[3] or '0'))
                if f.get('clip'):
                    e['time'],e['end']=f['clip']
                    e['source']+=' · 区间已人工核对'
                if section=='shots':
                    at=e.get('time')
                    kind='证据时间点'
                    if f.get('clip'):
                        at=sum(f['clip'])/2
                        kind='已核实区间'
                    elif at is None and v.get('duration'):
                        at=max(0,v['duration']-0.5)*{'opening':0,'expression':0.5,'ending':1}[field]
                        kind='参考帧'
                        e['time']=at
                    e['thumb']=''
                    if at is not None and 0<=at<=1200:
                        ms=round(at*1000)
                        e.update(thumb=f"/api/intelligence/cases/{v['id']}/still?ms={ms}",frame_time=ms/1000,frame_kind=kind)
                cards[section].append(line(label,v['handle'],f['value'],[e]))
            for pair in v['faq']:
                cards['barrier'].append(line(pair['label'],'有相关口播' if pair['passages'] else '待核对画面',
                    '关键词相符的口播片段；是否回答需核对原片',[evidence(v,v['text_source'],p) for p in pair['passages']]))
            if v['included'] and v['estimate'] and v['estimate']['gmv'] is not None:
                e=v['estimate'];val=f"{e['currency']} {e['gmv']:g}"
                cards['demand'].append(line('视频估算 GMV',val,e['region']+' · '+e['start']+' — '+e['end'],
                    [evidence(v,e['endpoint'],'视频区间估算值；不能全部归因于自家商品')]))
        base=[r[0] for r in comparable if r[0]['baseline']]
        positive=sum(v['views_snapshot']>v['baseline']['median'] for v in base)
        if base:cards['performance'].append(line('高于同账号播放中位数',f'{positive}/{len(base)}','同期采样 · 相似发布时长',
            [evidence(v,v['snap_scope'],f"本片播放 {v['views_snapshot']:g}；对照 {v['baseline']['count']} 条视频的中位数 {v['baseline']['median']:g}") for v in base],hits=positive,total=len(base)))
        no_base=[r[0] for r in comparable if not r[0]['baseline']]
        if no_base:cards['performance'].append(line('缺少可比基线',f'{len(no_base)} 条','至少需要 3 条同账号对照视频',
            [evidence(v,v['snap_scope'] or '本地案例','当前公开播放：'+(str(v['views_snapshot']) if v['views_snapshot'] is not None else '未提供')) for v in no_base]))
        sample=[r[0] for r in comparable]
        if sample:
            accounts={v['handle'].casefold() for v in sample if v['handle']}
            cards['performance'].append(line('独立账号覆盖',f'{len(accounts)} 位',f'同类样本 {len(sample)} 条，按账号去重',
                [evidence(v,'案例来源','@'+v['handle']) for v in sample if v['handle']]))
        dated=[v for v in sample if v['age'] is not None]
        if dated:
            recent=sum(0<=v['age']<=30 for v in dated)
            cards['performance'].append(line('近 30 天发布',f'{recent}/{len(dated)}','分母为有发布日期的同类视频',
                [evidence(v,'视频发布日期',v['published']) for v in dated],hits=recent,total=len(dated)))
        for v in sample:
            if v['trend']:
                t=v['trend']
                cards['performance'].append(line('近期新增播放',f"+{t['gain']:,}",v['title'],
                    [evidence(v,'Apify 两次播放快照',f"{t['before']:,} → {t['after']:,}")]))
        reports.append(dict(id=name or '__all__',label=name or '商品综合报告',summary=(f'当前拍法关联 {len(videos)} 条视频 · {len({v["handle"].casefold() for v in videos})} 位达人。'
            + (f' {positive}/{len(base)} 条高于账号播放基线。' if base else ' 暂缺可比播放基线。')) if videos else '等待相关案例入库',
            cases=list(byvid),cards=[dict(id=k,title=t,rows=cards[k]) for k,t in TITLES]))
    return reports
