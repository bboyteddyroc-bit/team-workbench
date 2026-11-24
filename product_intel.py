"""Verified product-video links from monitored accounts and shared cases."""
import re
import json
from urllib.parse import urlsplit
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException
from kalodata_integration import QueryError


def ident(value):
    value = str(value or '')
    return value if re.fullmatch(r'[0-9]{1,32}', value) else ''


def products(item):
    rows = []
    for key in ('products','productList','productInfo','productInfos','commerceInfo','anchors','shopAnchors'):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get('products', [value])
        if isinstance(value, list):
            rows.extend(v for v in value if isinstance(v, dict))
    if item.get('product_id') or item.get('productId'):
        rows.append(item)
    return rows


def record(db, video, handle, row, origin):
    pid = ident(row.get('product_id') or row.get('productId'))
    if not pid:
        link = row.get('productUrl') or row.get('product_url') or row.get('url')
        if isinstance(link,str) and link.startswith('https://'):
            try:
                url = urlsplit(link)
                match = re.search(r'/(?:product|products|view/product)/([0-9]+)(?:/|$)', url.path)
                if match and (url.hostname=='tiktok.com' or (url.hostname or '').endswith('.tiktok.com')):
                    pid = ident(match[1])
            except ValueError:
                pass
    if not pid or not ident(video):
        return
    name = str(row.get('product_name') or row.get('productName') or '')[:300]
    shop = ident(row.get('product_shop_id') or row.get('shop_id') or row.get('shopId'))
    shop_name = str(row.get('shop_name') or row.get('shopName') or '')[:300]
    db.execute("""INSERT INTO intel_goods VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET
      name=coalesce(nullif(excluded.name,''),intel_goods.name),
      shop=coalesce(nullif(excluded.shop,''),intel_goods.shop),
      shop_name=coalesce(nullif(excluded.shop_name,''),intel_goods.shop_name)""",(pid,name,shop,shop_name))
    db.execute("""INSERT INTO intel_goods_video VALUES(?,?,?,?) ON CONFLICT(product,video,origin)
      DO UPDATE SET handle=coalesce(nullif(excluded.handle,''),intel_goods_video.handle)""",(pid,str(video),str(handle or '').lstrip('@')[:100],origin))


    enqueue(db,'product',pid)
    enqueue(db,'shop',pid)
    if shop and not shop_name:
        enqueue(db,'store',shop)


def enqueue(db,kind,key):
    if ident(key):
        db.execute("INSERT OR IGNORE INTO goods_jobs VALUES(?,?,'queued')",(kind,key))


def attach(app,hub,user,worker=False):
    with hub.db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS intel_goods(id TEXT PRIMARY KEY,name TEXT,shop TEXT,shop_name TEXT);
        CREATE TABLE IF NOT EXISTS intel_goods_video(product TEXT,video TEXT,handle TEXT,origin TEXT,PRIMARY KEY(product,video,origin));
        CREATE TABLE IF NOT EXISTS goods_jobs(kind TEXT,key TEXT,state TEXT,PRIMARY KEY(kind,key));
        INSERT OR IGNORE INTO goods_jobs SELECT 'product',product,'done' FROM intel_goods_video WHERE origin='Kalodata' GROUP BY product HAVING count(*)>1;
        INSERT OR IGNORE INTO goods_jobs SELECT 'shop',id,'done' FROM intel_goods WHERE shop<>'';
        INSERT OR IGNORE INTO goods_jobs SELECT 'store',shop,'queued' FROM intel_goods WHERE shop<>'' AND shop_name='';
        CREATE INDEX IF NOT EXISTS intel_goods_by_video ON intel_goods_video(video);
        """)
        db.execute("CREATE TABLE IF NOT EXISTS goods_details(kind TEXT,key TEXT,payload TEXT,PRIMARY KEY(kind,key))")
        if not db.execute("SELECT 1 FROM goods_details WHERE kind='migration'").fetchone():
            db.execute("UPDATE goods_jobs SET state='queued' WHERE kind IN ('shop','store') AND state='done'")
            db.execute("INSERT OR IGNORE INTO goods_jobs SELECT 'shop',id,'queued' FROM intel_goods")
            db.execute("INSERT OR IGNORE INTO goods_jobs SELECT 'store',shop,'queued' FROM intel_goods WHERE shop<>''")
            db.execute("INSERT INTO goods_details VALUES('migration','1','{}')")
    prefix='/api/intelligence/goods'

    @app.get(prefix)
    def library(request:Request, video:str=''):
        user(request)
        with hub.db() as db:
            goods=[dict(r) for r in db.execute('SELECT * FROM intel_goods ORDER BY name,id')]
            links=[dict(r) for r in db.execute("""SELECT g.product,g.video,max(g.handle) handle,group_concat(DISTINCT origin) origin,
              (SELECT id FROM video_cases WHERE platform='TikTok' AND video=g.video LIMIT 1) case_id,
              (SELECT title FROM apify_snapshots WHERE video=g.video ORDER BY collected DESC LIMIT 1) title,
              (SELECT views FROM apify_snapshots WHERE video=g.video ORDER BY collected DESC LIMIT 1) views
              FROM intel_goods_video g GROUP BY g.product,g.video""")]
            pending=[dict(r) for r in db.execute("""SELECT video,max(handle) handle,max(t) t FROM (
              SELECT s.video,a.handle,max(s.collected) t FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account WHERE a.deleted_at IS NULL GROUP BY s.video,a.handle
              UNION ALL SELECT video,handle,updated FROM video_cases WHERE platform='TikTok'
            ) video_candidates WHERE (?='' OR video_candidates.video=?)
            GROUP BY video ORDER BY t DESC LIMIT 100""",(video,video))]
            members={}
            for row in db.execute("""SELECT DISTINCT s.video,u.username FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account JOIN users u ON u.id=a.owner WHERE a.deleted_at IS NULL
                UNION SELECT c.video,u.username FROM video_cases c JOIN video_case_members m ON m.case_id=c.id JOIN users u ON u.id=m.owner WHERE c.platform='TikTok'"""):
                members.setdefault(row[0],[]).append(row[1])
            # Reuse existing monitor snapshots independent of the recent-record limit.
            # Match the team visibility rules of the existing cover endpoint.
            monitor_covers={}
            for vid,aid in db.execute("""WITH ranked AS (
                SELECT s.video,s.account,s.collected,s.cover,
                    row_number() OVER (PARTITION BY s.account,s.video ORDER BY s.collected DESC) AS rn
                FROM apify_snapshots s
                JOIN apify_accounts a ON a.id=s.account JOIN users u ON u.id=a.owner
                WHERE a.deleted_at IS NULL AND u.enabled=1 AND s.cover IS NOT NULL
                  AND EXISTS (SELECT 1 FROM intel_goods_video g WHERE g.video=s.video)
                ) SELECT video,account FROM ranked WHERE rn=1 AND trim(cover)<>''
                ORDER BY collected DESC,account"""):
                monitor_covers.setdefault(vid,f'/api/intelligence/apify/accounts/{aid}/cover/{vid}')
            for link in links:
                link['members']=members.get(link['video'],[])
                link['monitor_cover']=monitor_covers.get(link['video'],'')
            for item in pending:
                key=item['video']
                case=db.execute("SELECT id,json_extract(source,'$.title') FROM video_cases WHERE platform='TikTok' AND video=? LIMIT 1",(key,)).fetchone()
                snap=db.execute("SELECT account,title FROM apify_snapshots WHERE video=? ORDER BY collected DESC LIMIT 1",(key,)).fetchone()
                job=db.execute("SELECT state FROM goods_jobs WHERE kind='video' AND key=?",(key,)).fetchone()
                item.update(title=(case and case[1]) or (snap and snap[1]) or '',cover='/api/intelligence/cases/'+case[0]+'/cover' if case else '/api/intelligence/apify/accounts/'+snap[0]+'/cover/'+key if snap else '',state=job[0] if job else '',source='内容复用' if case else '竞对监测',members=members.get(key,[]))
            details={k+':'+key:json.loads(payload) for k,key,payload in db.execute("SELECT * FROM goods_details WHERE kind<>'migration'")}
        return dict(goods=goods,links=links,pending=pending,details=details)

    @app.post(prefix+'/lookup/{kind}/{key}')
    def lookup(kind:str,key:str,request:Request):
        user(request)
        if not ident(key) or kind not in ('video','product','shop'):
            raise HTTPException(400,'查询参数无效')
        with hub.db() as db:
            if kind=='video':
                found=db.execute("""SELECT handle FROM video_cases WHERE video=? AND platform='TikTok' UNION ALL
                  SELECT a.handle FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account WHERE s.video=? LIMIT 1""",(key,key)).fetchone()
            else:
                found=db.execute('SELECT id FROM intel_goods WHERE id=?',(key,)).fetchone()
            if not found:raise HTTPException(404,'记录不存在')
            enqueue(db,kind,key)
        return {'count':0,'queued':True}

    def process(kind,key):
        with hub.db() as db:
            found=db.execute('SELECT handle FROM video_cases WHERE video=? UNION ALL SELECT a.handle FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account WHERE s.video=? LIMIT 1',(key,key)).fetchone()
        from video_case_skill import detail_body
        end=datetime.now(timezone.utc).date()-timedelta(days=1)
        args=detail_body(key,end-timedelta(days=29),end)
        args.pop('video_id')
        if kind=='store':
            args['shop_id']=key
            endpoint='/shop/detail'
        elif kind=='shop':
            args['need_image']=1
            args['product_id']=key
            endpoint='/product/detail'
        else:
            args.pop('need_extra',None)
            args.update(page_number=1,page_size=100,sort_field={'field':'revenue','type':'DESC'})
            args[kind+'_id']=key
            endpoint='/product/rank' if kind=='video' else '/video/rank'
        try:
            result=app.state.kalodata.post(endpoint,args)
        except QueryError as exc:
            raise HTTPException(502,str(exc)) from None
        rows=result if isinstance(result,list) else result.get('data',[result]) if isinstance(result,dict) else []
        count=0
        with hub.db() as db:
            for r in rows:
                if not isinstance(r,dict):continue
                if kind in ('shop','store') and ident(r.get('shop_id' if kind=='store' else 'product_id'))==key:
                    fields=('unit_price','revenue','sales_volumn','video_revenue','live_revenue','showcase_revenue','master_image_url','shop_name','product_name')
                    payload={f:r[f] for f in fields if isinstance(r.get(f),(str,int,float))}
                    payload['end']=str(end)
                    db.execute("INSERT OR REPLACE INTO goods_details VALUES(?,?,?)",(kind,key,json.dumps(payload)))
                if kind=='store' and ident(r.get('shop_id'))==key:
                    db.execute("UPDATE intel_goods SET shop_name=? WHERE shop=?",(str(r.get('shop_name') or '')[:300],key))
                elif kind=='shop':
                    shop=ident(r.get('product_shop_id') or r.get('shop_id'))
                    if str(r.get('product_id'))==key and shop:
                        db.execute('UPDATE intel_goods SET shop=?,shop_name=coalesce(nullif(?,\'\'),shop_name) WHERE id=?',(shop,str(r.get('shop_name') or r.get('product_shop_name') or '')[:300],key));count+=1
                        enqueue(db,'store',shop)
                elif kind=='video' and ident(r.get('product_id')):
                    record(db,key,found[0],r,'Kalodata');count+=1
                elif kind=='product' and ident(r.get('video_id')):
                    record(db,r['video_id'],r.get('belonged_creator_handle'),{'product_id':key},'Kalodata');count+=1
            db.execute("UPDATE goods_jobs SET state='done' WHERE kind=? AND key=?",(kind,key))

    def run():
        import logging
        while not hub.stop.wait(2):
            try:
                with hub.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row=db.execute("SELECT kind,key FROM goods_jobs WHERE state='queued' ORDER BY CASE WHEN kind='video' THEN 1 ELSE 0 END,rowid LIMIT 1").fetchone()
                    if not row:continue
                    db.execute("UPDATE goods_jobs SET state='claimed' WHERE kind=? AND key=?",tuple(row))
                try:process(*row)
                except Exception:
                    with hub.db() as db:db.execute("UPDATE goods_jobs SET state='attention' WHERE kind=? AND key=?",tuple(row))
                    logging.exception('Product intelligence lookup failed')
            except Exception:logging.exception('Product intelligence queue failed')
    if worker:
        import threading
        threading.Thread(target=run,daemon=True,name='goods-discovery').start()
