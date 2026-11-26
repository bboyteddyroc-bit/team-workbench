"""Prompt templates and their generation history."""
import json
import secrets
import time

from fastapi import HTTPException, Request


VIDEO_SOURCES = {'tiktok', 'libtv'}
SOURCES = VIDEO_SOURCES | {'image'}
VIDEO_OPTIONS = ('mode', 'duration', 'count', 'model', 'libtv_model', 'libtv_resolution')
IMAGE_OPTIONS = ('size', 'ratio', 'count')


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS prompt_templates(
      id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
      prompt TEXT NOT NULL, settings TEXT NOT NULL, refs TEXT NOT NULL, shared INTEGER NOT NULL,
      created REAL NOT NULL, updated REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS prompt_template_runs(
      template TEXT NOT NULL, source TEXT NOT NULL, job TEXT NOT NULL, owner TEXT NOT NULL,
      submitted REAL NOT NULL, use_key TEXT NOT NULL, snapshot TEXT NOT NULL,
      PRIMARY KEY(template,source,job)
    );
    """)


def visible(db, owner, ident, kind=None):
    if not isinstance(ident,str) or len(ident)!=24:
        raise HTTPException(404, '提示词模板不可用')
    row = db.execute('SELECT * FROM prompt_templates WHERE id=? AND (owner=? OR shared=1)', (ident, owner)).fetchone()
    if not row or kind and row['kind'] != kind:
        raise HTTPException(404, '提示词模板不可用')
    return row


def track(db, owner, ident, source, job, use_key, *, origin=False):
    if not ident:
        return
    visible(db, owner, ident, 'image' if source == 'image' else 'video')
    item = run(db,owner,source,job)
    if item:
        if source=='image':
            item['refs'] = [{'name':ref['name']} for ref in item['refs']]
        snapshot = json.dumps(item,ensure_ascii=False)
    else:
        snapshot = '{}'
    db.execute('INSERT OR IGNORE INTO prompt_template_runs VALUES(?,?,?,?,?,?,?)',
               (ident, source, job, owner, time.time(), '' if origin else use_key, snapshot))


def run(db, owner, source, ident):
    if source == 'tiktok':
        row = db.execute('SELECT id,prompt,state,created,config AS payload FROM tasks WHERE id=? AND owner=?',
                         (ident, owner)).fetchone()
    elif source == 'libtv':
        row = db.execute('SELECT id,state,created,asset_id,payload FROM libtv_jobs WHERE id=? AND owner=?',
                         (ident, owner)).fetchone()
    elif source == 'image':
        row = db.execute('SELECT id,prompt,status AS state,created,generation AS payload,images,result_asset,result_assets FROM ai_turns WHERE id=? AND owner=?',
                         (ident, owner)).fetchone()
    else:
        return None
    if row is None:
        return None
    item = dict(row)
    config = json.loads(item.pop('payload'))
    item.update(source=source, settings={}, refs=[], urls=[])
    if source == 'image':
        if config.get('provider') != 'libtv':
            return None
        item['settings'] = {k: config[k] for k in IMAGE_OPTIONS if k in config}
        item['refs'] = json.loads(item.pop('images'))
        ids = json.loads(item.pop('result_assets')) or ([item['result_asset']] if item.get('result_asset') else [])
        for asset in ids:
            if db.execute('SELECT 1 FROM assets WHERE id=? AND owner=?', (asset, owner)).fetchone():
                item['urls'].append('/api/assets/'+asset)
    else:
        if source == 'libtv':
            item['prompt'] = config.get('prompt', '')
            config = {**config, 'libtv_model':config.get('model'), 'libtv_resolution':config.get('resolution')}
            config['model'] = 'auto'
        item['settings'] = {k: config[k] for k in VIDEO_OPTIONS if k in config}
        item['settings']['channel'] = source
        item['settings']['ratio'] = '9:16'
        for ref in config.get('assets', []):
            asset = db.execute('SELECT id,name,mime,size FROM assets WHERE id=? AND owner=?',
                               (ref['id'], owner)).fetchone()
            entry = {'id': ref['id'], 'name': str(ref.get('name') or ref.get('token') or '已移除的素材')[:200],
                     'mime': ref.get('mime'), 'role':ref.get('role','reference'), 'token':ref.get('token',''),
                     'available':asset is not None}
            if asset:
                entry.update(dict(asset))
            item['refs'].append(entry)
        if item['state'] == 'ready':
            item['urls'].append('/api/tasks/'+ident+'/video')
    item['pinned'] = bool(source in VIDEO_SOURCES and db.execute(
        'SELECT 1 FROM retained_videos WHERE source=? AND job=? AND owner=?', (source,ident,owner)).fetchone())
    return item


def detach_image_history(db, owner, thread):
    """Deleting a chat does not delete the history explicitly saved in templates."""
    for link in db.execute("""SELECT DISTINCT r.job FROM prompt_template_runs r JOIN ai_turns t ON t.id=r.job
                             WHERE r.source='image' AND r.owner=? AND t.owner=? AND t.thread=?""",
                           (owner,owner,thread)):
        item = run(db,owner,'image',link['job'])
        if item:
            item['refs'] = [{'name':ref['name']} for ref in item['refs']]
            db.execute("UPDATE prompt_template_runs SET snapshot=? WHERE source='image' AND job=? AND owner=?",
                       (json.dumps(item,ensure_ascii=False),link['job'],owner))


def attach(app, hub, user, body):
    with hub.db() as db:
        initialize(db)

    @app.get('/api/prompt-templates')
    def listing(request:Request, kind:str='', q:str=''):
        owner=user(request)['id']
        if kind not in ('','video','image') or len(q)>100:
            raise HTTPException(400,'模板筛选无效')
        with hub.db() as db:
            return [dict(row) for row in db.execute("""SELECT p.id,p.title,p.kind,p.shared,p.created,p.updated,
                p.owner=? AS mine,
                (SELECT count(DISTINCT r.owner||':'||r.use_key) FROM prompt_template_runs r
                 WHERE r.template=p.id AND r.use_key<>'') AS uses,
                (SELECT max(r.submitted) FROM prompt_template_runs r WHERE r.template=p.id AND r.use_key<>'') AS last_used
                FROM prompt_templates p WHERE (p.owner=? OR p.shared=1) AND (?='' OR kind=?)
                AND instr(lower(title||' '||prompt),lower(?))>0
                ORDER BY uses DESC,updated DESC LIMIT 120""", (owner,owner,kind,kind,q.strip()))]

    @app.post('/api/prompt-templates')
    async def create(request:Request):
        owner=user(request)['id']
        data=await body(request)
        title=data.get('title','')
        shared=data.get('shared',False)
        origin=data.get('source')
        if not isinstance(title,str) or not 1<=len(title.strip())<=80 or type(shared) is not bool:
            raise HTTPException(400,'请输入 1–80 字模板名称')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if origin:
                item=run(db,owner,origin,str(data.get('job',''))) if isinstance(origin,str) else None
                if item is None:
                    raise HTTPException(404,'没有找到此生成记录')
                kind='image' if origin=='image' else 'video'
                prompt,settings,refs=item['prompt'],item['settings'],item['refs']
            elif data.get('copy'):
                copied=visible(db,owner,data['copy'])
                kind,prompt=copied['kind'],copied['prompt']
                settings=json.loads(copied['settings'])
                refs=json.loads(copied['refs']) if copied['owner']==owner else []
            else:
                kind,prompt=data.get('kind'),data.get('prompt')
                settings,refs={},[]
            if kind not in ('image','video') or not isinstance(prompt,str) or not 1<=len(prompt.strip())<=20000:
                raise HTTPException(400,'请填写提示词并选择模板类型')
            ident=secrets.token_hex(12)
            now=time.time()
            db.execute('INSERT INTO prompt_templates VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (ident,owner,kind,title.strip(),prompt.strip(),json.dumps(settings),json.dumps(refs,ensure_ascii=False),int(shared),now,now))
            if origin:
                jobs=[item['id']]
                if origin=='tiktok':
                    jobs=[r['id'] for r in db.execute("""SELECT t.id FROM tasks t JOIN tasks seed ON seed.id=?
                        WHERE t.owner=? AND (t.id=seed.id OR (seed.batch_id IS NOT NULL AND t.batch_id=seed.batch_id
                        AND t.config=seed.config AND t.prompt=seed.prompt))""",(item['id'],owner))]
                elif origin=='libtv':
                    key=db.execute('SELECT request_key FROM libtv_jobs WHERE id=?',(item['id'],)).fetchone()[0]
                    import re
                    match=re.fullmatch(r'([a-f0-9-]{36})-[0-9]+',key)
                    if match:
                        jobs=[r[0] for r in db.execute('SELECT id FROM libtv_jobs WHERE owner=? AND request_key LIKE ?',
                                                      (owner,match[1]+'-%'))]
                for job in jobs:
                    track(db,owner,ident,origin,job,'',origin=True)
        return {'id':ident}

    @app.get('/api/prompt-templates/{ident}')
    def detail(ident:str,request:Request,offset:int=0):
        owner=user(request)['id']
        if not 0<=offset<=100000:
            raise HTTPException(400,'页码无效')
        with hub.db() as db:
            row=visible(db,owner,ident)
            refs=json.loads(row['refs']) if row['owner']==owner else []
            if row['kind']=='video':
                for ref in refs:
                    ref['available']=bool(db.execute('SELECT 1 FROM assets WHERE id=? AND owner=?',(ref['id'],owner)).fetchone())
            total=db.execute('SELECT count(*) FROM prompt_template_runs WHERE template=? AND owner=?',(ident,owner)).fetchone()[0]
            history=[]
            for link in db.execute('SELECT * FROM prompt_template_runs WHERE template=? AND owner=? ORDER BY submitted DESC,job LIMIT 16 OFFSET ?',
                                   (ident,owner,offset)):
                snapshot=json.loads(link['snapshot'])
                item=run(db,owner,link['source'],link['job']) or snapshot
                if item:
                    previous={ref['id']:ref for ref in snapshot.get('refs',[]) if 'id' in ref}
                    for ref in item['refs']:
                        if ref.get('available') is False and ref.get('id') in previous:
                            ref['name']=previous[ref['id']]['name']
                    # Reference images are loaded into the template draft only; history
                    # keeps names, parameters and outcome links rather than repeated blobs.
                    if item['source']=='image':
                        item['refs']=[{'name':ref['name']} for ref in item['refs']]
                        item['urls']=[url for url in item['urls'] if db.execute(
                            'SELECT 1 FROM assets WHERE id=? AND owner=?',(url.rsplit('/',1)[1],owner)).fetchone()]
                    history.append(item)
            return {**{k:row[k] for k in ('id','kind','title','prompt','shared')}, 'mine':row['owner']==owner,
                    'settings':json.loads(row['settings']),'refs':refs,'history':history,'total':total}

    @app.post('/api/prompt-templates/{ident}/update')
    async def update(ident:str,request:Request):
        owner=user(request)['id'];data=await body(request)
        title,prompt,shared=data.get('title'),data.get('prompt'),data.get('shared')
        if not isinstance(title,str) or not 1<=len(title.strip())<=80 or not isinstance(prompt,str) or not 1<=len(prompt.strip())<=20000 or type(shared) is not bool:
            raise HTTPException(400,'请输入模板名称和提示词')
        with hub.db() as db:
            updated=db.execute('UPDATE prompt_templates SET title=?,prompt=?,shared=?,updated=? WHERE id=? AND owner=?',
                               (title.strip(),prompt.strip(),int(shared),time.time(),ident,owner)).rowcount
            if not updated:
                raise HTTPException(404,'没有找到可编辑的模板')
        return {'ok':True}
