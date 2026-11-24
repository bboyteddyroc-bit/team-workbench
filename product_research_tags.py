"""Explainable product labels. No inferred category from URLs outside the known product path."""
import json
import re
import unicodedata

from tiktok_shop_link import listing_parts

# Fine categories only. Broad terms such as 家居, 服饰, and 工具 never connect videos.
CATALOG = {
    '挂烫机': ('吸烫机','吸附式挂烫机','挂烫机','蒸汽挂烫器','garment steamer','clothes steamer','steamer for clothes','fabric steamer'),
    '真空收纳袋': ('真空收纳袋','真空压缩袋','衣物真空袋','vacuum storage bags','vacuum storage bag','travel vacuum bags','vacuum bags for clothes','vacuum compression bags'),
    '脏衣篮': ('脏衣篮','脏衣篓','洗衣篮','脏衣袋','laundry hamper','laundry basket','laundry bag','clothes hamper'),
    '篮球架': ('篮球架','篮球框','basketball hoop','basketball goal','basketball rim'),
    '水槽收纳架': ('水槽架','水槽收纳架','水槽置物架','水槽收纳','sink caddy','sink organizer','sink rack'),
    '碗碟沥水架': ('碗碟架','碗碟沥水架','碗碟置物架','dish rack','dish drying rack','dish drainer'),
    '衣柜挂袋': ('衣柜挂袋','衣柜悬挂收纳','hanging closet organizer','closet organizer'),
    '保温杯': ('保温杯','保温瓶','真空杯','保温水杯','insulated cup','insulated tumbler','thermos','vacuum flask'),
    '红酒杯': ('红酒杯','葡萄酒杯','wine glass','stemware'),
    '围巾': ('围巾','围脖','scarf','scarves','neck warmer'),
    '滑雪面罩': ('滑雪面罩','滑雪头套','保暖头套','ski mask','balaclava'),
    '面膜': ('面膜','sheet mask','facial mask','face mask skincare'),
    '护肤套装': ('护肤套装','护肤套组','skincare set','skincare kit'),
    '手机充电器': ('手机充电器','氮化镓快充','氮化镓充电器','phone charger','gan charger','usb c charger'),
    '无线耳机': ('无线耳机','蓝牙耳机','wireless earbuds','bluetooth headphones'),
    '除雪工具': ('除雪工具','清雪工具','清雪铲','雪铲','snow shovel','snow blower','snow removal'),
    '吹叶机': ('吹叶机','吹风清叶机','leaf blower'),
    '松土器': ('松土器','松土耙','松土机','中耕机','garden cultivator','garden tiller','soil cultivator','soil tiller','hand cultivator','cordless tiller','electric tiller','rototiller'),
    '电动剪刀': ('电动剪刀','电动裁布剪','充电剪刀','electric scissors','cordless scissors','electric fabric shears'),
    '车载手机支架': ('车载手机支架','汽车手机支架','car phone mount','car phone holder'),
    '汽车清洁刷': ('汽车清洁刷','洗车刷','car detailing brush','car wash brush'),
    '汽车外观配件': ('汽车外观配件','汽车装饰件','car exterior trim'),
    '宠物饮水机': ('宠物饮水机','猫咪饮水机','pet water fountain','cat water fountain'),
    '宠物脱毛刷': ('宠物脱毛刷','宠物除毛刷','宠物梳毛刷','pet grooming brush','pet deshedding brush'),
    '运动内衣': ('运动内衣','运动文胸','sports bra'),
    '瑜伽裤': ('瑜伽裤','yoga pants','yoga leggings'),
    '餐具套装': ('餐具套装','不锈钢餐具套装','flatware set','silverware set','cutlery set'),
}
CONTEXT = {
    '门后/悬挂': ('门后','门背','挂门','悬挂','over the door','door mounted','hanging'),
    '小空间': ('小空间','省空间','窄空间','节省空间','space saving','small space','compact'),
    '洗衣收纳': ('洗衣','脏衣','laundry'),
    '厨房/水槽': ('厨房','水槽','kitchen','sink'),
    '户外': ('户外','庭院','outdoor','outdoors','yard'),
    '保温': ('保温','insulated','insulation'),
    '送礼': ('送礼','礼物','gift'),
}
FEATURES = {
    '可折叠': ('可折叠','折叠式','foldable','collapsible'),
    '带提手': ('带提手','双提手','带手柄','carry handles','carrying handle'),
    '带滚轮': ('带滚轮','自带轮','on wheels','rolling wheels'),
    '可拆洗': ('可拆洗','可拆卸清洗','removable washable'),
}
# Neutral mentions (including "无提手" or "不折叠") prevent vendor claims
# from competing with a member's recorded specification on the same feature.
FEATURE_MENTIONS = {'可折叠':('折叠','fold','folding'), '带提手':('提手','手柄','handle','handles'),
                    '带滚轮':('滚轮','轮子','wheels','casters'), '可拆洗':('拆洗','拆卸清洗','washable')}
NEGATED = re.compile(r'不支持|不可|不能|无提手|不带|非折叠|没有|\b(?:no|not|without|non)\b',re.I)


def supported_alias(value,aliases):
    for clause in re.split(r'[。！？；;，,\n]',str(value or '')):
        if uncertain(clause) or NEGATED.search(clause):continue
        for alias in aliases:
            if contains(norm(clause),alias):return alias
    return ''


BROAD = {'家居','家居用品','生活家居用品','家居收纳','收纳','清洁','服饰','服装','工具','五金工具','家居园艺',
         '数码','电子','个护','美妆','食品','宠物','礼品','厨具','厨房用品','餐厨用品','餐具','汽车用品','运动','体育用品',
         '饮具','杯具','饰品','户外','产品','其他','商品','通用','未知','home','tools','storage','electronics','sports','accessories','other'}


def norm(s):
    return ' '.join(re.sub(r'[^\w\u3400-\u9fff]+|_+', ' ', unicodedata.normalize('NFKC',str(s or '')).casefold()).split())


def contains(normal, alias):
    a=norm(alias)
    if re.search(r'[\u3400-\u9fff]', a):return a in normal
    return (' '+a+' ') in (' '+normal+' ')


def uncertain(value):
    return (any(x in value for x in ('未知','不确定','推测','可能是','商品待核','品类待核','名称待核','无法确认','未确认','未证实','无法判断','未展示','不是'))
            or any(contains(norm(value),x) for x in ('unknown','maybe','possibly','unconfirmed','not a','not an')))


def primary(value):
    return re.split(r'\bwith\b|附带|配有|造型为',str(value or '').replace('-',' '),1,flags=re.I)[0]


def hits(value):
    n=norm(primary(value));out={}
    if uncertain(n):return out
    for k,aliases in CATALOG.items():
        a=next((a for a in aliases if contains(n,a)),None)
        if a:out[k]=a
    return out


def custom_category(value):
    clean=' '.join(unicodedata.normalize('NFKC', value).split())
    if not clean:return ''
    n=norm(clean)
    if len(clean)>36 or len(n)<2 or n in BROAD or len(hits(clean))>1 or any(x in clean for x in '/|、;；,，') or uncertain(clean):
        raise ValueError('请填写一个具体细品类，如「门后收纳袋」，不要填「家居」或多个品类。留空则自动识别。')
    return next((label for label,names in CATALOG.items() if any(norm(a)==n for a in names)),clean)


def product_profile(goods,override='',lookup=None,confirmed=()):
    raw_slug,raw_pid=listing_parts(goods['url'],goods.get('market'))
    slug,pid=raw_slug,raw_pid
    listing_field='商品链接名称'
    lookup=lookup or {}
    resolved_slug,resolved_pid=listing_parts(lookup.get('resolved_url'),goods.get('market'))
    if resolved_pid and resolved_pid==lookup.get('product_id') and (not raw_pid or raw_pid==resolved_pid):
        slug,pid=resolved_slug,resolved_pid
        if not raw_pid:listing_field='短链展开后的商品链接名称'
    remote=json.loads(lookup['metadata']) if lookup.get('state')=='ready' and pid and pid==resolved_pid else {}
    fields=(('商品名称',goods['name']),(listing_field,slug),('已录入规格',goods.get('facts','')))
    provider_fields=(('Kalodata 商品名称',remote.get('name','')),('Kalodata 类目',remote.get('category','')))
    title,link,facts=[hits(text) for _,text in fields]
    provider_hits={}
    for field,value in provider_fields:
        for label,alias in hits(value).items():
            if supported_alias(value,[alias]):provider_hits.setdefault(label,(field,alias))
    tag=evidence=origin=note=''
    local_hits=set(title)|set(link)|set(facts)
    extra_hits=set(provider_hits) | (set(link) if not raw_pid else set())
    local_sources={label:(field,alias) for field,matches in (
        (listing_field,link),('商品名称',title),('已录入规格',facts)) for label,alias in matches.items()}
    reviewed=set(confirmed) & local_sources.keys()
    if override:
        tag,origin,evidence=override,'人工标签','商品档案中明确指定的细品类'
    elif len(reviewed)==1:
        tag=next(iter(reviewed));origin='已确认标签'
        field,alias=local_sources[tag];evidence=f'{field}包含「{alias}」'
    elif len(link)==1 and (not title or set(title)<=set(link) or (norm(goods['name']) and contains(norm(slug),goods['name']))) and (not facts or set(link)==set(facts)):
        tag=next(iter(link));origin='自动标签';evidence=f'{listing_field}包含「{link[tag]}」'
    elif len(title)==1 and (not link or set(link)==set(title)) and (not facts or set(facts)==set(title)):
        tag=next(iter(title));origin='自动标签';evidence=f'商品名称包含「{title[tag]}」'
    elif not title and not link and len(facts)==1:
        tag=next(iter(facts));origin='自动标签';evidence=f'已录入规格包含「{facts[tag]}」'
    if tag and extra_hits-{tag}:
        if override or tag in reviewed:
            note='取回的资料与已核对品类不一致，保留人工结论。'
        else:
            tag=evidence=origin=''
            note='取回的资料与档案信息指向不同细品类，请核对后指定一个细品类。'
    elif not tag and not local_hits and len(provider_hits)==1:
        tag=next(iter(provider_hits));origin='Kalodata 资料打标'
        field,alias=provider_hits[tag];evidence=f'{field}包含「{alias}」 · 商品 ID {pid}'
    elif not tag and extra_hits and len(local_hits|extra_hits)>1:
        note='现有资料指向多个细品类，请在商品档案中核对。'
    tags=([{'label':tag,'kind':'细品类','source':evidence}] if tag else [])
    derived=remote if not note else {}
    claim_fields=(('Kalodata 商品名称',derived.get('name','')),('Kalodata 商品描述',derived.get('description','')))
    contexts=fields+(provider_fields+(claim_fields[1],) if derived else ())
    manual_facts=goods.get('facts','')
    for label,aliases in CONTEXT.items():
        marker=next(((field,a) for field,value in contexts for a in aliases if supported_alias(value,[a])),None)
        if marker:
            source=f'{marker[0]}包含「{marker[1]}」'
            if marker[0].startswith('Kalodata'):source+=f' · 商品 ID {pid}，待核实'
            tags.append({'label':label,'kind':'场景/特征','source':source})
    for label,aliases in FEATURES.items():
        marker=supported_alias(manual_facts,aliases)
        if marker:
            tags.append({'label':label,'kind':'商品特征','source':f'商品档案规格包含「{marker}」'})
        elif derived and not any(contains(norm(manual_facts),a) for a in aliases+FEATURE_MENTIONS[label]):
            for field,value in claim_fields:
                if marker:=supported_alias(value,aliases):
                    tags.append({'label':label,'kind':'商品页标称','source':f'{field}包含「{marker}」 · 商品 ID {pid}，待核实'})
                    break
    # Listing titles are seller claims. Preserve the literal match for review and keep
    # them separate from measurements entered by the team.
    listing_sources=((listing_field,slug),)+claim_fields if not note else ((listing_field,raw_slug),)
    for field,pattern,unit in (
        ('标称功率',r'\b(\d{1,5})\s*w(?:att[s]?)?\b','W'),
        ('水箱容量',r'\b(\d{1,5})\s*ml\s+(?:water\s+)?tank\b','mL'),
        ('预热时间',r'\b(\d{1,3})\s*(?:s|sec|seconds?)\s+heat\s+up\b','秒'),
        ('包装数量',r'\b(\d{1,3})\s+pack\b','件装')):
        # Multiple different advertised measurements are ambiguous, not a verified spec.
        claims={m[1]:(source,m[0]) for source,value in reversed(listing_sources)
                for m in re.finditer(pattern,norm(value)) if int(m[1])>0}
        if len(claims)==1:
            amount,(source,phrase)=next(iter(claims.items()))
            tags.append({'label':f'{field} {amount} {unit}','kind':'商品页标称',
                         'source':f'{source}含「{phrase}」，待核实'})
    if tag=='真空收纳袋' and supported_alias(raw_slug if note else slug,['with pump']):
        tags.append({'label':'配抽气泵','kind':'商品页标称','source':f'{listing_field}含「with pump」，待核实'})
    reason=evidence or note or ('商品录入信息指向不止一个细品类，请确认。' if local_hits else '未识别细品类，可在编辑档案时补充。')
    return {'category':tag,'origin':origin or '待确认','reason':reason,'notice':note,'tags':tags,'override':override,'product_id':pid}


def case_category(human,ai):
    if 'tag_groups' in human or 'category' in human:
        groups=human.get('tag_groups') or {};values=groups.get('product',[]) if isinstance(groups,dict) else []
        text=human.get('category','');origin='人工案例标签'
    else:
        f=ai.get('fields') or {};groups=f.get('tag_groups') or {};values=groups.get('product',[]) if isinstance(groups,dict) else []
        text=f.get('product_category','');origin='AI 视频分析 · 待核对'
        if not ai.get('generated_at'):return {},'',[]
    values=(values if isinstance(values,list) else [])+(re.split(r'[/、|；;]',text) if isinstance(text,str) else [])
    seen={};raw=[]
    for s in values[:24]:
        if not isinstance(s,str):continue
        s=s.strip()[:125]
        if not s or not norm(s) or norm(s) in BROAD or uncertain(s):continue
        if s not in raw:raw.append(s)
        for label in hits(s):seen.setdefault(label,s)
    # Multiple incompatible fine categories without a verified item edge are not a clean match.
    if len(seen)>1:return {},origin,[]
    return seen,origin,raw


def linked_titles(db,videos):
    """Only a single identified listing can describe a video's product unambiguously."""
    videos=list(set(videos)); result={}
    for start in range(0,len(videos),400):
        batch=videos[start:start+400]
        marks=','.join('?' for _ in batch)
        rows=db.execute(f"""SELECT v.video,MAX(g.name) name FROM intel_goods_video v
            LEFT JOIN intel_goods g ON g.id=v.product WHERE v.video IN ({marks})
            AND v.origin IN ('Apify','Kalodata') GROUP BY v.video
            HAVING COUNT(DISTINCT v.product)=1 AND MAX(g.name)<>''""",batch)
        result.update((r['video'],r['name']) for r in rows)
    return result


def resolved_case_category(human,ai,listing=''):
    labels,origin,raw=case_category(human,ai)
    if labels or raw or 'tag_groups' in human or 'category' in human or not listing:
        return labels,origin,raw
    fields=ai.get('fields') or {}
    values=(fields.get('tag_groups') or {}).get('product',[]) if isinstance(fields.get('tag_groups'),dict) else []
    if len({k for v in [fields.get('product_category',''),*(values if isinstance(values,list) else [])] for k in hits(v)})>1:
        return labels,origin,raw
    product=hits(listing)
    if len(product)==1:
        return product,'平台关联的唯一商品名称',[listing]
    return labels,origin,raw
