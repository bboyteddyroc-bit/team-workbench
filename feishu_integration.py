"""Feishu OAuth and owner-scoped export archive. No provider credentials reach clients."""
import hashlib,json,re,secrets,sqlite3,threading,time,zlib,logging
from datetime import datetime,timezone,timedelta
from urllib.parse import urlencode,urlsplit
import httpx
from fastapi import HTTPException,Request
from fastapi.responses import RedirectResponse,HTMLResponse
from fastapi.concurrency import run_in_threadpool

API='https://open.feishu.cn/open-apis/'
SCOPES='offline_access drive:file space:document:retrieve space:folder:create'
CALLBACK='/api/feishu/callback'

def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def folder_token(value):
    u=urlsplit(str(value).strip())
    if u.scheme!='https' or not (u.hostname or '').endswith('.feishu.cn'):raise ValueError('请填写飞书云盘文件夹的 HTTPS 链接')
    m=re.fullmatch(r'/drive/folder/([A-Za-z0-9_-]+)',u.path.rstrip('/'))
    if not m:raise ValueError('请使用云盘文件夹链接，不是文档或多维表格链接')
    return m[1]

class Feishu:
    def __init__(self,hub):
        self.hub=hub;self.lock=threading.RLock()
        with hub.db() as db:db.executescript('''
        CREATE TABLE IF NOT EXISTS feishu_config(id INTEGER PRIMARY KEY,secret BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS feishu_links(owner TEXT PRIMARY KEY,subject TEXT UNIQUE NOT NULL,name TEXT,secret BLOB NOT NULL,expires REAL);
        CREATE TABLE IF NOT EXISTS feishu_prefs(owner TEXT PRIMARY KEY,folder TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS feishu_states(state TEXT PRIMARY KEY,nonce TEXT NOT NULL,owner TEXT,session TEXT,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS feishu_uploads(export_id TEXT PRIMARY KEY,owner TEXT NOT NULL,folder TEXT NOT NULL,day TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',file_token TEXT NOT NULL DEFAULT '',upload_id TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL);
        ''')
        with hub.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS feishu_refresh(owner TEXT PRIMARY KEY,lease TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL)')
            columns={r['name'] for r in db.execute('PRAGMA table_info(feishu_uploads)')}
            for name in ('phase','target_folder','local_sha256','remote_name'):
                if name not in columns:db.execute(f"ALTER TABLE feishu_uploads ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            if 'local_size' not in columns:db.execute('ALTER TABLE feishu_uploads ADD COLUMN local_size INTEGER NOT NULL DEFAULT 0')
            for name in ('block_size','block_num','next_part','transfer_at'):
                if name not in columns:db.execute(f'ALTER TABLE feishu_uploads ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
            # Old clients may already have sent finish without a durable phase.
            # Preserve ambiguity instead of resending a possibly committed finish.
            db.execute("UPDATE feishu_uploads SET phase='finish_unknown' WHERE phase='' AND file_token='' AND upload_id!='' AND block_num>0 AND next_part>=block_num AND state IN ('attention','uploading','waiting')")
    def pack(self,data):return self.hub.cipher.encrypt(json.dumps(data).encode())
    def unpack(self,data):return json.loads(self.hub.cipher.decrypt(data))
    def config(self):
        with self.hub.db() as db:r=db.execute('SELECT secret FROM feishu_config WHERE id=1').fetchone()
        return self.unpack(r['secret']) if r else {}
    def call(self,path,token=None,method='GET',**kwargs):
        headers={'Authorization':'Bearer '+token} if token else {}
        try:
            # Feishu is directly reachable; avoid inheriting malformed system proxy / NO_PROXY
            # settings and never fall back to a proxy with OAuth credentials.
            with httpx.Client(timeout=90,follow_redirects=False,trust_env=False) as c:r=c.request(method,API+path,headers=headers,**kwargs)
            data=r.json()
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            # Never log OAuth codes, tokens, payloads or response bodies.
            logging.getLogger('hub.feishu').warning('Feishu transport failure endpoint=%s type=%s',path.split('?')[0],type(exc).__name__)
            reason='请求超时' if isinstance(exc,httpx.TimeoutException) else '连接失败'
            raise ValueError('服务器访问飞书'+reason+'，请返回中台重新点击飞书登录或绑定，不要刷新当前回调页面') from None
        except ValueError:
            logging.getLogger('hub.feishu').warning('Feishu non-JSON response endpoint=%s status=%s',path.split('?')[0],r.status_code)
            raise ValueError('飞书接口返回异常，请返回中台重新发起授权') from None
        if r.status_code>=400 or data.get('code',0)!=0 or data.get('error'):
            code=data.get('code',r.status_code)
            raise ValueError(f'飞书请求失败（{code}），请检查授权、应用发布状态和文件夹权限')
        return data.get('data',data)
    def token(self,owner):
        from feishu_refresh import token
        return token(self,owner)
    def list_folder(self,token,folder):
        result=[];page=None
        while True:
            args={'folder_token':folder,'page_size':200}
            if page:args['page_token']=page
            data=self.call('drive/v1/files',token,params=args);result.extend(data.get('files',[]))
            if not data.get('has_more'):return result
            page=data.get('next_page_token')
            if not page:raise ValueError('飞书文件列表分页不完整')
    def queue(self,db,eid,owner,created):
        p=db.execute('SELECT * FROM feishu_prefs WHERE owner=? AND enabled=1',(owner,)).fetchone()
        if not p:return
        day=datetime.fromtimestamp(created,timezone(timedelta(hours=8))).strftime('%y%m%d')
        db.execute('INSERT OR IGNORE INTO feishu_uploads(export_id,owner,folder,day,state,created,updated) VALUES(?,?,?,?,?,?,?)',(eid,owner,p['folder'],day,'waiting',created,created))
    def recover(self):
        with self.hub.db() as db:db.execute("UPDATE feishu_uploads SET state='attention',error='上传因重启中断，请重试；将先核对远端同名成片' WHERE state='uploading'")
    def tick(self):
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE feishu_uploads SET state='failed',error='视频渲染失败，请先重新导出' WHERE state='waiting' AND export_id IN (SELECT id FROM edit_exports WHERE state='failed')")
            r=db.execute("SELECT f.* FROM feishu_uploads f JOIN edit_exports e ON f.export_id=e.id JOIN users u ON u.id=f.owner WHERE f.state='waiting' AND e.state='ready' AND u.enabled=1 ORDER BY f.created LIMIT 1").fetchone()
            if not r:return
            db.execute("UPDATE feishu_uploads SET state='uploading',updated=? WHERE export_id=?",(time.time(),r['export_id']))
        try:
            self.upload(dict(r));state,error='ready',''
        except Exception as e:state,error='attention',str(e) if isinstance(e,ValueError) else '上传未完成，请重试；本地成片仍保留'
        with self.hub.db() as db:db.execute('UPDATE feishu_uploads SET state=?,error=?,updated=? WHERE export_id=?',(state,error,time.time(),r['export_id']))
    def upload(self,job):
        if job.get('phase')=='finish_unknown' and not job.get('file_token'):
            raise ValueError('原上传完成请求结果未知，请在飞书核对并使用“关联已上传文件”；未重复上传或再次完成提交')
        if job.get('file_token'):
            if job.get('phase')=='confirmed':return
            raise ValueError('历史归档缺少已验证的内容确认，请人工核对；未重复上传')
        token=self.token(job['owner']);items=self.list_folder(token,job['folder'])
        folders=[x for x in items if x.get('type')=='folder' and x.get('name')==job['day']]
        if len(folders)>1:raise ValueError('主文件夹下存在多个同名日期目录，请先整理后重试')
        folder=folders[0]['token'] if folders else self.call('drive/v1/files/create_folder',token,'POST',json={'name':job['day'],'folder_token':job['folder']})['token']
        with self.hub.db() as db:export=db.execute('SELECT body FROM edit_exports WHERE id=?',(job['export_id'],)).fetchone()
        title=json.loads(export['body']).get('export_name') if export else None
        name=(title or '成片')+'.mp4'
        # Old versions used a unique export-id suffix. Recognize it when recovering
        # an existing job, but never mistake an unrelated same-name file for success.
        legacy_name=(title+'_'+job['export_id'] if title else '成片_'+job['export_id'])+'.mp4'
        files=[x for x in self.list_folder(token,folder) if x.get('type')=='file']
        legacy=[x for x in files if x.get('name')==legacy_name]
        if legacy:
            raise ValueError('存在旧规则同名文件，但不能仅凭文件名确认原内容；请人工核对，未重复上传或标记成功')
        elif any(x.get('name')==name for x in files):
            raise ValueError('飞书日期目录已存在同名文件，请先核对该文件或调整导出名称，避免误认或重复上传')
        else:
            path=self.hub.directory/'edits'/(job['export_id']+'.mp4')
            if not path.is_file():raise ValueError('本地成片文件不存在，请重新导出')
            if job['upload_id']:
                if time.time()-job['transfer_at']>=23*3600:raise ValueError('原上传事务已过期，请先核对飞书目录；未重复上传')
                uid=job['upload_id'];block=job['block_size'];count=job['block_num'];start=job['next_part']
            else:
                data=self.call('drive/v1/files/upload_prepare',token,'POST',json={'file_name':name,'parent_type':'explorer','parent_node':folder,'size':path.stat().st_size})
                uid=data['upload_id'];block=data['block_size'];count=data['block_num'];start=0
                with self.hub.db() as db:db.execute('UPDATE feishu_uploads SET upload_id=?,block_size=?,block_num=?,transfer_at=? WHERE export_id=?',(uid,block,count,int(time.time()),job['export_id']))
            if not isinstance(block,int) or not 0<block<=20*1024*1024:raise ValueError('飞书返回的分片大小无效')
            with path.open('rb') as f:
                f.seek(start*block)
                for seq in range(start,count):
                    chunk=f.read(block)
                    self.call('drive/v1/files/upload_part',token,'POST',data={'upload_id':uid,'seq':str(seq),'size':str(len(chunk)),'checksum':str(zlib.adler32(chunk)&0xffffffff)},files={'file':('chunk',chunk,'application/octet-stream')})
                    with self.hub.db() as db:db.execute('UPDATE feishu_uploads SET next_part=? WHERE export_id=?',(seq+1,job['export_id']))
            sha=hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda:source.read(1024*1024),b''):sha.update(chunk)
            with self.hub.db() as db:db.execute("UPDATE feishu_uploads SET phase='finish_unknown',target_folder=?,remote_name=?,local_size=?,local_sha256=? WHERE export_id=?",(folder,name,path.stat().st_size,sha.hexdigest(),job['export_id']))
            fid=self.call('drive/v1/files/upload_finish',token,'POST',json={'upload_id':uid,'block_num':count})['file_token']
        with self.hub.db() as db:db.execute("UPDATE feishu_uploads SET file_token=?,phase='confirmed' WHERE export_id=?",(fid,job['export_id']))
    def verify_uploaded(self,job,fid):
        token=self.token(job['owner'])
        matches=[x for x in self.list_folder(token,job['target_folder']) if x.get('token')==fid and x.get('type')=='file' and x.get('name')==job['remote_name']]
        if len(matches)!=1:raise ValueError('文件不在原目标目录或名称不匹配')
        # Human confirmation alone is not evidence. Verify the remote bytes against
        # the persisted task fingerprint; if scopes/API cannot read, fail closed.
        sha=hashlib.sha256();size=0;deadline=time.monotonic()+180
        with httpx.Client(timeout=30,follow_redirects=False,trust_env=False) as client:
            with client.stream('GET',API+'drive/v1/files/'+fid+'/download',headers={'Authorization':'Bearer '+token,'Accept-Encoding':'identity'}) as response:
                if response.status_code!=200:raise ValueError('无法读取原上传文件核对，未关联；请核对飞书权限')
                for chunk in response.iter_bytes(65536):
                    size+=len(chunk)
                    if size>job['local_size'] or time.monotonic()>deadline:raise ValueError('远端文件大小不匹配或核对超时')
                    sha.update(chunk)
        if size!=job['local_size'] or sha.hexdigest()!=job['local_sha256']:raise ValueError('远端文件内容与本次成片指纹不同，未关联')

    def loop(self):
        while not self.hub.stop.is_set():
            try:self.tick()
            except Exception:pass
            self.hub.stop.wait(3)

def attach(app,hub,user,body,origin):
    service=Feishu(hub);app.state.feishu=service;hub.feishu=service
    def configured():
        c=service.config()
        if not c.get('app_secret'):raise HTTPException(503,'管理员尚未配置飞书应用')
        return c
    @app.get('/api/feishu/status')
    def status(request:Request):
        u=user(request);c=service.config()
        with hub.db() as db:
            link=db.execute('SELECT name FROM feishu_links WHERE owner=?',(u['id'],)).fetchone();p=db.execute('SELECT folder,enabled FROM feishu_prefs WHERE owner=?',(u['id'],)).fetchone()
        return {'configured':bool(c),'name':link['name'] if link else None,'bound':bool(link),'folder':('https://www.feishu.cn/drive/folder/'+p['folder']) if p else '', 'enabled':bool(p and p['enabled']),'origin':c.get('origin'),'admin':u['role']=='admin'}
    @app.get('/api/feishu/public')
    def public():
        c=service.config();return {'configured':bool(c),'origin':c.get('origin')}
    @app.post('/api/feishu/config')
    async def config(request:Request):
        user(request,True);d=await body(request)
        appid=str(d.get('app_id',''));secret=str(d.get('app_secret',''));base=str(d.get('origin','')).rstrip('/')
        if not re.fullmatch(r'cli_[a-zA-Z0-9]+',appid) or not 8<=len(secret)<=512 or base!='https://192.168.100.10:8443':raise HTTPException(400,'请填写正确的 App ID、App Secret 和团队 HTTPS 地址')
        with hub.db() as db:
            old=service.config()
            if old and old.get('app_id')!=appid and db.execute('SELECT 1 FROM feishu_links LIMIT 1').fetchone():raise HTTPException(409,'已有关联账号，不能直接更换应用')
            db.execute('INSERT OR REPLACE INTO feishu_config VALUES(1,?)',(service.pack({'app_id':appid,'app_secret':secret,'origin':base}),))
        return {'ok':True,'callback':base+CALLBACK}
    @app.post('/api/feishu/preferences')
    async def prefs(request:Request):
        u=user(request);d=await body(request)
        if type(d.get('enabled')) is not bool:raise HTTPException(400,'自动上传设置无效')
        try:
            folder=folder_token(d.get('folder',''))
            await run_in_threadpool(lambda:service.list_folder(service.token(u['id']),folder))
        except ValueError as e:raise HTTPException(400,str(e)) from None
        with hub.db() as db:db.execute('INSERT OR REPLACE INTO feishu_prefs VALUES(?,?,?)',(u['id'],folder,int(d['enabled'])))
        return {'ok':True,'note':'文件夹读取权限已验证；实际写入权限将在首次上传时验证'}
    @app.get('/api/feishu/start')
    def start(request:Request,mode:str='login'):
        c=configured()
        if origin!=c['origin']:raise HTTPException(400,'请在团队 HTTPS 地址登录并绑定飞书')
        if mode not in ('login','bind'):raise HTTPException(400,'授权方式无效')
        owner=user(request)['id'] if mode=='bind' else None
        state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32)
        with hub.db() as db:
            db.execute('DELETE FROM feishu_states WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO feishu_states VALUES(?,?,?,?,?)',(digest(state),digest(nonce),owner,digest(request.cookies.get('hub_session','')) if owner else None,time.time()+600))
        url='https://accounts.feishu.cn/open-apis/authen/v1/authorize?'+urlencode({'client_id':c['app_id'],'response_type':'code','redirect_uri':c['origin']+CALLBACK,'scope':SCOPES,'state':state})
        r=RedirectResponse(url,302);r.set_cookie('hub_feishu_state',nonce,httponly=True,secure=True,samesite='lax',max_age=600,path='/api/feishu');return r
    @app.get(CALLBACK)
    def callback(request:Request,state:str='',code:str=''):
        c=configured()
        if origin!=c['origin']:raise HTTPException(400,'回调地址不匹配')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');s=db.execute('SELECT * FROM feishu_states WHERE state=?',(digest(state),)).fetchone()
            if not s or s['expires']<time.time() or not secrets.compare_digest(s['nonce'],digest(request.cookies.get('hub_feishu_state',''))):raise HTTPException(400,'授权已过期或浏览器不匹配，请重新发起')
            db.execute('DELETE FROM feishu_states WHERE state=?',(digest(state),))
            if s['owner'] and not db.execute('SELECT 1 FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.user_id=? AND s.expires>? AND u.enabled=1 AND u.must_change=0',(s['session'],s['owner'],time.time())).fetchone():raise HTTPException(403,'原账号登录已失效，请重新登录后绑定')
        if not code:raise HTTPException(400,'未完成飞书授权，请返回中台重试')
        try:
            tokens=service.call('authen/v2/oauth/token',method='POST',json={'grant_type':'authorization_code','client_id':c['app_id'],'client_secret':c['app_secret'],'code':code,'redirect_uri':c['origin']+CALLBACK})
            info=service.call('authen/v1/user_info',tokens['access_token'])
            subject=str(info.get('open_id',''))
            if not subject:raise ValueError('未获取到飞书身份')
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE');link=db.execute('SELECT owner FROM feishu_links WHERE subject=?',(subject,)).fetchone()
                owner=s['owner'] or (link['owner'] if link else None)
                if not owner:raise ValueError('该飞书账号尚未绑定，请先用原中台账号登录，再点击绑定飞书')
                if s['owner'] and not db.execute('SELECT 1 FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.user_id=? AND s.expires>? AND u.enabled=1 AND u.must_change=0',(s['session'],s['owner'],time.time())).fetchone():
                    raise ValueError('原账号登录已失效，请重新登录后绑定')
                u=db.execute('SELECT * FROM users WHERE id=? AND enabled=1',(owner,)).fetchone()
                if not u or u['must_change']:raise ValueError('原中台账号不可用或需要先修改初始密码')
                own=db.execute('SELECT subject FROM feishu_links WHERE owner=?',(owner,)).fetchone()
                if (link and link['owner']!=owner) or (own and own['subject']!=subject):raise ValueError('该账号已有其他绑定，不能覆盖')
                db.execute('INSERT OR REPLACE INTO feishu_links VALUES(?,?,?,?,?)',(owner,subject,str(info.get('name','飞书成员')),service.pack(tokens),time.time()+tokens.get('expires_in',3600)))
                db.execute('DELETE FROM feishu_refresh WHERE owner=?',(owner,))
                session=secrets.token_urlsafe(32);db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(session),owner,time.time()+8*3600))
                hub.log(db,owner,'feishu_bound' if s['owner'] else 'feishu_login',subject)
        except (ValueError,KeyError) as e:raise HTTPException(400,str(e) if isinstance(e,ValueError) else '飞书返回信息不完整，请重试') from None
        r=RedirectResponse('/?feishu=connected',303);r.set_cookie('hub_session',session,httponly=True,secure=True,samesite='lax',max_age=8*3600);r.delete_cookie('hub_feishu_state',path='/api/feishu');return r
    @app.get('/api/feishu/uploads')
    def uploads(request:Request):
        u=user(request)
        with hub.db() as db:return [dict(r) for r in db.execute('SELECT export_id,day,state,error,file_token,phase FROM feishu_uploads WHERE owner=? ORDER BY created DESC LIMIT 50',(u['id'],))]
    @app.post('/api/feishu/uploads/{eid}/retry')
    def retry(eid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            r=db.execute("SELECT f.* FROM feishu_uploads f JOIN edit_exports e ON e.id=f.export_id WHERE f.export_id=? AND f.owner=? AND e.state='ready'",(eid,u['id'])).fetchone()
            if not r:raise HTTPException(404,'成片不存在或尚未完成')
            if r['phase']=='finish_unknown':raise HTTPException(409,'上传完成结果未知，请先关联已上传文件；未重复提交')
            if r['state'] not in ('attention','failed'):raise HTTPException(409,'该任务无需重传')
            db.execute("UPDATE feishu_uploads SET state='waiting',error='' WHERE export_id=?",(eid,))
        return {'ok':True}

    @app.post('/api/feishu/uploads/{eid}/associate')
    async def associate(eid:str,request:Request):
        u=user(request);data=await body(request);fid=str(data.get('file_token',''))
        if data.get('confirm') is not True or not re.fullmatch(r'[A-Za-z0-9_-]{8,200}',fid):raise HTTPException(400,'请明确确认并填写文件 token')
        with hub.db() as db:
            row=db.execute("SELECT * FROM feishu_uploads WHERE export_id=? AND owner=? AND phase='finish_unknown' AND state='attention'",(eid,u['id'])).fetchone()
        if not row:raise HTTPException(409,'没有可核对的未知上传任务')
        try:await run_in_threadpool(service.verify_uploaded,dict(row),fid)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute("UPDATE feishu_uploads SET file_token=?,phase='confirmed',state='ready',error='',updated=? WHERE export_id=? AND owner=? AND phase='finish_unknown' AND state='attention'",(fid,time.time(),eid,u['id'])).rowcount
            if not changed:raise HTTPException(409,'任务状态已变化，请刷新')
            hub.log(db,u['id'],'feishu_upload_associated',eid)
        return {'ok':True,'note':'已核验目录、名称及完整内容 SHA256，关联原成片；未再次上传'}
