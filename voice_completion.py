"""Local post-processing of already generated speech. Never calls the provider."""
import hashlib,json,os,secrets,shutil,time
from fastapi import HTTPException
from editor import Editor,record_version


def save_asset(voice,owner,jid):
    with voice.hub.db() as db:
        row=db.execute("SELECT * FROM voice_jobs WHERE id=? AND owner=? AND state='ready'",(jid,owner)).fetchone()
    if not row or not row['audio_path']:raise HTTPException(404,'配音未完成或无权使用')
    path=voice.files/row['audio_path']
    if not path.is_file():raise ValueError('配音文件缺失')
    aid=hashlib.sha256(('voice:'+owner+':'+jid).encode()).hexdigest()[:24]
    target=voice.hub.assets/aid
    if not target.exists():
        tmp=voice.hub.assets/(aid+'.'+secrets.token_hex(4)+'.tmp')
        try:shutil.copyfile(path,tmp);os.replace(tmp,target)
        finally:tmp.unlink(missing_ok=True)
    mime={'.wav':'audio/wav','.mp3':'audio/mpeg','.opus':'audio/ogg'}.get(path.suffix,'audio/wav')
    with voice.hub.db() as db:
        db.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?,?)',
                   (aid,owner,'AI配音-'+row['text'][:30]+path.suffix,mime,target.stat().st_size,time.time()))
        db.execute('UPDATE voice_jobs SET asset_id=? WHERE id=?',(aid,jid))
    return aid


def finish(voice,jid):
    with voice.hub.db() as db:job=db.execute("SELECT * FROM voice_jobs WHERE id=? AND state='ready'",(jid,)).fetchone()
    if not job or job['completion_state']!='pending':return
    workflow=json.loads(job['workflow'] or '{}');status='';message=''
    try:
        if workflow.get('auto_asset'):save_asset(voice,job['owner'],jid)
        if workflow.get('auto_timeline'):
            with voice.hub.db() as db:
                project=db.execute('SELECT * FROM edit_projects WHERE id=? AND owner=?',(job['project_id'],job['owner'])).fetchone()
                user=db.execute('SELECT role FROM users WHERE id=?',(job['owner'],)).fetchone()
            if not project or project['version']!=workflow.get('project_version'):raise ValueError('生成期间剪辑已修改，请确认后手动加入配音轨')
            body=json.loads(project['body']);sounds=body.setdefault('audio_clips',[])
            if not any(c.get('voice_job_id')==jid for c in sounds):
                sounds.append(dict(source='voice',voice_job_id=jid,start=0,end=job['duration'],at=job['insert_at'],volume=1,locked=False,muted=False,fade_in=0,fade_out=0,link_captions=False))
                body=Editor(voice.hub).validate(body,job['owner'],bool(user and user['role']=='admin'))
                with voice.hub.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    changed=db.execute('UPDATE edit_projects SET body=?,version=version+1,updated=? WHERE id=? AND owner=? AND version=?',
                        (json.dumps(body,ensure_ascii=False),time.time(),project['id'],job['owner'],project['version'])).rowcount
                    if not changed:raise ValueError('剪辑已被其他窗口修改，请手动加入配音轨')
                    record_version(db,project['id'])
            status='added'
    except (ValueError,HTTPException) as e:
        status='needs_review';message=str(e.detail if isinstance(e,HTTPException) else e)
    except Exception:
        status='needs_review';message='自动保存或加入失败，音频已保留，请从任务结果重试'
    with voice.hub.db() as db:
        db.execute("UPDATE voice_jobs SET completion_state='done',timeline_status=?,workflow_error=?,updated=? WHERE id=?",(status,message,time.time(),jid))
