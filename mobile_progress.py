"""Server-observed streamed byte progress, shared between Hub processes via SQLite."""
import secrets,time
from urllib.parse import unquote
from fastapi import HTTPException

class UploadProgress:
    def __init__(self,hub):
        self.hub=hub
        with hub.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS mobile_upload_progress(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,total INTEGER NOT NULL,received INTEGER NOT NULL,state TEXT NOT NULL,updated REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS mobile_progress_owner ON mobile_upload_progress(owner,updated)')
    def recent(self,owner):
        now=time.time()
        with self.hub.db() as db:
            rows=db.execute('SELECT id,name,total,received,state,updated FROM mobile_upload_progress WHERE owner=? AND updated>? ORDER BY updated DESC LIMIT 30',(owner,now-3600)).fetchall()
        result=[]
        for row in rows:
            d=dict(row)
            if d['state'] in ('uploading','verifying') and now-d['updated']>90:d['state']='stalled'
            result.append(d)
        return result
    async def receive(self,request,owner,upload):
        uid=secrets.token_hex(16)
        try:total=max(0,int(request.headers.get('content-length','0')))
        except ValueError:total=0
        name=unquote(request.headers.get('x-file-name','手机视频')).replace('\\','/').split('/')[-1][:160]
        received=0;last=0
        with self.hub.db() as db:
            db.execute('DELETE FROM mobile_upload_progress WHERE updated<?',(time.time()-86400,))
            db.execute('INSERT INTO mobile_upload_progress VALUES(?,?,?,?,?,?,?)',(uid,owner,name,total,0,'uploading',time.time()))
        def update(state):
            with self.hub.db() as db:db.execute('UPDATE mobile_upload_progress SET received=?,state=?,updated=? WHERE id=?',(received,state,time.time(),uid))
        class ObservedRequest:
            headers=request.headers
            async def body(self):
                return b''.join([chunk async for chunk in self.stream()])
            async def stream(self):
                nonlocal received,last
                async for chunk in request.stream():
                    received+=len(chunk)
                    if time.monotonic()-last>=0.75:
                        update('uploading');last=time.monotonic()
                    yield chunk
                update('verifying')
        try:
            result=await upload(ObservedRequest(),{'id':owner})
            update('done')
            return result
        except HTTPException:
            update('failed');raise
        except BaseException:
            update('unknown');raise
