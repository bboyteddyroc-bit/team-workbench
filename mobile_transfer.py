"""Scoped, expiring mobile transfer; no directory exposure or login-cookie sharing."""
import hashlib,json,secrets,time,tempfile,zipfile,threading,shutil
from pathlib import Path
from urllib.parse import quote
from fastapi import HTTPException,Request
from fastapi.responses import FileResponse,HTMLResponse,Response
from starlette.background import BackgroundTask
import segno
import io

def attach(app,hub,user,body,origin,upload):
    from mobile_http import mobile_origin as configured_origin
    mobile_origin=configured_origin()
    zip_slots=threading.BoundedSemaphore(2)
    editor=app.state.editor
    with hub.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS mobile_transfers (id TEXT PRIMARY KEY, token TEXT UNIQUE, owner TEXT, expires REAL, exports TEXT, revoked INTEGER DEFAULT 0)')
    def session(token):
        with hub.db() as db:
            r=db.execute('SELECT m.* FROM mobile_transfers m JOIN users u ON u.id=m.owner WHERE m.token=? AND m.expires>? AND m.revoked=0 AND u.enabled=1',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not r:raise HTTPException(410,'传输链接已失效，请在电脑重新生成二维码')
        return r
    def files(r):
        out=[]
        with hub.db() as db:
            for eid in json.loads(r['exports']):
                row=db.execute("SELECT body FROM edit_exports WHERE id=? AND owner=? AND state='ready'",(eid,r['owner'])).fetchone();p=editor.root/(eid+'.mp4')
                if row and p.is_file():out.append(dict(id=eid,name=(json.loads(row['body']).get('export_name') or 'video')+'.mp4',size=p.stat().st_size))
        return out
    @app.get('/api/mobile/received')
    def received(request:Request):
        u=user(request)
        with hub.db() as db:r=db.execute('SELECT COUNT(*),MAX(created) FROM edit_footage WHERE owner=?',(u['id'],)).fetchone()
        return {'revision':str(r[0])+':'+str(r[1])}
    def selected_exports(db,owner,ids):
        if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(x,str) for x in ids):raise HTTPException(400,'请选择有效成品')
        ids=list(dict.fromkeys(ids))
        for eid in ids:
            if not db.execute("SELECT 1 FROM edit_exports WHERE id=? AND owner=? AND state='ready'",(eid,owner)).fetchone() or not (editor.root/(eid+'.mp4')).is_file():raise HTTPException(404,'成品未完成或无权分享')
        return ids
    @app.post('/api/mobile/transfers/{tid}/selection')
    async def update_selection(tid:str,request:Request):
        u=user(request);d=await body(request)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT expires FROM mobile_transfers WHERE id=? AND owner=? AND revoked=0 AND expires>?',(tid,u['id'],time.time())).fetchone()
            if not row:raise HTTPException(410,'传输链接已失效，请重新生成二维码')
            ids=selected_exports(db,u['id'],d.get('exports',[]))
            db.execute('UPDATE mobile_transfers SET exports=? WHERE id=?',(json.dumps(ids),tid))
        return {'expires':row['expires'],'count':len(ids)}
    @app.post('/api/mobile/transfers')
    async def create(request:Request):
        u=user(request);d=await body(request)
        with hub.db() as db:
            ids=selected_exports(db,u['id'],d.get('exports',[]))
            if db.execute('SELECT COUNT(*) FROM mobile_transfers WHERE owner=? AND expires>? AND revoked=0',(u['id'],time.time())).fetchone()[0]>=10:raise HTTPException(409,'有效传输链接过多，请先撤销旧链接')
            token=secrets.token_urlsafe(32);tid=secrets.token_hex(12);expires=time.time()+1800
            db.execute('INSERT INTO mobile_transfers VALUES(?,?,?,?,?,0)',(tid,hashlib.sha256(token.encode()).hexdigest(),u['id'],expires,json.dumps(ids)))
        return dict(id=tid,url=mobile_origin+'/mobile/#'+token,expires=expires,qr='/api/mobile/transfers/'+tid+'/qr?token='+quote(token))
    @app.get('/api/mobile/transfers/{tid}/qr')
    def qr(tid:str,token:str,request:Request):
        u=user(request);r=session(token)
        if r['id']!=tid or r['owner']!=u['id']:raise HTTPException(404)
        out=io.BytesIO();segno.make(mobile_origin+'/mobile/#'+token).save(out,kind='svg',scale=5)
        return Response(out.getvalue(),media_type='image/svg+xml')
    @app.post('/api/mobile/transfers/{tid}/revoke')
    def revoke(tid:str,request:Request):
        u=user(request)
        with hub.db() as db:db.execute('UPDATE mobile_transfers SET revoked=1 WHERE id=? AND owner=?',(tid,u['id']))
        return {'ok':True}
    def auth(request):return session(request.headers.get('x-transfer-token',''))
    @app.get('/mobile/')
    def page():return FileResponse(Path(__file__).parent/'static/mobile-transfer.html',media_type='text/html')
    @app.get('/api/mobile/session')
    def info(request:Request):
        r=auth(request);return dict(expires=r['expires'],files=files(r))
    from mobile_progress import UploadProgress
    progress=UploadProgress(hub)
    @app.get('/api/mobile/progress')
    def desktop_upload_progress(request:Request):
        return {'items':progress.recent(user(request)['id'])}
    @app.post('/api/mobile/upload')
    async def receive(request:Request):
        r=auth(request)
        return await progress.receive(request,r['owner'],upload)
    @app.get('/api/mobile/file/{eid}')
    def download(eid:str,token:str):
        r=session(token);f=next((f for f in files(r) if f['id']==eid),None)
        if not f:raise HTTPException(404)
        return FileResponse(editor.root/(eid+'.mp4'),media_type='video/mp4',filename=f['name'])
    @app.post('/api/mobile/zip')
    async def package(request:Request):
        r=auth(request);d=await body(request)
        return await build_package(r,d.get('ids',[]))
    @app.get('/api/mobile/zip-download')
    async def zip_download(token:str,ids:str):
        return await build_package(session(token),ids.split(','))
    async def build_package(r,ids):
        allowed={f['id']:f for f in files(r)}
        if not isinstance(ids,list) or not ids or len(ids)>100 or any(not isinstance(i,str) or i not in allowed for i in ids):raise HTTPException(400,'请选择有效成品')
        # Bound disk usage; no compression/re-encoding of existing MP4s.
        ids=list(dict.fromkeys(ids))
        if sum(allowed[i]['size'] for i in ids)>4*1024**3:raise HTTPException(413,'打包总大小不能超过 4 GB，请分批下载')
        if not zip_slots.acquire(blocking=False):raise HTTPException(429,'打包资源繁忙，请等待当前下载完成')
        total=sum(allowed[i]['size'] for i in ids)
        try:space=shutil.disk_usage(editor.root).free
        except OSError:
            zip_slots.release()
            raise HTTPException(503,'无法确认可用空间，未创建下载包') from None
        if space<total+64*1024**2:
            zip_slots.release()
            raise HTTPException(507,'可用空间不足，未创建下载包')
        def build():
            import os
            fd,name=tempfile.mkstemp(suffix='.zip',dir=editor.root);os.close(fd);p=Path(name)
            try:
                with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
                    for n,i in enumerate(ids,1):z.write(editor.root/(i+'.mp4'),str(n)+'_'+Path(allowed[i]['name'].replace('\\','/')).name)
                return p
            except BaseException:p.unlink(missing_ok=True);raise
        from starlette.concurrency import run_in_threadpool
        try:p=await run_in_threadpool(build)
        except BaseException:
            zip_slots.release();raise
        def cleanup():
            try:p.unlink(missing_ok=True)
            finally:zip_slots.release()
        return FileResponse(p,media_type='application/zip',filename='videos.zip',background=BackgroundTask(cleanup))
