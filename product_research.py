"""Local, auditable product report. A GET never writes or starts a paid task."""
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from fastapi import HTTPException, Request
from comment_research import SIGNALS, bucket, read_pack
from video_case_presentation import METRICS, metric_projection, numeric
from comment_samples import CASE_VISIBLE
from own_goods import get_goods, require_editor
from own_goods_lookup import dossier_profile
from research_tag_review import review_index, review_tags, tag_key, video_tags
from product_research_methods import method_reports, peer_baseline, specific_actions
from product_research_tags import uncertain as uncertain_scene, CONTEXT, linked_titles, resolved_case_category, contains, norm
from script_library import matches as performance_matches
from video_case_fields import projection as field_projection

REPORT_LIMIT=24
DAY=86400
SNAPSHOT_ORIGINS={'账号监测快照','Apify 单视频采集'}
FORMAT_ALIASES={
    '实物 / 使用演示':{'使用演示','实物演示','功能演示','使用展示','product demo','demonstration'},
    '前后对比':{'前后对比','效果对比','before after','before and after'},
    '开箱':{'开箱','开箱演示','unboxing'},
    '教程':{'教程','安装教程','使用教程','tutorial','how to'},
    '场景演示':{'场景演示','情景演示','scenario demo'},
}
THRESHOLDS={'likes':5,'collects':0.8,'comments':0.15}
SIGNAL_LABELS={'looking':'正在找解决办法','bought':'自称已买或下单','used':'自述使用体验','people':'明确说到使用者','scene':'明确说到场景 / 时点','pain':'明确吐槽','barrier':'购买阻力','question':'仍在询问的内容','buy_intent':'询问规格、价格、渠道等','reaction':'只有泛反应'}
DIMENSIONS=(('demand','1. 需求：有人在找，还是已经在买？',('looking','bought','used')),
 ('people','2. 人群与场景：谁在什么时候遇到问题？',('people','scene')),
 ('pain','3. 痛点与购买阻力：用户在吐槽什么？',('pain','barrier')),
 ('competition','4. 竞争：样本分散，还是集中在少数账号？',()),
 ('gap','5. 内容缺口：用户还在问什么？',('question',)),
 ('performance','6. 内容表现：好结果是否跨账号重复？',()),
 ('intent','7. 关注与购买意图：是泛反应，还是认真了解？',('buy_intent','reaction')),
 ('timing','8. 时机：是近期信号，还是旧内容累积？',()))
FAQ_WORDS=(('尺寸与适配',('尺寸','门厚','适配','多宽','多高','size','width','thick','fit','measure','dimensions')),
 ('安装与使用',('安装','怎么用','怎么挂','assemble','install','mount','hang','attach')),
 ('价格与购买',('价格','多少','购买','链接','price','cost','where to buy','link','how much','order')),
 ('承重与耐用',('承重','耐用','易坏','材质','weight','load','durable','break','material')),
 ('地区与配送',('运费','配送','发货','shipping','deliver','ship')))


def obj(raw):
    try:v=json.loads(raw) if isinstance(raw,str) else raw
    except ValueError:return {}
    return v if isinstance(v,dict) else {}


def short(s,n=260):return ' '.join(s.split())[:n] if isinstance(s,str) else ''


def override(db,gid):
    r=db.execute('SELECT category FROM own_goods_research_category WHERE goods=?',(gid,)).fetchone()
    return r[0] if r else ''


def custom_exact(label, raw):
    return any(norm(x)==norm(label) for x in raw)


def sources_for_goods(db,gid,pid):
    source=defaultdict(list)
    if pid:
        for r in db.execute(f'''SELECT DISTINCT iv.video,iv.origin FROM intel_goods_video iv
          JOIN intel_goods g ON g.id=iv.product JOIN video_cases c ON c.video=iv.video
          WHERE iv.product=? AND iv.origin IN ('Apify','Kalodata') AND {CASE_VISIBLE}
          ORDER BY c.updated DESC,iv.video,iv.origin''',(pid,)):
            source[r['video']].append(r['origin'])
    links={r['ref']:r['relation'] for r in db.execute(f'''SELECT l.ref,l.relation FROM own_goods_links l JOIN video_cases c ON c.id=l.ref
       WHERE l.goods=? AND l.kind='case' AND {CASE_VISIBLE} ORDER BY l.created DESC''',(gid,))}
    excluded={r['id']:r['video'] for r in db.execute(f'''SELECT c.id,c.video FROM own_goods_research_exclusions e JOIN video_cases c ON c.id=e.case_id
        WHERE e.goods=? AND e.excluded=1 AND {CASE_VISIBLE} ORDER BY c.updated DESC,c.id''',(gid,))}
    return source,links,excluded


def candidates(db,goods,profile):
    same,manual,excluded=sources_for_goods(db,goods['id'],profile['product_id'])
    decisions=review_index(db,'case')
    goods_context=[t for t in profile['tags'] if t['label'] in CONTEXT and t['decision']!='rejected']
    fields='''c.id,c.video,c.handle,c.url,c.updated,json_extract(c.human,'$.tag_groups') htags,
      coalesce(json_extract(c.human,'$.opening'),json_extract(c.ai,'$.fields.opening'),'') opening,
      coalesce(json_extract(c.human,'$.audience_scenario'),json_extract(c.ai,'$.fields.audience_scenario'),'') scene,
      json_extract(c.human,'$.category') hcat,json_extract(c.ai,'$.generated_at') ai_at,
      json_extract(c.ai,'$.fields.tag_groups') atags,json_extract(c.ai,'$.fields.product_category') acat,
      json_type(c.human,'$.tag_groups') htags_type,json_type(c.human,'$.category') hcat_type'''
    recent=db.execute(f'SELECT {fields} FROM video_cases c WHERE {CASE_VISIBLE} ORDER BY c.updated DESC,c.id').fetchall()
    ranked=[];seen=set();category=profile['category']
    allow_category=all(t['decision']!='rejected' for t in profile['tags'] if t['kind']=='细品类')
    rows=recent
    titles=linked_titles(db,(row['video'] for row in rows))
    for c in rows:
        if c['video'] in seen:continue
        seen.add(c['video']);manual_relation=manual.get(c['id']);verified=same.get(c['video']);
        human={k:v for k,v,exists in (('tag_groups',obj(c['htags']),c['htags_type']),('category',c['hcat'],c['hcat_type'])) if exists}
        labels,basis,raw=resolved_case_category(human,{'generated_at':c['ai_at'],'fields':{'tag_groups':obj(c['atags']),'product_category':c['acat']}},titles.get(c['video'],''))
        overlap=labels.get(category) or (category if profile['override'] and custom_exact(category,raw) else '')
        denied=decisions.get(c['id'],{})
        if denied.get(tag_key('细品类',category))=='rejected' or not allow_category:overlap=''
        context=next((t['label'] for t in goods_context if any(contains(norm(c['scene']),w) for w in CONTEXT[t['label']])),None)
        actions=[a for a in specific_actions(str(c['opening'])) if denied.get(tag_key('内容玩法',a))!='rejected']
        if verified:
            match={'kind':'identity','label':'相同 TikTok Shop 商品 ID','reason':f'自营商品链接的商品 ID {profile["product_id"]} 与该视频已有商品记录一致（{"、".join(verified)}）。不代表同一 SKU、同一订单或全部视频销量归属于该商品。'};rank=0
        elif overlap:
            match={'kind':'category','label':'同细品类 · 不等于同款','reason':f'自营细品类「{category}」（{profile["reason"]}）；该视频的{basis}中有「{overlap}」。规格、品牌、市场和适配性仍需核对。'};rank=1 if human else 2
        elif manual_relation:
            relation={'same':'人工标记同款（系统未核实）','similar':'人工标记相似款','analogy':'人工标记场景 / 痛点类比'}[manual_relation]
            match={'kind':'manual','label':relation,'reason':'这是团队手动加入的参考，未凭自动规则认定为同品类，不纳入下方的同类汇总。'};rank=3
        elif context and actions and not uncertain_scene(c['scene']):
            match={'kind':'analogy','label':'跨品类拍法线索','reason':f'商品档案和案例场景共有「{context}」，案例开场有「{actions[0]}」。仅作拍法参考。'};rank=4
        else:continue
        if c['id'] in excluded and match['kind']!='manual':
            if not manual_relation:continue
            match={'kind':'manual','label':'手动参考（已排除自动关联）','reason':'原手动参考保留；不纳入同类汇总。'};rank=3
        ranked.append((rank,-c['updated'],c['id'],dict(c,listing_title=titles.get(c['video'],'')),match))
    ranked.sort(key=lambda r:r[:3])
    hidden=[{'id':cid,'video':vid} for cid,vid in list(excluded.items())[:REPORT_LIMIT]]
    return [(r[3],r[4]) for r in ranked],len(ranked),hidden,len(recent),False


def iso_date(value):
    if not isinstance(value,str):return None
    try:return date.fromisoformat(value[:10].replace('/','-'))
    except ValueError:return None


def format_key(value):
    n=norm(value)
    if not n or len(n)>55 or n in {'演示','其他','未知','未提供','不确定','短视频','视频','video','other'} or re.search(r'未知|待核|无依据|不确定|无法|未能|可能',n):return ''
    return next((key for key,aliases in FORMAT_ALIASES.items() if n in aliases),n)


def case_shops(db,vid):
    # These are shop IDs on existing video-to-product edges, not verified sellers of this one SKU.
    return [dict(r) for r in db.execute('''SELECT DISTINCT g.shop id,coalesce(max(nullif(g.shop_name,'')),'') name
        FROM intel_goods_video iv JOIN intel_goods g ON g.id=iv.product
        WHERE iv.video=? AND g.shop<>'' AND iv.origin IN ('Apify','Kalodata') GROUP BY g.shop ORDER BY g.shop LIMIT 20''',(vid,))]


def utc_day(epoch):
    v=numeric(epoch)
    if v is None:return None
    try:return datetime.fromtimestamp(v,timezone.utc).date()
    except (ValueError,OSError,OverflowError):return None


def delta_views(db,c,now):
    # No remote request. Both observations must be on the same account and stored in the last 30 days.
    rows=db.execute('''SELECT s.account,s.views,s.collected FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account
        JOIN users u ON u.id=a.owner AND u.enabled=1
        WHERE s.video=? AND a.handle=? COLLATE NOCASE AND a.deleted_at IS NULL AND s.views IS NOT NULL
        AND s.collected BETWEEN ? AND ? ORDER BY s.collected DESC LIMIT 120''',(c['video'],c['handle'],now-30*DAY,now)).fetchall()
    if not rows:return None
    new=rows[0]
    if now-new['collected']>7*DAY:return None
    old=next((s for s in rows if s['account']==new['account'] and new['collected']-s['collected']>=DAY),None)
    if old is None or not 0<=old['views']<=new['views']:return None
    return {'before':old['views'],'after':new['views'],'gain':new['views']-old['views'],'start':old['collected'],'end':new['collected'],
            'pct':round((new['views']-old['views'])*100/old['views'],1) if old['views'] else None}


def faq_pairs(groups,rows,transcript):
    # Only surface potentially relevant passages. Keyword absence never means the video failed to answer.
    spans=[short(s,270) for s in re.split(r'[\n。！？!?]+',transcript[:10000]) if s.strip()]
    by_id={s['cid']:s for s in rows};out=[]
    for g in groups[:5]:
        question=g['label']+' '+' '.join(by_id[i]['text'] for i in g['ids'] if i in by_id)[:1000]
        relevant=[]
        for label,words in FAQ_WORDS:
            if any(contains(norm(question),w) for w in words):
                passage=next((s for s in spans if any(contains(norm(s),w) for w in words)),None)
                if passage and passage not in relevant:relevant.append(passage)
        out.append({'label':g['label'],'passages':relevant[:2]})
    return out


def ready_projection(job,marked,rows):
    if not job:return {'state':'not_sampled','ai_state':'','research_state':'','comments':0,'replies':0,'topics':[]},None
    packed=read_pack(marked['payload'],rows) if marked and marked['state']=='ready' and job['ai_state']=='ready' else None
    topic=[];ids={r['cid']:r for r in rows};mains={c for c,r in ids.items() if not r['parent']};replies=set(ids)-mains
    for raw in json.loads(job['topics'])[:6] if job['ai_state']=='ready' else []:
        def count(key):
            subset=set(raw.get(key,[])) & set(ids)
            return {'comments':bucket(len(mains & subset),len(mains)),'replies':bucket(len(replies & subset),len(replies)),
                    'quotes':[ids[i] for i in sorted(subset)[:2]]}
        topic.append({'label':short(raw.get('label'),100),'support':count('support'),'counter':count('counter')})
    return {'state':job['state'],'ai_state':job['ai_state'],'research_state':marked['state'] if marked and (packed or marked['state']!='ready') else ('stale' if marked else 'legacy' if job['ai_state']=='ready' and rows else ''),
            'comments':len(mains),'replies':len(replies),'topics':topic,'observed':job['finished'],'error':job['error'],
            'ai_error':job['ai_error'],'research_error':marked['error'] if marked else ''},packed


def video_sample(db,c,match,now,market):
    row=dict(db.execute('SELECT source,human,ai,handle,transcript,transcript_source FROM video_cases WHERE id=?',(c['id'],)).fetchone())
    row.update({k:obj(row[k]) for k in ('source','human','ai')});fields=field_projection(row)
    s=row['source'];k=obj(s.get('kalodata'));title=short(fields['title']['value'],200) or '@'+c['handle']
    publ=iso_date(fields['published_at']['value']);today=utc_day(now)
    age=(today-publ).days if publ and publ<=today else None
    # Cumulative public fields from one observation only. Never divide a Kalodata numerator by Apify views.
    when=numeric(s.get('collected'));snap_origin=short(s.get('origin'),50)
    snapshot_valid=bool(snap_origin in SNAPSHOT_ORIGINS and when and when<=now)
    public=[{'key':key,'label':label,'value':numeric(s.get(skey))} for key,label,_,_,skey in METRICS if skey] if snapshot_valid else []
    snapshot={m['key']:m['value'] for m in public};view=snapshot.get('views')
    at_day=utc_day(when) if snapshot_valid else None
    # For cumulative comparisons prefer the actual published timestamp carried by that public source.
    # A date from another provider has no UTC offset; allow explicit manual dates, not implicit time zone conversion.
    snap_publ=publ if 'published_at' in row['human'] else utc_day(s.get('published'))
    snapshot_age=(at_day-snap_publ).days if at_day and snap_publ and snap_publ<=at_day else None
    flags=performance_matches(snapshot,THRESHOLDS) if view is not None else []
    testable=bool(flags) or view is not None and (view<10000 or all(snapshot.get(key) is not None and snapshot[key]<=view for key in THRESHOLDS))
    age_band=('0–7天' if snapshot_age<=7 else '8–30天' if snapshot_age<=30 else '31–90天' if snapshot_age<=90 else '') if snapshot_age is not None else ''
    job=db.execute('SELECT * FROM comment_sample_jobs WHERE video=?',(c['video'],)).fetchone()
    marked=db.execute('SELECT * FROM comment_sample_research WHERE video=?',(c['video'],)).fetchone() if job else None
    rows=[dict(r) for r in db.execute('SELECT cid,parent,text,published FROM comment_sample_text WHERE video=? ORDER BY ordinal,cid',(c['video'],))] if job else []
    comments,annotation=ready_projection(job,marked,rows)
    stats={key:{'value':short(fields[key]['value'],320),'source':fields[key]['source'],'evidence':short(fields[key]['evidence'],260)} for key in ('summary','content_type','audience_scenario','category','opening','ending','replication_actions','expression') if not fields[key]['missing']}
    for field,claim,start,end in db.execute('SELECT field,claim,start,end FROM video_case_clip_reviews WHERE case_id=?',(c['id'],)):
        if field in stats and fields[field]['value']==claim:
            stats[field]['clip']=[start,end]
    estimate=None
    if k.get('provider')=='Kalodata' or k.get('data_type')=='third_party_estimate':
        estimate={'units':numeric(k.get('units')),'gmv':numeric(k.get('gmv')),'product_count':numeric(k.get('product_count')),
                  'region':short(k.get('region'),12),'start':short(k.get('period_start'),30),'end':short(k.get('period_end'),30),
                  'currency':short(k.get('currency'),6),'collected':numeric(k.get('collected')),'endpoint':'Kalodata /video/detail'}
    trends=delta_views(db,c,now)
    transcript=fields['transcript']['value']
    return {'id':c['id'],'video':c['video'],'title':title,'handle':c['handle'],'url':c['url'],'match':match,'video_content':stats,'duration':numeric(s.get('duration')),'thumb':f'/api/intelligence/cases/{c["id"]}/cover' if s.get('cover') else '',
            'tags':review_tags(db,'case',c['id'],video_tags(row['human'],row['ai'],c.get('listing_title',''))),'shops':case_shops(db,c['video']),
            'metrics':metric_projection(row),'public':public,'estimate':estimate,'published':publ.isoformat() if publ else '',
            'published_source':fields['published_at']['source'],'age':age,'trend':trends,
            'views_snapshot':view,'snap_time':when if snapshot_valid else None,'snap_scope':snap_origin,'snap_age_band':age_band,'threshold_testable':testable,
            'performance_flags':flags,'comments':comments,'text_source':fields['transcript']['source'],
            'has_transcript':bool(transcript),'faq':faq_pairs(annotation['signals']['question'],rows,transcript or '') if annotation else [],
            'market_conflict':bool(estimate and estimate['region'] and estimate['region']!=market)},rows,annotation


def counts(keys,all_rows):
    tops={key for key,r in all_rows.items() if not r['parent']};replies=set(all_rows)-tops
    return {'comments':bucket(len(keys & tops),len(tops)),'replies':bucket(len(keys & replies),len(replies))}


def quote_examples(keys,rows):
    # Prefer a different video for each example, then a different role in the same video.
    ranked=sorted(keys);picked=[];scope=set()
    for distinct in (lambda i:i[0],lambda i:(i[0],bool(rows[i]['parent']))):
        scope={distinct(i) for i in picked}
        for i in ranked:
            if len(picked)==3:return picked
            k=distinct(i)
            if k in scope:continue
            picked.append(i);scope.add(k)
    return (picked+[i for i in ranked if i not in picked])[:3]


def signal_rollup(data):
    all_rows={};linked=defaultdict(lambda:defaultdict(set))
    for item,rows,annotation in data:
        if not annotation:continue
        vid=item['video'];all_rows.update({(vid,r['cid']):dict(r,case_id=item['id'],video=vid) for r in rows})
        for key,groups in annotation['signals'].items():
            for group in groups:
                linked[key][group['label']].update((vid,cid) for cid in group['ids'])
    result={}
    for key in SIGNALS:
        groups=linked[key];all_ids=set().union(*groups.values())
        ordered=sorted(groups,key=lambda x:(-len(groups[x]),x))
        result[key]={'label':SIGNAL_LABELS[key],**counts(all_ids,all_rows),'group_count':len(ordered),
                     'groups':[{'label':label,**counts(groups[label],all_rows),
                       'cases':sorted({all_rows[i]['case_id'] for i in groups[label]}),
                       'quotes':[all_rows[i] for i in quote_examples(groups[label],all_rows)]} for label in ordered[:5]]}
    return result


def report_structure(data,market):
    pool=[item for item,_,_ in data];metrics=[v for v in pool if v['views_snapshot'] is not None]
    known=[v for v in pool if v['age'] is not None];recent=[v for v in known if v['age']<=30]
    shop_cases=[v for v in pool if v['shops']]
    accounts={v['handle'].casefold() for v in pool if v['handle']}
    # Keep unlike time windows separate. Counts below are videos with some estimate, never order totals.
    windows=defaultdict(list)
    for v in pool:
        e=v['estimate']
        if not e or e['region']!=market or e['units'] is None:continue
        start,end=iso_date(e['start']),iso_date(e['end'])
        if start and end and start<=end:windows[(start.isoformat(),end.isoformat())].append(v)
    estimate=[{'start':start,'end':end,'reported':len(vs),'positive':sum(v['estimate']['units']>0 for v in vs),
               'cases':[v['id'] for v in vs]} for (start,end),vs in sorted(windows.items(),key=lambda pair:pair[0][1],reverse=True)]
    # Compare observations in the same sample week and at a similar age, not one video's peak to today's uploads.
    by_age=defaultdict(list);formats=defaultdict(list)
    for v in metrics:
        if v['handle'] and v['snap_age_band']:
            week=utc_day(v['snap_time']).isocalendar()
            group=(f'{week.year}-W{week.week:02d}',v['snap_age_band'])
            by_age[group].append(v)
            name=format_key(v['video_content'].get('content_type',{}).get('value',''))
            if v['threshold_testable'] and name:formats[(*group,name)].append(v)
    concentration=[]
    for (week,band),items in by_age.items():
        table=Counter()
        for v in items:table[v['handle'].casefold()]+=v['views_snapshot']
        total=int(sum(table.values()))
        if len(table)>1 and total:
            h,n=table.most_common(1)[0]
            concentration.append({'week':week,'band':band,'account':h,'accounts':len(table),'videos':len(items),'share':bucket(int(n),total),
                                  'cases':[v['id'] for v in items]})
    recurrence=[]
    for (week,band,name),items in formats.items():
        positives=[v for v in items if v['performance_flags']]
        total={v['handle'].casefold() for v in items};ok={v['handle'].casefold() for v in positives}
        recurrence.append({'kind':name if name in FORMAT_ALIASES else items[0]['video_content']['content_type']['value'],
                           'week':week,'band':band,'accounts':bucket(len(ok),len(total)),
                           'videos':bucket(len(positives),len(items)),'cases':[v['id'] for v in items],'repeated':len(ok)>=2})
    trends=[v for v in pool if v['trend']];old=[v for v in trends if v['age'] is not None and v['age']>30]
    return {'videos':len(pool),'accounts':len(accounts),'shop_videos':len(shop_cases),'shops':len({s['id'] for v in shop_cases for s in v['shops']}),
            'baseline_videos':len(metrics),'estimate_windows':estimate,
            'analysed_videos':sum(bool(a) for _,_,a in data),'sampled_videos':sum(bool(r) for _,r,_ in data),'recent':bucket(len(recent),len(known)),
            'fresh_growth_old':bucket(sum(v['trend']['gain']>0 for v in old),len(old)),
            'comparable_trends':len(trends),'concentration':sorted(concentration,key=lambda x:(x['week'],x['videos']),reverse=True)[:5],
            'formats':sorted(recurrence,key=lambda x:(not x['repeated'],-x['accounts']['hits'],-x['accounts']['total'],x['kind']))[:8]}


def build(db,goods,now=None):
    now=time.time() if now is None else now
    profile=dossier_profile(db,goods,override(db,goods['id']))
    profile['tags']=review_tags(db,'goods',goods['id'],profile['tags'])
    rows,total,excluded,scanned,bounded=candidates(db,goods,profile)
    data=[video_sample(db,c,match,now,goods['market']) for c,match in rows]
    same=[x for x in data if x[0]['match']['kind'] in ('identity','category') and not x[0]['market_conflict']]
    # The aggregate excludes manual analogies and explicitly different markets. Unknown comment regions remain unknown.
    case_reports=[]
    for v,text,marks in data:
        v['included']=v['match']['kind'] in ('identity','category') and not v['market_conflict']
        v['baseline']=peer_baseline(db,v) if v['included'] else None
        v['signals']=signal_rollup([(v,text,marks)]) if marks else None
        case_reports.append(v)
    cfg=db.execute('SELECT collect,ai,collect_error,ai_error FROM comment_sample_config WHERE id=1').fetchone()
    return {'methods':method_reports(data,goods,profile,signal_rollup,format_key),'profile':profile,'dimensions':[{'key':k,'title':title,'signals':list(signals)} for k,title,signals in DIMENSIONS],
            'coverage':report_structure(same,goods['market']),'signals':signal_rollup(same),'cases':case_reports,'excluded':excluded,
            'scope':{'matched':total,'shown':len(rows),'limit':len(rows),'scanned':scanned,'bounded':bounded,'market':goods['market'],'as_of':now},
            'queues':dict(cfg) if cfg else {}}


def attach(app,hub,user,body):
    from own_goods import PREFIX,can_edit
    @app.get(PREFIX+'/{gid}/research')
    def read_report(gid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            db.execute('BEGIN')
            g=get_goods(db,gid);report=build(db,g)
        return report|{'can_edit':can_edit(g,u),'is_admin':u['role']=='admin'}

    @app.post(PREFIX+'/{gid}/research/exclusion')
    async def exclude_case(gid:str,request:Request):
        from video_cases import require_case
        u=user(request);d=await body(request);case=d.get('case_id');excluded=d.get('excluded')
        if not isinstance(case,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',case) or type(excluded) is not bool:
            raise HTTPException(400,'请选择有效案例与排除状态')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');g=get_goods(db,gid);require_editor(g,u);require_case(db,case)
            db.execute('''INSERT INTO own_goods_research_exclusions(goods,case_id,excluded) VALUES(?,?,?)
                        ON CONFLICT(goods,case_id) DO UPDATE SET excluded=excluded.excluded''',(gid,case,int(excluded)))
            hub.log(db,u['id'],'own_goods_research_exclusion',gid)
        return {'excluded':excluded}
