"""Team-owned product dossiers and locally computed, traceable research conclusions."""
import hashlib
import json
import re
import time
import unicodedata
import uuid
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, Request
import research_tag_review as reviews
from own_goods_lookup import attach as attach_lookup, dossier_profile, initialize as initialize_lookup, latest as latest_lookup, status as lookup_status
from product_research_tags import custom_category, linked_titles

PREFIX = '/api/intelligence/own-goods'
KINDS = {'comment':'视频评论','review':'商品评价','search':'搜索线索','video':'视频内容核查','own':'自家商品核实'}
RELATIONS = {'same':'同款','similar':'相似款','analogy':'场景或痛点类比'}
SIDES = {'support':'支持','counter':'反例','context':'背景'}


def upstream(source):
    p=urlsplit(source)
    if p.hostname in ('tiktok.com','www.tiktok.com','m.tiktok.com'):
        video=re.search(r'/video/(\d+)(?:/|$)',p.path)
        if video:return 'tiktok:video:'+video[1]
        product=re.search(r'/(?:product|pdp)/(?:[^/]+/)?(\d+)(?:/|$)',p.path)
        if product:return 'tiktok:product:'+product[1]
    return urlunsplit(p._replace(path=p.path.rstrip('/'),query='')) if source else ''


def sample_counts(d):
    total, hits = d.get('sample_total'), d.get('sample_hits')
    if total is None and hits is None:return None,None
    if type(total) is not int or type(hits) is not int or not 0<=hits<=total<=1000000 or not total:
        raise HTTPException(400,'命中数和样本总数须成对填写，且 0 ≤ 命中数 ≤ 样本总数（总数至少 1）')
    return total,hits


def text(d, key, limit, required=True):
    value = d.get(key, '')
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise HTTPException(400, f'请检查字段 {key}（最多 {limit} 字）')
    return value.strip()


def normalized(s):
    return ' '.join(unicodedata.normalize('NFKC', s).casefold().split())


def url(d, key, required=True):
    raw = text(d, key, 1800, required)
    if not raw:
        return ''
    try:
        p = urlsplit(raw)
        if (p.scheme != 'https' or not p.hostname or p.username is not None or p.password is not None
                or p.port not in (None, 443) or re.search(r'[\\\s\x00-\x1f\x7f]', raw)):
            raise ValueError()
        return urlunsplit(('https', p.hostname.lower(), p.path or '/', p.query, ''))
    except ValueError:
        raise HTTPException(400, '请输入不带凭据的有效 HTTPS 来源链接') from None


def revision(d):
    value = d.get('revision')
    if type(value) is not int or value < 1:
        raise HTTPException(400, '缺少有效版本，请刷新详情')
    return value


def choice(d, key, options):
    result = text(d, key, 30)
    if result not in options:
        raise HTTPException(400, '选择无效，请重新选择')
    return result


def initialize(hub):
    with hub.db() as db:
        reviews.initialize(db)
        db.executescript('''
        CREATE TABLE IF NOT EXISTS own_goods(id TEXT PRIMARY KEY, name TEXT NOT NULL, shop TEXT NOT NULL,
          market TEXT NOT NULL, url TEXT NOT NULL, sku TEXT NOT NULL, facts TEXT NOT NULL,
          owner TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL, archived REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS own_goods_identity ON own_goods(market,url) WHERE archived IS NULL;
        CREATE INDEX IF NOT EXISTS own_goods_list ON own_goods(archived,updated DESC);
        CREATE TABLE IF NOT EXISTS own_goods_links(goods TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
          relation TEXT NOT NULL, owner TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(goods,kind,ref));
        CREATE TABLE IF NOT EXISTS own_goods_topics(id TEXT PRIMARY KEY, goods TEXT NOT NULL, claim TEXT NOT NULL,
          norm TEXT NOT NULL, owner TEXT NOT NULL, created REAL NOT NULL, UNIQUE(goods,norm));
        CREATE TABLE IF NOT EXISTS own_goods_evidence(id TEXT PRIMARY KEY, topic TEXT NOT NULL, kind TEXT NOT NULL,
          side TEXT NOT NULL, source_url TEXT NOT NULL, source_group TEXT NOT NULL, quote TEXT NOT NULL,
          observed TEXT NOT NULL, sample TEXT NOT NULL, sample_total INTEGER, sample_hits INTEGER,
          relation TEXT NOT NULL, upstream TEXT NOT NULL, fingerprint TEXT NOT NULL, owner TEXT NOT NULL,
          created REAL NOT NULL, removed REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS own_goods_evidence_unique ON own_goods_evidence(topic,fingerprint) WHERE removed IS NULL;
        CREATE INDEX IF NOT EXISTS own_goods_evidence_topic ON own_goods_evidence(topic,removed,created);
        CREATE TABLE IF NOT EXISTS own_goods_research_category(goods TEXT PRIMARY KEY,category TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS own_goods_research_exclusions(goods TEXT NOT NULL,case_id TEXT NOT NULL,
          excluded INTEGER NOT NULL CHECK(excluded IN (0,1)),PRIMARY KEY(goods,case_id));
        ''')


def get_goods(db, gid):
    r = db.execute('SELECT * FROM own_goods WHERE id=? AND archived IS NULL', (gid,)).fetchone()
    if not r:
        raise HTTPException(404, '自营商品不存在或已归档')
    return dict(r)


def can_edit(r, u):
    return r['owner'] == u['id'] or u['role'] == 'admin'


def require_editor(r, u):
    if not can_edit(r, u):
        raise HTTPException(403, '仅录入人或管理员可修改或移除')


def summary(items):
    counts = {s: 0 for s in SIDES}
    distinct = set()
    for row in items:
        counts[row['side']] += 1
        if row['side'] == 'support' and row['kind'] != 'own':
            distinct.add((row['kind'], normalized(row['source_group']), row['upstream']))
    # Require different underlying items, claimed source groups and types; not a confidence score.
    multi = any(k != k2 and g != g2 and org != org2 for k,g,org in distinct for k2,g2,org2 in distinct)
    if counts['counter'] and counts['support']:
        status, result = '证据有分歧', '本批记录同时有支持和反例，不能当作一致结论。'
    elif counts['counter']:
        status, result = '仅有反例', '已收录反例，现有记录不支持这项判断。'
    elif multi:
        status, result = '多角度支持', '按已录入的出处与类型，本批样本有不同角度的支持；不能外推到自家销量或整个市场。'
    elif counts['support']:
        status, result = '初步线索', '现有记录提供初步支持，尚缺不同来源、不同角度的印证。'
    else:
        status, result = '证据不足', '还没有直接支持或反驳该判断的记录。'
    return {'status':status,'result':result,'counts':counts,'external_angles':len({k for k,g,org in distinct}),
            'external_groups':len({g for k,g,org in distinct})}


def case_title(r):
    s=json.loads(r['source']); h=json.loads(r['human'])
    return (h.get('title') or s.get('title') or '@'+r['handle'])[:200]


def link_view(db, row):
    row=dict(row)
    row.update(available=False, title='原记录不可用', url='')
    if row['kind']=='case':
        from video_cases import require_case
        from video_case_presentation import metric_projection
        try:r=require_case(db,row['ref'])
        except HTTPException as e:
            if e.status_code==404: return row
            raise
        row.update(title=case_title(r),url=r['url'],available=True,
                   metrics=metric_projection({k:json.loads(r[k]) for k in ('human','source')}))
    else:
        r=db.execute('SELECT name,shop_name FROM intel_goods WHERE id=?',(row['ref'],)).fetchone()
        if r:row.update(title=r['name'] or row['ref'],detail=r['shop_name'],available=True)
    return row


def attach(app, hub, user, body):
    initialize(hub)
    initialize_lookup(hub)
    attach_lookup(app, hub, user, body)

    @app.get(PREFIX+'/available')
    def available():
        return {'available':True, 'listing_cover_lookup':True}

    @app.get(PREFIX)
    def listing(request:Request,q:str='',offset:int=0):
        user(request)
        if len(q)>160 or not 0<=offset<=100000:raise HTTPException(400,'搜索参数过长或分页无效')
        like='%'+q.strip().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
        where=" FROM own_goods g WHERE archived IS NULL AND (g.name LIKE ? ESCAPE '!' OR g.shop LIKE ? ESCAPE '!' OR g.market LIKE ? ESCAPE '!' OR g.sku LIKE ? ESCAPE '!')"
        from own_goods_cover import displayed_cover
        with hub.db() as db:
            db.execute('BEGIN')
            total=db.execute('SELECT count(*)'+where,(like,)*4).fetchone()[0]
            rows=[dict(r) for r in db.execute('''SELECT g.id,g.name,g.shop,g.market,g.sku,g.url,g.facts,
              (SELECT category FROM own_goods_research_category p WHERE p.goods=g.id) AS category_override,
              (SELECT count(*) FROM own_goods_links l WHERE l.goods=g.id) AS links,
              (SELECT count(*) FROM own_goods_topics t WHERE t.goods=g.id) AS topics'''+where+
              ' ORDER BY g.updated DESC,g.id LIMIT 24 OFFSET ?',(*((like,)*4),offset))]
            for r in rows:
                profile = dossier_profile(db, r,r.pop('category_override') or '')
                profile['tags'] = reviews.review_tags(db,'goods',r['id'],profile['tags'])
                r['tag_profile'] = profile
                r.update(displayed_cover(db, r, latest_lookup(db, r)))
                r.pop('facts');r.pop('url')
        return {'items':rows,'total':total,'page_size':24}

    @app.get(PREFIX+'/references')
    def references(request:Request,kind:str,q:str=''):
        user(request)
        if kind not in ('case','competitor') or len(q.strip())<1 or len(q)>160:raise HTTPException(400,'请填写搜索关键词')
        like='%'+q.strip().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
        with hub.db() as db:
            if kind=='case':
                rows=db.execute('''SELECT c.id,c.source,c.human,c.handle,c.video FROM video_cases c
                  WHERE c.removed_at IS NULL AND EXISTS(SELECT 1 FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=c.id)
                  AND (c.handle LIKE ? ESCAPE '!' OR c.video LIKE ? ESCAPE '!' OR json_extract(c.source,'$.title') LIKE ? ESCAPE '!'
                    OR json_extract(c.human,'$.title') LIKE ? ESCAPE '!') ORDER BY c.updated DESC LIMIT 21''',(like,)*4).fetchall()
                results=[{'id':r['id'],'title':case_title(r),'detail':'@'+r['handle']+' · '+r['video']} for r in rows]
            else:
                results=[dict(r) for r in db.execute('''SELECT id,coalesce(nullif(name,''),id) title,shop_name detail FROM intel_goods
                  WHERE name LIKE ? ESCAPE '!' OR id LIKE ? ESCAPE '!' OR shop_name LIKE ? ESCAPE '!' ORDER BY name,id LIMIT 21''',(like,)*3)]
            return {'items':results[:20],'more':len(results)>20}

    @app.post(PREFIX)
    async def save(request:Request):
        u=user(request); d=await body(request); gid=text(d,'id',32,False) or uuid.uuid4().hex
        vals=(text(d,'name',140),text(d,'shop',120),text(d,'market',2).upper(),url(d,'url'),text(d,'sku',140,False),text(d,'facts',3000,False))
        if not re.fullmatch('[A-Z]{2}',vals[2]):raise HTTPException(400,'市场请填两位国家代码，例如 US')
        category=None
        if 'category' in d:
            try:category=custom_category(text(d,'category',36,False))
            except ValueError as exc:raise HTTPException(400,str(exc)) from None
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if d.get('id'):
                r=get_goods(db,gid);require_editor(r,u)
                if r['revision']!=revision(d):raise HTTPException(409,'档案有更新，请刷新后再编辑')
            exists=db.execute('SELECT id FROM own_goods WHERE market=? AND url=? AND archived IS NULL AND id<>?',(vals[2],vals[3],gid)).fetchone()
            if exists:raise HTTPException(409,'这个市场已有该商品链接，请返回列表查看')
            if d.get('id'):
                db.execute('UPDATE own_goods SET name=?,shop=?,market=?,url=?,sku=?,facts=?,revision=revision+1,updated=? WHERE id=?',(*vals,time.time(),gid))
            else:db.execute('INSERT INTO own_goods(id,name,shop,market,url,sku,facts,owner,updated) VALUES(?,?,?,?,?,?,?,?,?)',(gid,*vals,u['id'],time.time()))
            if category is not None:
                db.execute('INSERT INTO own_goods_research_category(goods,category) VALUES(?,?) ON CONFLICT(goods) DO UPDATE SET category=excluded.category',(gid,category))
            hub.log(db,u['id'],'own_goods_saved',gid)
        return {'id':gid}

    def tags_for_review(db, entity, ref, member):
        if entity=='goods':
            product=get_goods(db,ref)
            saved=db.execute('SELECT category FROM own_goods_research_category WHERE goods=?',(ref,)).fetchone()
            return dossier_profile(db, product,saved[0] if saved else '')['tags'],can_edit(product,member)
        if entity=='case':
            from video_cases import require_case
            case=require_case(db,ref)
            return reviews.video_tags(json.loads(case['human']),json.loads(case['ai']),linked_titles(db,[case['video']]).get(case['video'],'')),True
        raise HTTPException(404,'标签对象不存在')

    @app.get(PREFIX+'/tag-review/{entity}/{ref}')
    def read_reviews(entity:str,ref:str,request:Request):
        member=user(request)
        with hub.db() as db:
            tags,editable=tags_for_review(db,entity,ref,member)
            return {'tags':reviews.review_tags(db,entity,ref,tags),'can_edit':editable}

    @app.post(PREFIX+'/tag-review/{entity}/{ref}')
    async def write_review(entity:str,ref:str,request:Request):
        member=user(request); data=await body(request)
        kind=text(data,'kind',60); label=text(data,'label',120)
        decision=choice(data,'decision',('pending','confirmed','rejected'))
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            tags,editable=tags_for_review(db,entity,ref,member)
            if not editable:raise HTTPException(403,'仅录入人或管理员可审核商品标签')
            reviews.set_review(db,entity,ref,tags,kind,label,decision,member['id'])
            hub.log(db,member['id'],'research_tag_review',ref)
            return {'tags':reviews.review_tags(db,entity,ref,tags),'can_edit':editable}

    @app.get(PREFIX+'/{gid}')
    def detail(gid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            db.execute('BEGIN')
            r=get_goods(db,gid); r['can_edit']=can_edit(r,u);r.pop('owner');r.pop('archived')
            saved=db.execute('SELECT category FROM own_goods_research_category WHERE goods=?',(gid,)).fetchone()
            r['tag_profile']=dossier_profile(db, r,saved[0] if saved else '')
            r['tag_profile']['tags']=reviews.review_tags(db,'goods',gid,r['tag_profile']['tags'])
            r['lookup']=lookup_status(db,r)
            for k in ('cover_url','cover_source','cover_observed'):
                r[k]=r['lookup'][k]
            rows=db.execute('SELECT * FROM own_goods_links WHERE goods=? ORDER BY created DESC',(gid,)).fetchall()
            r['links']=[{k:v for k,v in {**link_view(db,x),'can_edit':can_edit(x,u)}.items() if k!='owner'} for x in rows]
            r['topics']=[]
            for t in db.execute('SELECT id,claim,created FROM own_goods_topics WHERE goods=? ORDER BY created DESC',(gid,)):
                items=list(db.execute('SELECT kind,side,source_group,upstream FROM own_goods_evidence WHERE topic=? AND removed IS NULL',(t['id'],)))
                r['topics'].append({**dict(t), **summary(items), 'evidence_count':len(items)})
        return r

    @app.get(PREFIX+'/{gid}/topics/{tid}/evidence')
    def evidence_list(gid:str,tid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            get_goods(db,gid)
            if not db.execute('SELECT 1 FROM own_goods_topics WHERE goods=? AND id=?',(gid,tid)).fetchone():raise HTTPException(404,'判断不存在')
            items=[{**dict(e),'can_edit':can_edit(e,u)} for e in db.execute('''SELECT id,kind,side,source_url,source_group,
                quote,observed,sample,sample_total,sample_hits,relation,owner FROM own_goods_evidence
                WHERE topic=? AND removed IS NULL ORDER BY created DESC,id''',(tid,))]
        for e in items:e.pop('owner')
        return {'items':items}

    @app.post(PREFIX+'/{gid}/links')
    async def link(gid:str,request:Request):
        u=user(request);d=await body(request);kind=choice(d,'kind',('case','competitor'));ref=text(d,'ref',100)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');get_goods(db,gid)
            if d.get('remove') is True:
                old=db.execute('SELECT owner FROM own_goods_links WHERE goods=? AND kind=? AND ref=?',(gid,kind,ref)).fetchone()
                if old:require_editor(old,u);db.execute('DELETE FROM own_goods_links WHERE goods=? AND kind=? AND ref=?',(gid,kind,ref))
                return {'ok':True}
            relation=choice(d,'relation',RELATIONS)
            if not link_view(db,{'kind':kind,'ref':ref})['available']:raise HTTPException(404,'原记录不可用')
            existing=db.execute('SELECT relation FROM own_goods_links WHERE goods=? AND kind=? AND ref=?',(gid,kind,ref)).fetchone()
            if existing:
                if existing['relation']!=relation:raise HTTPException(409,'已关联。如需改变对标关系，请先解除旧关联')
                return {'ok':True}
            if db.execute('SELECT count(*) FROM own_goods_links WHERE goods=?',(gid,)).fetchone()[0]>=30:raise HTTPException(400,'每个商品最多关联30条参考')
            db.execute('INSERT INTO own_goods_links VALUES(?,?,?,?,?,?)',(gid,kind,ref,relation,u['id'],time.time()))
        return {'ok':True}

    @app.post(PREFIX+'/{gid}/topics')
    async def add_topic(gid:str,request:Request):
        u=user(request);d=await body(request);claim=text(d,'claim',200);norm=normalized(claim)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');get_goods(db,gid)
            old=db.execute('SELECT id FROM own_goods_topics WHERE goods=? AND norm=?',(gid,norm)).fetchone()
            if old:return {'id':old['id']}
            if db.execute('SELECT count(*) FROM own_goods_topics WHERE goods=?',(gid,)).fetchone()[0]>=12:raise HTTPException(400,'每个商品最多12项待验证判断')
            tid=uuid.uuid4().hex
            db.execute('INSERT INTO own_goods_topics VALUES(?,?,?,?,?,?)',(tid,gid,claim,norm,u['id'],time.time()))
        return {'id':tid}

    @app.post(PREFIX+'/{gid}/topics/{tid}/evidence')
    async def evidence(gid:str,tid:str,request:Request):
        u=user(request);d=await body(request)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');get_goods(db,gid)
            if not db.execute('SELECT 1 FROM own_goods_topics WHERE goods=? AND id=?',(gid,tid)).fetchone():raise HTTPException(404,'判断不存在')
            if d.get('remove') is True:
                ref=text(d,'id',32)
                old=db.execute('SELECT owner FROM own_goods_evidence WHERE topic=? AND id=? AND removed IS NULL',(tid,ref)).fetchone()
                if old:require_editor(old,u);db.execute('UPDATE own_goods_evidence SET removed=? WHERE topic=? AND id=?',(time.time(),tid,ref))
                return {'ok':True}
            kind=choice(d,'kind',KINDS);side=choice(d,'side',SIDES);source=url(d,'source_url',kind!='own')
            group=text(d,'source_group',160);quote=text(d,'quote',1000);observed=text(d,'observed',10);sample=text(d,'sample',300)
            try:
                if date.fromisoformat(observed).isoformat()!=observed:raise ValueError()
            except ValueError:raise HTTPException(400,'采样日期请填 YYYY-MM-DD') from None
            relation=choice(d,'relation',('self',) if kind=='own' else RELATIONS)
            if kind=='own' and side!='context':raise HTTPException(400,'自家商品核实仅作产品事实背景，不计作用户反馈')
            total,hits=sample_counts(d)
            if total is not None and kind not in ('comment','review'):
                raise HTTPException(400,'只有已逐条检查的评论或评价样本可以录入命中数')
            origin=upstream(source)
            fingerprint=hashlib.sha256(json.dumps([origin or normalized(group),normalized(quote)]).encode()).hexdigest()
            old=db.execute('SELECT id,side,kind FROM own_goods_evidence WHERE topic=? AND fingerprint=? AND removed IS NULL',(tid,fingerprint)).fetchone()
            if old:
                if old['side']!=side or old['kind']!=kind:raise HTTPException(409,'该证据已记录；如需更正，请先移除原记录')
                return {'id':old['id']}
            if db.execute('SELECT count(*) FROM own_goods_evidence WHERE topic=? AND removed IS NULL',(tid,)).fetchone()[0]>=50:raise HTTPException(400,'每项判断最多保留50条可见代表证据')
            eid=uuid.uuid4().hex
            db.execute('''INSERT INTO own_goods_evidence(id,topic,kind,side,source_url,source_group,quote,observed,sample,
                sample_total,sample_hits,relation,upstream,fingerprint,owner,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (eid,tid,kind,side,source,group,quote,observed,sample,total,hits,relation,origin,fingerprint,u['id'],time.time()))
            return {'id':eid}
