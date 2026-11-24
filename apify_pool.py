"""Administrator-managed encrypted tokens, durable per-run round robin binding."""
import hashlib,json,math,secrets,time
import httpx
from fastapi import HTTPException,Request

class KeyPool:
 def __init__(self,hub,config):
  self.hub,self.config=hub,config
  with hub.db() as db:
   db.executescript('''CREATE TABLE IF NOT EXISTS apify_keys(id TEXT PRIMARY KEY,name TEXT NOT NULL,secret BLOB NOT NULL,fingerprint TEXT UNIQUE,enabled INTEGER NOT NULL DEFAULT 1,state TEXT NOT NULL DEFAULT 'unchecked',last_used REAL NOT NULL DEFAULT 0,checked REAL,usage REAL,limit_usd REAL,error TEXT);
   CREATE TABLE IF NOT EXISTS apify_key_bindings(run TEXT PRIMARY KEY,key_id TEXT NOT NULL);''')
   exists=db.execute('SELECT 1 FROM apify_keys LIMIT 1').fetchone()
  if not exists:
   token=config.secret()
   if token:self.add('原有中台密钥',token,key_id='legacy')
 def add(self,name,token,key_id=None):
  if not isinstance(token,str) or not 8<=len(token.strip())<=4096 or any(ord(c)<33 or ord(c)>126 for c in token.strip()):raise HTTPException(400,'请输入有效的 Apify API Token')
  token=token.strip();name=str(name or 'Apify 密钥').strip()[:80]
  with self.hub.db() as db:
   if db.execute('SELECT 1 FROM apify_keys WHERE fingerprint=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone():raise HTTPException(409,'此密钥已存在，不重复添加')
   db.execute('INSERT INTO apify_keys(id,name,secret,fingerprint) VALUES(?,?,?,?)',(key_id or secrets.token_hex(12),name,self.hub.cipher.encrypt(token.encode()),hashlib.sha256(token.encode()).hexdigest()))
 def token(self,binding,submit=False,budget=0):
  with self.hub.db() as db:
   db.execute('BEGIN IMMEDIATE')
   row=db.execute('SELECT k.* FROM apify_keys k JOIN apify_key_bindings b ON b.key_id=k.id WHERE b.run=?',(binding,)).fetchone()
   if not row and submit:
    row=db.execute("SELECT * FROM apify_keys WHERE enabled=1 AND state NOT IN ('invalid','forbidden','exhausted','rate_limited') ORDER BY CASE WHEN limit_usd-usage>=? THEN 0 WHEN limit_usd IS NULL OR usage IS NULL THEN 1 ELSE 2 END,last_used,id LIMIT 1",(budget,)).fetchone()
    if not row:raise ValueError('Apify 密钥池没有可用密钥，请管理员核验状态')
    db.execute('INSERT INTO apify_key_bindings VALUES(?,?)',(binding,row['id']))
    db.execute('UPDATE apify_keys SET last_used=? WHERE id=?',(time.time(),row['id']))
   if row:return self.hub.cipher.decrypt(bytes(row['secret'])).decode()
  # Runs created before the pool must keep their original credential, never rotate.
  with self.hub.db() as db:legacy=db.execute("SELECT secret FROM apify_keys WHERE id='legacy'").fetchone()
  if legacy:return self.hub.cipher.decrypt(bytes(legacy['secret'])).decode()
  raise ValueError('旧任务没有原始密钥绑定，不能自动切换账号；请管理员核对')
 def available(self):
  with self.hub.db() as db:
   count=db.execute('SELECT COUNT(*) FROM apify_keys').fetchone()[0]
   ready=bool(db.execute("SELECT 1 FROM apify_keys WHERE enabled=1 AND state NOT IN ('invalid','forbidden','exhausted','rate_limited') LIMIT 1").fetchone())
  if not count:
   token=self.config.secret()
   if token:
    self.add('原有中台密钥',token,key_id='legacy')
    return True
  return ready
 def rows(self):
  with self.hub.db() as db:
   return [dict(r) for r in db.execute('SELECT id,name,enabled,state,last_used,checked,usage,limit_usd,error FROM apify_keys ORDER BY rowid')]
 def mark(self,binding,status):
  state={401:'invalid',403:'forbidden',402:'exhausted',429:'rate_limited'}.get(status)
  if state:
   with self.hub.db() as db:db.execute('UPDATE apify_keys SET state=?,error=? WHERE id=(SELECT key_id FROM apify_key_bindings WHERE run=?)',(state,'采集接口 HTTP '+str(status),binding))
 def refresh(self,kid):
  with self.hub.db() as db:r=db.execute('SELECT secret FROM apify_keys WHERE id=?',(kid,)).fetchone()
  if not r:raise HTTPException(404,'密钥不存在')
  token=self.hub.cipher.decrypt(bytes(r['secret'])).decode();usage=limit=None;error=None;state='ready'
  try:
   with httpx.Client(timeout=15,trust_env=False) as client:
    def get(path):
     response=client.get('https://api.apify.com/v2'+path,headers={'Authorization':'Bearer '+token})
     response.raise_for_status();return response.json()['data']
    get('/users/me')
    limits=get('/users/me/limits')
    limit=limits.get('limits',{}).get('maxMonthlyUsageUsd')
    usage=limits.get('current',{}).get('monthlyUsageUsd')
    def number(v):return float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) else None
    usage,limit=number(usage),number(limit)
  except httpx.HTTPStatusError as exc:
   status=exc.response.status_code;state={401:'invalid',403:'forbidden',402:'exhausted',429:'rate_limited'}.get(status,'error');error='余额核验 HTTP '+str(status)
  except (httpx.HTTPError,ValueError,KeyError):state='error';error='余额核验失败，请稍后刷新；未发起采集'
  with self.hub.db() as db:db.execute('UPDATE apify_keys SET state=?,checked=?,usage=?,limit_usd=?,error=? WHERE id=?',(state,time.time(),usage,limit,error,kid))
  return self.rows()

def attach(app,hub,user,body,config):
 pool=KeyPool(hub,config);app.state.apify_pool=pool
 @app.get('/api/intelligence/apify/pool')
 def listing(request:Request):
  user(request,True);return {'items':pool.rows()}
 @app.post('/api/intelligence/apify/pool')
 async def add(request:Request):
  u=user(request,True);data=await body(request);pool.add(data.get('name'),data.get('secret_key'))
  with hub.db() as db:hub.log(db,u['id'],'apify_pool_added','apify_pool')
  return {'items':pool.rows()}
 @app.post('/api/intelligence/apify/pool/{kid}/toggle')
 async def toggle(kid:str,request:Request):
  user(request,True);data=await body(request)
  if not isinstance(data.get('enabled'),bool):raise HTTPException(400,'请选择启用或停用')
  with hub.db() as db:
   if not db.execute('SELECT 1 FROM apify_keys WHERE id=?',(kid,)).fetchone():raise HTTPException(404,'密钥不存在')
   db.execute('UPDATE apify_keys SET enabled=? WHERE id=?',(int(data['enabled']),kid))
  return {'items':pool.rows()}
 @app.post('/api/intelligence/apify/pool/{kid}/refresh')
 def refresh(kid:str,request:Request):
  user(request,True);return {'items':pool.refresh(kid)}
 return pool
