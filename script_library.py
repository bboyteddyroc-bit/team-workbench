"""Shared script library and local snapshot simulation. No external requests or jobs."""
import json
import time
import uuid
from fastapi import HTTPException, Request

FIELDS = ('product_category', 'content_type', 'opening', 'audience_scenario', 'expression', 'ending', 'work_status', 'edited_text', 'notes', 'pain_point', 'reuse_framework')

def matches(row, thresholds):
    views = row.get('views')
    if type(views) not in (int, float) or views < 0:
        return []
    reasons = ['播放量 ≥ 70 万'] if views >= 700000 else []
    if views >= 10000:
        for field, label in [('likes', '点赞率'), ('collects', '收藏率'), ('comments', '评论率')]:
            value, limit = row.get(field), thresholds.get(field)
            if type(value) in (int, float) and value >= 0 and value <= views and type(limit) in (int, float) and 0 < limit <= 100 and value / views * 100 >= limit:
                reasons.append(label + '达标')
    return reasons

def attach(app, hub, user, body):
    with hub.db() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS script_library (
          id TEXT PRIMARY KEY, video TEXT UNIQUE, account_handle TEXT, video_url TEXT, published REAL,
          description TEXT, cover TEXT, snapshot TEXT, reasons TEXT, transcript_original TEXT,
          transcript_source TEXT, transcript_status TEXT NOT NULL, product_category TEXT DEFAULT '',
          content_type TEXT DEFAULT '', opening TEXT DEFAULT '', expression TEXT DEFAULT '', ending TEXT DEFAULT '',
          work_status TEXT DEFAULT '待审核', edited_text TEXT DEFAULT '', notes TEXT DEFAULT '',
          created REAL NOT NULL, updated REAL NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL
        );''')
        if 'removed_at' not in {r['name'] for r in db.execute('PRAGMA table_info(script_library)')}:
            db.execute('ALTER TABLE script_library ADD COLUMN removed_at REAL')
        import script_enrichment
        script_enrichment.initialize(db)
        cols={r['name'] for r in db.execute('PRAGMA table_info(script_library)')}
        for name, default in [('tags', '[]'), ('pain_point', ''), ('reuse_framework', '')]:
            if name not in cols:
                db.execute('ALTER TABLE script_library ADD COLUMN '+name+" TEXT NOT NULL DEFAULT '"+default+"'")

    import script_creation
    script_creation.attach(app,hub,user,body)

    @app.get('/api/intelligence/scripts')
    def list_scripts(request: Request):
        user(request)
        with hub.db() as db:
            result = [dict(r) for r in db.execute('SELECT * FROM script_library WHERE removed_at IS NULL ORDER BY updated DESC LIMIT 5000')]
        for r in result:
            r['snapshot'] = json.loads(r['snapshot']) if r['snapshot'] else None
            r['reasons'] = json.loads(r['reasons']) if r['reasons'] else []
            r['tags'] = json.loads(r['tags']) if r['tags'] else []
        return result

    @app.get('/api/intelligence/scripts/simulate')
    def simulate(request: Request, likes: float = 5, collects: float = 0.8, comments: float = 0.15):
        user(request)
        thresholds = dict(likes=likes, collects=collects, comments=comments)
        if any(not 0 < v <= 100 for v in thresholds.values()):
            raise HTTPException(400, '比例应大于 0 且不超过 100')
        with hub.db() as db:
            rows = db.execute('''SELECT s.*, a.handle FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account
                WHERE a.deleted_at IS NULL AND s.rowid=(SELECT t.rowid FROM apify_snapshots t WHERE t.account=s.account AND t.video=s.video ORDER BY t.collected DESC,t.rowid DESC LIMIT 1)
                ORDER BY s.collected DESC LIMIT 10000''').fetchall()
            existing = {r[0] for r in db.execute('SELECT video FROM script_library WHERE video IS NOT NULL')}
        result = []
        for r in rows:
            item = dict(r); reasons = matches(item, thresholds)
            if reasons:
                item['reasons'] = reasons; item['in_library'] = item['video'] in existing
                result.append(item)
        return {'matched':result, 'scanned':len(rows), 'limit':10000, 'thresholds':thresholds, 'notice':'仅本地快照模拟，不采集、不提取、不计费；阈值尚未确认'}

    @app.post('/api/intelligence/scripts/from-snapshot')
    async def from_snapshot(request: Request):
        u = user(request); data = await body(request)
        account, video = data.get('account'), data.get('video')
        if not isinstance(account, str) or not isinstance(video, str): raise HTTPException(400, '视频参数无效')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT s.*,a.handle FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account
                WHERE s.account=? AND s.video=? AND a.deleted_at IS NULL ORDER BY s.collected DESC,s.rowid DESC LIMIT 1''', (account,video)).fetchone()
            if not row: raise HTTPException(404,'视频快照不存在')
            row = dict(row)
            old = db.execute('SELECT id,removed_at FROM script_library WHERE video=?',(video,)).fetchone()
            if old and old['removed_at'] is not None:raise HTTPException(409,'该文案已移除，未重复入库')
            if old: return {'id':old['id'], 'existing':True}
            ident = uuid.uuid4().hex; now = time.time()
            snapshot = {k:row[k] for k in ('views','likes','collects','comments','shares','collected')}
            url = 'https://www.tiktok.com/@' + row['handle'] + '/video/' + video if row['handle'] and video.isdigit() else ''
            db.execute('''INSERT INTO script_library(id,video,account_handle,video_url,published,description,cover,snapshot,reasons,transcript_status,created,updated,created_by,updated_by)
                VALUES(?,?,?,?,?,?,?,?,?,'未提取',?,?,?,?)''', (ident,video,row['handle'],url,row['published'],row['title'],row['cover'],json.dumps(snapshot),json.dumps(['人工加入（模拟结果）'],ensure_ascii=False),now,now,u['id'],u['id']))
        return {'id':ident,'existing':False}

    @app.post('/api/intelligence/scripts/{item_id}/remove')
    async def remove_script(item_id: str, request: Request):
        u=user(request);data=await body(request)
        if data.get('confirm') is not True:raise HTTPException(400,'请确认从团队文案库移除')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT id FROM script_library WHERE id=? AND removed_at IS NULL',(item_id,)).fetchone()
            if not row:raise HTTPException(404,'文案不存在或已移除')
            if db.execute("SELECT 1 FROM script_transcriptions WHERE item=? AND state='running'",(item_id,)).fetchone() or db.execute("SELECT 1 FROM script_enrichment WHERE item=? AND state='running'",(item_id,)).fetchone():raise HTTPException(409,'文案处理正在执行，请等待结束后再移除')
            now=time.time()
            db.execute("UPDATE script_transcriptions SET state='cancelled',error='文案已移除',updated=? WHERE item=? AND state='queued'",(now,item_id))
            db.execute("UPDATE script_enrichment SET state='cancelled',error='文案已移除',updated=? WHERE item=? AND state='queued'",(now,item_id))
            db.execute('UPDATE script_library SET removed_at=?,updated=?,updated_by=? WHERE id=?',(now,now,u['id'],item_id))
            hub.log(db,u['id'],'script_library_removed',item_id)
        return {'ok':True}
    @app.post('/api/intelligence/scripts/{item_id}')
    async def update_script(item_id: str, request: Request):
        u=user(request); data=await body(request)
        updates={}
        for k in FIELDS:
            if k in data:
                v=data[k]
                if not isinstance(v,str) or len(v) > (30000 if k in ('edited_text','notes','pain_point','reuse_framework') else 200):
                    raise HTTPException(400,'字段格式或长度不正确')
                updates[k]=v.strip()
        if 'tags' in data:
            tags=data['tags']
            if not isinstance(tags,list) or len(tags)>20 or any(not isinstance(t,str) or not t.strip() or len(t.strip())>30 for t in tags):
                raise HTTPException(400,'标签最多20个，每个1至30字')
            clean=[]
            for tag in tags:
                tag=tag.strip()
                if tag.casefold() not in {t.casefold() for t in clean}: clean.append(tag)
            updates['tags']=json.dumps(clean,ensure_ascii=False)
        if not updates: raise HTTPException(400,'没有可保存的字段')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM script_library WHERE id=? AND removed_at IS NULL',(item_id,)).fetchone(): raise HTTPException(404,'文案不存在')
            db.execute('UPDATE script_library SET '+','.join(k+'=?' for k in updates)+',updated=?,updated_by=? WHERE id=?',(*updates.values(),time.time(),u['id'],item_id))
        return {'ok':True}
