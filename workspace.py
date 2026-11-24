"""Project associations and private continuation drafts; no provider calls."""
import json
import time
from fastapi import HTTPException, Request


def require_project(db, pid, owner):
    row = db.execute('SELECT * FROM edit_projects WHERE id=? AND owner=?', (pid, owner)).fetchone()
    if not row:
        raise HTTPException(404, '项目不存在或无权访问')
    return row


def validate_continuation(db, item, u, project_id, hub):
    continuation=item.get('continuation')
    if continuation is None:return
    if not isinstance(continuation,dict):raise HTTPException(400,'接力来源格式有误')
    source=str(continuation.get('source_id',''))
    row=db.execute("SELECT t.owner,t.state,a.scope FROM tasks t JOIN accounts a ON a.id=t.account_id WHERE t.id=?",(source,)).fetchone()
    if row:
        allowed=row['state']=='ready' and (row['owner']==u['id'] or u['role']=='admin' and row['scope']=='shared')
    else:
        # LibTV results are private to their owner, even when the generation account is shared.
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='libtv_jobs'").fetchone()
        remote=db.execute("SELECT j.asset_id FROM libtv_jobs j JOIN assets a ON a.id=j.asset_id AND a.owner=j.owner WHERE j.id=? AND j.owner=? AND j.state='ready'",(source,u['id'])).fetchone() if exists else None
        allowed=bool(remote and (hub.assets/remote['asset_id']).is_file())
    if not allowed:
        raise HTTPException(400,'接力来源不存在、尚未完成或无权访问')
    frame=str(continuation.get('frame_id',''))
    derived=db.execute("SELECT * FROM derived_assets WHERE asset_id=? AND owner=? AND source_task=? AND kind='frame'",(frame,u['id'],source)).fetchone()
    ids={a['id'] for a in item.get('assets',[])}
    if not derived or frame not in ids:raise HTTPException(400,'请先从来源视频提取并选择参考帧')
    audio=continuation.get('audio_id')
    if audio and audio not in ids:raise HTTPException(400,'声音参考没有加入生成输入')
    if audio:
        audio_row=db.execute("SELECT mime FROM assets WHERE id=? AND owner=?",(audio,u['id'])).fetchone()
        if not audio_row or not audio_row['mime'].startswith('audio/'):raise HTTPException(400,'声音参考格式有误')
        try:
            from editor import probe
            seconds,_=probe(hub.assets/audio)
            if not 2<=seconds<=15.2:raise ValueError()
        except (ValueError,OSError):raise HTTPException(400,'生成声音参考需要 2–15 秒，请重新选择原声范围或上传合适长度的声音') from None
    if item.get('mode')=='frames' and audio:raise HTTPException(400,'首尾帧模式不支持声音参考，请切换全能模式')
    if item.get('mode')=='frames' and not any(a['id']==frame and a.get('role')=='first' for a in item.get('assets',[])):
        raise HTTPException(400,'接力首尾帧模式需要把选定参考帧用作首帧')
    append=continuation.get('append_timeline',False)
    if type(append) is not bool or append and not project_id:raise HTTPException(400,'自动追加时间轴需要选择项目')
    item['continuation']={'source_id':source,'frame_id':frame,'frame_time':derived['start'],
                          'audio_id':audio,'append_timeline':append}


def append_completed(hub, task_id):
    """Append once in a transaction; never invalidate a successful generated video."""
    from editor import probe, record_version, timeline_duration
    from multitrack import FPS, normalize
    import math
    with hub.db() as db:
        task=db.execute('SELECT owner,config,state FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not task or task['state']!='ready':return
        config=json.loads(task['config'] or '{}')
        if not config.get('continuation',{}).get('append_timeline'):return
        link=db.execute('SELECT project_id FROM project_tasks WHERE task_id=? AND owner=?',(task_id,task['owner'])).fetchone()
        if not link:return
    pid=link['project_id']
    try:
        duration,_=probe(hub.media/(task_id+'.mp4'))
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM continuation_results WHERE task_id=?',(task_id,)).fetchone():return
            project=require_project(db,pid,task['owner']);content=json.loads(project['body']);clips=content.get('clips',[])
            if not any(c.get('task_id')==task_id for c in clips):
                # Use the entire timeline, not source lengths: include speed, gaps,
                # captions, detached audio and stickers. Quantize the new boundary.
                at=math.ceil(timeline_duration(content)*FPS-1e-7)/FPS
                if len(clips)>=50 or at+duration>600:
                    raise ValueError('项目达到片段或时长上限，请手动加入剪辑')
                content['clips']=clips
                # Upgrade legacy placement before adding: normalize also fills all
                # required track fields and retains existing per-track metadata.
                normalize(content,content)
                track=content.get('main_track') or 'video-main'
                clips.append({'task_id':task_id,'start':0,'end':duration,'volume':1,'speed':1,'at':at,'track':track})
                normalize(content,content)
                db.execute('UPDATE edit_projects SET body=?,version=version+1,updated=? WHERE id=?',
                           (json.dumps(content,ensure_ascii=False),time.time(),pid))
                record_version(db,pid)
            db.execute('INSERT INTO continuation_results VALUES(?,?,?,?)',(task_id,pid,'applied',''))
            db.execute('UPDATE tasks SET updated=? WHERE id=?',(time.time(),task_id))
    except Exception:
        with hub.db() as db:
            changed=db.execute('INSERT OR IGNORE INTO continuation_results VALUES(?,?,?,?)',
                       (task_id,pid,'failed','自动加入时间轴失败；生成视频已保留，请从结果点击加入剪辑')).rowcount
            if changed:db.execute('UPDATE tasks SET updated=? WHERE id=?',(time.time(),task_id))


def attach(app, hub, user, body):
    with hub.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS project_tasks(
            project_id TEXT NOT NULL, task_id TEXT NOT NULL, owner TEXT NOT NULL,
            created REAL NOT NULL, PRIMARY KEY(project_id,task_id));
        CREATE TABLE IF NOT EXISTS continuation_drafts(
            owner TEXT PRIMARY KEY, content TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS continuation_results(
            task_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS asset_labels(
            asset_id TEXT PRIMARY KEY,category TEXT NOT NULL DEFAULT 'other');
        ''')

    @app.get('/api/workspace/links')
    def links(request: Request):
        u = user(request)
        with hub.db() as db:
            return [dict(r) for r in db.execute(
                'SELECT l.project_id,l.task_id,p.title FROM project_tasks l JOIN edit_projects p ON p.id=l.project_id WHERE l.owner=? AND p.owner=?',
                (u['id'], u['id']))]

    @app.get('/api/workspace/overview')
    def overview(request: Request, offset:int=0, limit:int=0, project_id:str=''):
        u = user(request); result=[]
        if offset<0 or limit<0 or limit>100 or (offset and not limit) or len(project_id)>128 or (project_id and (offset or limit)):raise HTTPException(400,'分页参数无效')
        with hub.db() as db:
            if project_id:
                projects=db.execute('SELECT * FROM edit_projects WHERE owner=? AND id=?',(u['id'],project_id)).fetchall()
            else:
                projects=db.execute('SELECT * FROM edit_projects WHERE owner=? ORDER BY updated DESC,id DESC'+(' LIMIT ? OFFSET ?' if limit else ''),(u['id'],limit,offset) if limit else (u['id'],)).fetchall()
            project_ids=[p['id'] for p in projects]
            restricted=bool(limit or project_id)
            page_filter=' AND p.id IN ('+','.join('?' for _ in project_ids)+')' if restricted and project_ids else ''
            task_map={};export_map={}
            if projects:
                rows=db.execute("""SELECT l.project_id,t.id,t.prompt,t.state,t.duration,t.created,t.updated,t.config
                    FROM project_tasks l JOIN edit_projects p ON p.id=l.project_id AND p.owner=?
                    JOIN tasks t ON t.id=l.task_id JOIN accounts a ON a.id=t.account_id
                    WHERE l.owner=? AND (t.owner=? OR (?='admin' AND a.scope='shared'))"""+page_filter+" ORDER BY t.created",(u['id'],u['id'],u['id'],u['role'],*(project_ids if restricted else [])))
                for row in rows:
                    config=json.loads(row['config'] or '{}')
                    task_map.setdefault(row['project_id'],[]).append({**{k:row[k] for k in ('id','prompt','state','duration','created','updated')},
                                  'model':config.get('model','5000005'),
                                  'source_id':config.get('continuation',{}).get('source_id'),
                                  'asset_ids':[a['id'] for a in config.get('assets',[]) if isinstance(a,dict) and 'id' in a]})
                rows=db.execute("""SELECT id,state,created,error,project_id FROM (
                    SELECT e.id,e.state,e.created,e.error,e.project_id,
                    ROW_NUMBER() OVER (PARTITION BY e.project_id ORDER BY e.created DESC) AS rn
                    FROM edit_exports e JOIN edit_projects p ON p.id=e.project_id AND p.owner=? WHERE e.owner=?"""+page_filter+"""
                    ) WHERE rn<=10 ORDER BY project_id,created DESC""",(u['id'],u['id'],*(project_ids if restricted else [])))
                for row in rows:
                    export_map.setdefault(row['project_id'],[]).append({k:row[k] for k in ('id','state','created','error')})
            for project in projects:
                timeline=json.loads(project['body'])
                tasks=task_map.get(project['id'],[]);exports=export_map.get(project['id'],[])
                result.append(dict(id=project['id'],title=project['title'],version=project['version'],updated=project['updated'],
                    ratio=timeline.get('ratio','9:16'),target_duration=timeline.get('target_duration',30),
                    timeline_duration=sum(c['end']-c['start'] for c in timeline.get('clips',[])),
                    clip_count=len(timeline.get('clips',[])),tasks=tasks,exports=exports))
        return result

    @app.get('/api/workspace/materials')
    def materials(request: Request):
        u=user(request)
        with hub.db() as db:
            return [dict(r) for r in db.execute("""SELECT a.id,a.name,a.mime,a.size,a.created,
                COALESCE(l.category,'other') AS category, COALESCE(c.status,'waiting_model') AS classification_status, COALESCE(c.error,'') AS classification_error FROM assets a
                LEFT JOIN asset_classification c ON c.asset_id=a.id
                LEFT JOIN asset_labels l ON l.asset_id=a.id WHERE a.owner=? ORDER BY a.created DESC""",(u['id'],))]

    @app.post('/api/workspace/material-status')
    async def material_status(request: Request):
        u=user(request); data=await body(request); ids=data.get('ids')
        if not isinstance(ids,list) or len(ids)>500 or any(not isinstance(i,str) or not i or len(i)>128 for i in ids):
            raise HTTPException(400,'素材列表无效')
        ids=list(dict.fromkeys(ids))
        if not ids:return []
        with hub.db() as db:
            sql="""SELECT a.id,COALESCE(l.category,'other') AS category,
                COALESCE(c.status,'waiting_model') AS classification_status FROM assets a
                LEFT JOIN asset_classification c ON c.asset_id=a.id LEFT JOIN asset_labels l ON l.asset_id=a.id
                WHERE a.owner=? AND a.id IN ("""+','.join('?' for _ in ids)+')'
            return [dict(r) for r in db.execute(sql,(u['id'],*ids))]

    @app.get('/api/workspace/materials-page')
    def materials_page(request: Request, offset:int=0, limit:int=50, q:str=''):
        u=user(request)
        if offset<0 or not 1<=limit<=100 or len(q)>200:raise HTTPException(400,'筛选参数无效')
        with hub.db() as db:
            where='a.owner=? AND instr(lower(a.name),lower(?))>0';params=(u['id'],q)
            total=db.execute('SELECT COUNT(*) FROM assets a WHERE '+where,params).fetchone()[0]
            rows=db.execute("""SELECT a.id,a.name,a.mime,a.size,a.created,
                COALESCE(l.category,'other') AS category, COALESCE(c.status,'waiting_model') AS classification_status, COALESCE(c.error,'') AS classification_error FROM assets a
                LEFT JOIN asset_classification c ON c.asset_id=a.id LEFT JOIN asset_labels l ON l.asset_id=a.id WHERE """+where+' ORDER BY a.created DESC,a.id DESC LIMIT ? OFFSET ?',(*params,limit,offset))
            return {'items':[dict(r) for r in rows],'total':total,'offset':offset,'limit':limit}

    @app.post('/api/workspace/materials/{aid}/classify')
    def classify_material(aid: str, request: Request):
        u=user(request)
        from asset_classification import enqueue
        try:return enqueue(hub,aid,u['id'],force=True)
        except ValueError:raise HTTPException(404,'素材不存在') from None

    @app.post('/api/workspace/materials/{aid}')
    async def label_material(aid: str, request: Request):
        u=user(request); data=await body(request)
        category=data.get('category'); name=data.get('name')
        if not any(k in data for k in ('name','category')):raise HTTPException(400,'请提供名称或分类')
        if 'category' in data and category not in ('person','product','scene','other'):
            raise HTTPException(400,'素材分类无效')
        if 'name' in data and (not isinstance(name,str) or not name.strip() or len(name)>200 or any(ord(c)<32 for c in name) or '/' in name or '\\' in name):
            raise HTTPException(400,'素材名称需为 1–200 字，不能包含路径或控制字符')
        with hub.db() as db:
            if not db.execute('SELECT 1 FROM assets WHERE id=? AND owner=?',(aid,u['id'])).fetchone():
                raise HTTPException(404,'素材不存在或无权访问')
            if 'name' in data:db.execute('UPDATE assets SET name=? WHERE id=?',(name.strip(),aid))
            if 'category' in data:
                db.execute('INSERT INTO asset_labels VALUES(?,?) ON CONFLICT(asset_id) DO UPDATE SET category=excluded.category',(aid,category))
                db.execute("INSERT INTO asset_classification(asset_id,status,folder,source,updated) VALUES(?,'manual',?,'manual',?) ON CONFLICT(asset_id) DO UPDATE SET status='manual',folder=excluded.folder,source='manual',error='',updated=excluded.updated",(aid,category,time.time()))
        return {'ok':True}

    @app.post('/api/workspace/materials/{aid}/delete')
    def delete_material(aid: str, request: Request):
        u=user(request)
        def contains(value):
            if isinstance(value,str):return value==aid
            if isinstance(value,list):return any(contains(v) for v in value)
            if isinstance(value,dict):return any(contains(v) for v in value.values())
            return False
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM assets WHERE id=? AND owner=?',(aid,u['id'])).fetchone()
            if not row:raise HTTPException(404,'素材不存在或无权访问')
            # Preserve projects, recovery snapshots and generation references, including pending jobs.
            for table,column,label in [('tasks','config','生成任务'),('compositions','content','制作草稿'),
                    ('continuation_drafts','content','接力草稿'),('edit_projects','body','剪辑项目'),
                    ('edit_versions','body','剪辑历史版本'),('edit_exports','body','导出任务')]:
                for ref in db.execute(f'SELECT {column} FROM {table} WHERE owner=?' if table!='edit_versions' else
                        'SELECT v.body FROM edit_versions v JOIN edit_projects p ON p.id=v.project_id WHERE p.owner=?',(u['id'],)):
                    try:used=contains(json.loads(ref[0] or '{}'))
                    except (ValueError,TypeError):used=True
                    if used:raise HTTPException(409,f'素材仍被{label}引用，不能删除；请先移除相关引用')
            if db.execute("SELECT 1 FROM voice_jobs WHERE asset_id=? AND owner=? AND completion_state='pending'",(aid,u['id'])).fetchone():
                raise HTTPException(409,'配音仍在自动保存处理中，请完成后再删除')
            path=hub.assets/row['id']
            # A rename is reversible if SQLite fails; no deleted file is served by its old ID.
            trash=hub.assets/(row['id']+'.deleting')
            try:
                if path.exists():path.replace(trash)
                for table in ('asset_labels','asset_classification','platform_images','derived_assets'):
                    db.execute(f'DELETE FROM {table} WHERE asset_id=?',(aid,))
                db.execute("UPDATE voice_jobs SET asset_id='' WHERE asset_id=? AND owner=?",(aid,u['id']))
                db.execute('DELETE FROM assets WHERE id=? AND owner=?',(aid,u['id']))
                db.commit()
            except Exception:
                db.rollback()
                if trash.exists():trash.replace(path)
                raise
        try:trash.unlink(missing_ok=True)
        except OSError:pass  # Inaccessible tombstone; retry cleanup during maintenance.
        return {'ok':True}

    @app.post('/api/workspace/link')
    async def link(request: Request):
        u = user(request); data = await body(request)
        pid = str(data.get('project_id', '')); tid = str(data.get('task_id', ''))
        try:
            app.state.editor.source(u['id'], u['role'] == 'admin', tid)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        with hub.db() as db:
            require_project(db, pid, u['id'])
            db.execute('INSERT OR IGNORE INTO project_tasks VALUES(?,?,?,?)', (pid, tid, u['id'], time.time()))
        return {'ok': True}

    @app.get('/api/workspace/continuation')
    def continuation(request: Request):
        u = user(request)
        with hub.db() as db:
            row = db.execute('SELECT content FROM continuation_drafts WHERE owner=?', (u['id'],)).fetchone()
        return json.loads(row['content']) if row else None

    @app.post('/api/workspace/continuation')
    async def save_continuation(request: Request):
        u = user(request); data = await body(request)
        try:
            from editor import probe, number
            duration, _ = probe(app.state.editor.source(u['id'], u['role'] == 'admin', str(data.get('source_id', ''))))
            frame = number(data.get('frame_time', 0), 0, duration)
            if data.get('model') not in ('auto', '5000005', 'mini', 'fast'):
                raise ValueError('请选择有效模型')
            if data.get('mode') not in ('omni', 'frames'):
                raise ValueError('请选择生成模式')
            if data['mode'] == 'frames' and data['model'] not in ('auto', '5000005'):
                raise ValueError('首尾帧模式只支持 Seedance 2.0')
            if type(data.get('duration')) is not int or not 4 <= data['duration'] <= 15:
                raise ValueError('时长需为 4–15 秒')
            if not isinstance(data.get('prompt', ''), str):
                raise ValueError('提示词格式有误')
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from None
        clean = {k: data.get(k) for k in ('source_id', 'project_id', 'model', 'mode', 'duration', 'prompt')}
        clean.update(frame_time=frame, inherit=bool(data.get('inherit')), add_library=bool(data.get('add_library', True)),
                     append_timeline=bool(data.get('append_timeline')))
        with hub.db() as db:
            if clean['project_id']:
                require_project(db, clean['project_id'], u['id'])
            if 'reference_ids' in data:
                ids=data['reference_ids']
                if not isinstance(ids,list) or len(ids)>12 or any(not isinstance(a,str) for a in ids):
                    raise HTTPException(400,'参考素材列表无效')
                for aid in ids:
                    if not db.execute('SELECT 1 FROM assets WHERE id=? AND owner=?',(aid,u['id'])).fetchone():
                        raise HTTPException(400,'参考素材不存在或无权使用')
                clean['reference_ids']=list(dict.fromkeys(ids))
                tokens=data.get('reference_tokens',{})
                if not isinstance(tokens,dict):
                    raise HTTPException(400,'参考图片标识无效')
                import re
                clean['reference_tokens']={}
                for aid in ids:
                    token=tokens.get(aid)
                    if token is not None:
                        if not isinstance(token,str) or not re.fullmatch(r'图片[2-9][0-9]*|图片1[0-9]+',token):
                            raise HTTPException(400,'参考图片标识无效')
                        clean['reference_tokens'][aid]=token
                if len(set(clean['reference_tokens'].values()))!=len(clean['reference_tokens']):
                    raise HTTPException(400,'参考图片标识不能重复')
            for key,kind in [('frame_id','image/'),('audio_id','audio/')]:
                aid=data.get(key)
                if aid:
                    asset=db.execute('SELECT * FROM assets WHERE id=? AND owner=?',(str(aid),u['id'])).fetchone()
                    if not asset or not asset['mime'].startswith(kind):raise HTTPException(400,'参考素材不存在或无权使用')
                    if key=='frame_id':
                        derived=db.execute("SELECT start FROM derived_assets WHERE asset_id=? AND source_task=? AND owner=? AND kind='frame'",(aid,clean['source_id'],u['id'])).fetchone()
                        if not derived:raise HTTPException(400,'参考帧与来源视频不一致')
                        clean['frame_time']=derived['start']
                    clean[key]=aid
            db.execute('INSERT INTO continuation_drafts VALUES(?,?,?) ON CONFLICT(owner) DO UPDATE SET content=excluded.content,updated=excluded.updated',
                       (u['id'], json.dumps(clean, ensure_ascii=False), time.time()))
        return clean
