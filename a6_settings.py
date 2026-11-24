"""Separately stored A6 credential; saving never starts inference or switches provider."""
import time
from fastapi import Request,HTTPException

def attach(app,hub,user,body):
 with hub.db() as db:
  db.execute('CREATE TABLE IF NOT EXISTS a6_settings(id INTEGER PRIMARY KEY CHECK(id=1),secret BLOB NOT NULL,updated REAL NOT NULL)')
 @app.get('/api/assistant/a6-settings')
 def status(request:Request):
  user(request,True)
  with hub.db() as db:r=db.execute('SELECT updated FROM a6_settings WHERE id=1').fetchone()
  return {'configured':bool(r),'updated':r['updated'] if r else None,'active':bool(r),'model':'gemini-3.8-flash'}
 @app.post('/api/assistant/a6-settings')
 async def save(request:Request):
  u=user(request,True);data=await body(request);key=data.get('key')
  if not isinstance(key,str) or not 10<=len(key.strip())<=4096 or any(ord(c)<33 or ord(c)>126 for c in key.strip()):raise HTTPException(400,'请输入有效的 A6API 密钥，不能包含空格')
  encrypted=hub.cipher.encrypt(key.strip().encode())
  with hub.db() as db:
   db.execute('INSERT INTO a6_settings VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET secret=excluded.secret,updated=excluded.updated',(encrypted,time.time()))
   hub.log(db,u['id'],'a6_key_saved','a6_settings')
  return {'saved':True,'active':True}
