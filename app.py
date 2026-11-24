import contextlib
import hashlib
import hmac
import json
import os
import re
import shutil
from pathlib import Path
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from provider import TikTok, ProviderError, parse_curl, reference_payload
from exception_center import safe_error
import task_feedback as feedback

ROOT = Path(__file__).resolve().parent
MAX_INFLIGHT_PER_ACCOUNT = 10


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


def check_password(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)


class Hub:
    def __init__(self, directory, provider=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.media = self.directory / 'media'
        self.media.mkdir(exist_ok=True)
        keyfile = self.directory / 'vault.key'
        if not keyfile.exists():
            with keyfile.open('xb') as f:
                f.write(Fernet.generate_key())
            os.chmod(keyfile, 0o600)
        self.cipher = Fernet(keyfile.read_bytes())
        self.path = self.directory / 'hub.sqlite3'
        self.provider = provider or TikTok(os.getenv('HUB_PROXY', 'http://127.0.0.1:7890'))
        self.stop = threading.Event()
        self.failures = {}
        self.poll_failures = {}
        self.rate_lock = threading.Lock()
        self.upload_lock = threading.Lock()
        self.route_lock = threading.Lock()
        self.reference_enabled = (self.directory/'image-upload-verified.json').is_file() or bool(getattr(provider,'reference_enabled',False))
        with self.db() as db:
            # Whole-team concurrency: WAL keeps readers (task lists, polls) off the writer's lock.
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
              password TEXT NOT NULL, role TEXT NOT NULL, enabled INTEGER DEFAULT 1, daily_limit INTEGER DEFAULT 10,
              must_change INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT NOT NULL,scope TEXT NOT NULL,
              owner TEXT NOT NULL,secret BLOB NOT NULL,enabled INTEGER DEFAULT 1,status TEXT DEFAULT 'connected',
              daily_limit INTEGER DEFAULT 20,checked REAL,error TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,owner TEXT NOT NULL,account_id TEXT NOT NULL,
              prompt TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
              remote_id TEXT,draft_id TEXT,error TEXT DEFAULT '',metadata TEXT DEFAULT '{}',
              poll_at REAL DEFAULT 0,request_key TEXT NOT NULL,UNIQUE(owner,request_key));
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at REAL,actor TEXT,action TEXT,target TEXT);
            CREATE INDEX IF NOT EXISTS task_state ON tasks(account_id,state);
            ''')
            if 'identity' not in {r['name'] for r in db.execute('PRAGMA table_info(accounts)')}:
                db.execute('ALTER TABLE accounts ADD COLUMN identity TEXT')
            if 'submitted_at' not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
                db.execute('ALTER TABLE tasks ADD COLUMN submitted_at REAL')
                db.execute("UPDATE tasks SET submitted_at=updated WHERE state NOT IN ('queued','cancelled')")

        self.assets = self.directory / 'assets'
        self.assets.mkdir(exist_ok=True)
        with self.db() as db:
            cols = {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}
            for name, declaration in [('duration','INTEGER DEFAULT 5'),('config',"TEXT DEFAULT '{}'"),('batch_id','TEXT')]:
                if name not in cols: db.execute(f'ALTER TABLE tasks ADD COLUMN {name} {declaration}')
            db.executescript("""
            CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT,mime TEXT,size INTEGER,created REAL);
            CREATE TABLE IF NOT EXISTS compositions(owner TEXT PRIMARY KEY,content TEXT NOT NULL,updated REAL);
            CREATE TABLE IF NOT EXISTS task_requests(owner TEXT NOT NULL,request_key TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(owner,request_key));
            CREATE TABLE IF NOT EXISTS platform_images(asset_id TEXT NOT NULL,account_id TEXT NOT NULL,reference TEXT NOT NULL,PRIMARY KEY(asset_id,account_id));
            """)
            feedback.init_schema(db)

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def log(self, db, actor, action, target):
        db.execute('INSERT INTO audit(at,actor,action,target) VALUES(?,?,?,?)', (time.time(),actor,action,target))

    def headers(self, account):
        return json.loads(self.cipher.decrypt(account['secret']))

    def sync_subaccounts(self, account, actor):
        headers=self.headers(account);verified=[]
        for item in self.provider.account_info(headers,listing=True):
            identity=str(item.get('aioClientID',''))
            scoped=self.provider.scoped_account(headers,identity)
            info=self.provider.account_info(scoped)
            if str(info.get('aioClientID'))!=identity:raise ProviderError('子账号身份校验不一致，未保存')
            verified.append((identity,str(info.get('profileName') or identity),self.cipher.encrypt(json.dumps(scoped).encode())))
        with self.db() as db:
            for identity,name,secret in verified:
                row=db.execute('SELECT id FROM accounts WHERE identity=?',('aio:'+identity,)).fetchone()
                if row:
                    db.execute("UPDATE accounts SET secret=?,status='connected',error='',checked=? WHERE id=?",(secret,time.time(),row['id']))
                else:
                    db.execute('INSERT INTO accounts(id,name,scope,owner,secret,daily_limit,checked,identity) VALUES(?,?,?,?,?,?,?,?)',(secrets.token_hex(12),'子账号 '+name,'shared',account['owner'],secret,0,time.time(),'aio:'+identity))
            self.log(db,actor,'subaccounts_synced',str(len(verified)))
        return len(verified)

    def route_task(self, account, task, config):
        if not hasattr(self.provider,'quotas'):return account,config
        with self.db() as db:
            candidates=db.execute("SELECT * FROM accounts WHERE scope='shared' AND enabled=1 AND status='connected' ORDER BY checked,id").fetchall()
        if config.get('account_choice','pool')!='pool':candidates=[a for a in candidates if a['id']==account['id']]
        models=[config.get('model','auto')]
        if models==['auto']:
            models=['5000005','mini','fast'] if config.get('assets') and config.get('mode')!='frames' else ['5000005']
        quotas={}
        for model in models:
            for candidate in candidates:
                with self.db() as db:
                    active=db.execute("SELECT COUNT(*) FROM tasks WHERE account_id=? AND id<>? AND (state IN ('running','submitting') OR (state='attention' AND remote_id IS NOT NULL AND remote_id<>''))",(candidate['id'],task['id'])).fetchone()[0]
                if active>=MAX_INFLIGHT_PER_ACCOUNT:continue
                if candidate['id'] not in quotas:
                    with feedback.step('quota','blocked'):
                        quotas[candidate['id']]=self.provider.quotas(self.headers(candidate))
                key={'5000005':'5000005','mini':'2000009','fast':'2000012'}[model]
                quota=quotas[candidate['id']].get(key,{})
                if quota.get('matched') is not True or quota.get('allowed') is not True:continue
                try:remaining=0 if quota.get('unlimited') is True else int(quota.get('remaining',0))
                except (ValueError,TypeError):continue
                if quota.get('unlimited') is not True and remaining<=active:continue
                config=dict(config,model=model,requested_model=config.get('model','auto'))
                with self.db() as db:
                    db.execute('UPDATE tasks SET account_id=?,config=?,updated=? WHERE id=?',(candidate['id'],json.dumps(config,ensure_ascii=False),time.time(),task['id']))
                return candidate,config
        with feedback.step('quota','blocked'):
            raise ProviderError('当前账号池没有足够的已确认额度或并发位置；未提交生成，请稍后再试')

    def tick(self):
        # A bounded in-flight window is an execution resource, not a daily submission quota.
        jobs = []
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            accounts = db.execute("SELECT * FROM accounts WHERE enabled=1 AND scope='shared'").fetchall()
            for account in accounts:
                active = db.execute("SELECT * FROM tasks WHERE account_id=? AND state IN ('submitting','unknown','attention','running') ORDER BY created", (account['id'],)).fetchall()
                jobs.extend((account,t,True) for t in active if t['state'] in ('running','attention') and t['remote_id'] and t['poll_at']<=time.time() and account['status']=='connected')
                jobs.extend((account,t,'reconcile') for t in active if t['state']=='unknown' and t['poll_at']<=time.time() and account['status']=='connected')
                if account['status']!='connected':
                    continue
                # Unknown submissions are reconciled separately, never resubmitted.
                # Known in-flight tasks still occupy the normal concurrency window.
                in_flight=sum(1 for t in active if t['state'] in ('running','submitting') or (t['state']=='attention' and t['remote_id']))
                available = max(0, MAX_INFLIGHT_PER_ACCOUNT-in_flight)
                queued = db.execute("SELECT t.* FROM tasks t JOIN users u ON t.owner=u.id WHERE t.account_id=? AND t.state='queued' AND u.enabled=1 ORDER BY t.created,t.id LIMIT ?", (account['id'],available)).fetchall()
                for task in queued:
                    db.execute("UPDATE tasks SET state='submitting',updated=?,submitted_at=? WHERE id=? AND state='queued'",(time.time(),time.time(),task['id']))
                    jobs.append((account,task,False))
        if jobs:
            with ThreadPoolExecutor(max_workers=30) as executor:
                list(executor.map(lambda job:self.process_task(*job),jobs))

    def prepare_images(self, account, task, config):
        images=[]
        for asset in config.get('assets',[]):
            with self.upload_lock:
                with self.db() as db:
                    local=db.execute('SELECT * FROM assets WHERE id=? AND owner=?',(asset['id'],task['owner'])).fetchone()
                    cached=db.execute('SELECT reference FROM platform_images WHERE asset_id=? AND account_id=?',(asset['id'],account['id'])).fetchone()
                if not local:
                    raise ProviderError('图片已不可用，尚未提交视频生成')
                if cached:
                    reference=json.loads(cached['reference'])
                else:
                    if local['mime'].startswith('image/'):
                        reference=self.provider.upload_image(self.headers(account),(self.assets/local['id']).read_bytes(),local['name'])
                    else:
                        reference=self.provider.upload_media(self.headers(account),(self.assets/local['id']).read_bytes(),local['name'],local['mime'].split('/')[0])
                    with self.db() as db:
                        db.execute('INSERT INTO platform_images VALUES(?,?,?)',(asset['id'],account['id'],json.dumps(reference)))
                images.append(reference)
        return images

    def process_task(self, account, task, polling):
        with feedback.bound(self, 'tiktok', task['id']):
            if polling=='reconcile':
                self.reconcile_unknown(account,task)
            else:
                self._process_task(account,task,polling)

    def _process_task(self, account, task, polling):
        generation_attempted=False
        try:
            headers = self.headers(account)
            if not polling:
                config=json.loads(task['config'])
                with self.route_lock:
                    account,config=self.route_task(account,task,config)
                headers=self.headers(account)
                is_reference=bool(config.get('assets'))
                if is_reference:
                    with feedback.step('upload','blocked'):
                        if not self.reference_enabled:raise ProviderError('图片上传未验证，尚未提交视频生成')
                        images=self.prepare_images(account,task,config)
                        if config.get('mode')!='frames':
                            reference_payload(config.get('provider_prompt',task['prompt']),images,task['duration'],{'auto':'2000004','5000005':'2000004','mini':'2000009','fast':'2000012'}[config.get('model','auto')])
                with self.db() as db:
                    db.execute('UPDATE tasks SET submitted_at=? WHERE id=?',(time.time(),task['id']))
                generation_attempted=True
                with feedback.step('submit','unknown'):
                    if is_reference:
                        if config.get('mode')=='frames':
                            result=self.provider.create_frames(headers,task['prompt'],images,duration=task['duration'])
                        elif config.get('model')=='mini' and all(x.get('fileType','image')=='image' for x in images):
                            result=self.provider.create_mini_reference(headers,config.get('provider_prompt',task['prompt']),images,duration=task['duration'])
                        else:
                            result=self.provider.create_reference(headers,config.get('provider_prompt',task['prompt']),images,duration=task['duration'],model=config.get('model','auto'))
                    else:
                        result = self.provider.create(headers, task['prompt'], duration=task['duration'])
                    task_id = result.get('task_id')
                    if not task_id:
                        raise ProviderError('平台未返回任务 ID，请在网页核对；不会自动重提')
                with feedback.step('save_task','unknown'), self.db() as db:
                    db.execute("UPDATE tasks SET state='running',remote_id=?,draft_id=?,updated=?,poll_at=? WHERE id=?",(str(task_id),str((result.get('draft_infos') or [{}])[0].get('id','')),time.time(),time.time()+10,task['id']))
                return
            state,error,metadata = 'running','','{}'
            with feedback.step('poll') as attempt:
                draft = (self.provider.find(headers, task['remote_id'], task['draft_id'])
                         if isinstance(self.provider, TikTok) else self.provider.find(headers, task['remote_id']))
                if not draft:
                    attempt.mark('waiting')
                elif str(draft.get('generateErrorCode') or '0') != '0' or 3 in (draft.get('draftTaskStatus'),draft.get('renderTaskStatus')):
                    attempt.code(draft.get('generateErrorCode'))
                    attempt.mark('failed')
                    state,error = 'failed',str(draft.get('generateErrorMessage') or ('平台确认生成失败，错误码 '+str(draft.get('generateErrorCode') or '未提供')))[:1500]
            if draft and state!='failed':
                original = (draft.get('videoInfo') or {}).get('OriginalVideoInfo') or {}
                if original.get('MainUrl') and (draft.get('hasContent') or (task['draft_id'] and str(draft.get('id')) == str(task['draft_id']) and float((draft.get('videoInfo') or {}).get('Duration') or 0) > 0)):
                    with feedback.step('video_download'):
                        self.provider.download(original['MainUrl'],self.media/(task['id']+'.mp4'),headers.get('user-agent','Mozilla/5.0'))
                    state,metadata = 'ready',json.dumps(original.get('VideoMeta') or {})
            if state=='running' and time.time()-(task['submitted_at'] or task['updated'])>7200:
                state,error = 'running','平台仍未返回最终结果；中台持续查询原任务，不会重新生成'
            with feedback.step('save_task'), self.db() as db:
                db.execute('UPDATE tasks SET state=?,error=?,metadata=?,updated=?,poll_at=? WHERE id=?',(state,error,metadata,time.time(),time.time()+(300 if state=='attention' else 15),task['id']))
            self.poll_failures.pop(task['id'],None)
            if state=='ready':
                from workspace import append_completed
                try:append_completed(self,task['id'])
                except Exception:pass  # A project append failure must not invalidate the generated video.
        except Exception as exc:
            error = str(exc)[:1500] if isinstance(exc,ProviderError) else '执行异常，请检查本机连接；没有自动重提'
            delay=60
            if polling:
                failures=self.poll_failures.get(task['id'],0)+1
                self.poll_failures[task['id']]=failures
                delay=min(300,60*2**min(failures-1,3))
                error=f'查询已有任务失败；{delay} 秒后自动重查，不会重新生成。'+error
            with self.db() as db:
                db.execute('UPDATE tasks SET state=?,error=?,updated=?,poll_at=? WHERE id=?',('attention' if polling else 'unknown' if generation_attempted else 'failed',error,time.time(),time.time()+delay,task['id']))
                if isinstance(exc,ProviderError) and exc.auth:
                    db.execute("UPDATE accounts SET status='reauth',error=? WHERE id=?",('登录失效，请重新连接',account['id']))

    def reconcile_unknown(self,account,task):
        # History reads only. Never retry a generation request with an unknown result.
        message='平台记录尚未能唯一匹配；5 分钟后再核对，不会自动重提该任务'
        try:
            expected=json.loads(task['config']).get('provider_prompt',task['prompt'])
            stamp=task['submitted_at'] or task['updated']
            with feedback.step('history'):
                data=self.provider.history(self.headers(account))
            matches=[]
            for draft in data.get('draft_infos',[]):
                settings=draft.get('settings') or {}
                if isinstance(settings,str):settings=json.loads(settings)
                if (str(draft.get('taskId','')).isdigit() and settings.get('prompt')==expected
                    and abs(float(draft.get('createdAt',0))-stamp)<600
                    and float(settings.get('duration',draft.get('duration',0)))==task['duration']):
                    matches.append(draft)
            if len(matches)==1:
                draft=matches[0];remote=str(draft['taskId'])
                with self.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    used=db.execute('SELECT 1 FROM tasks WHERE remote_id=?',(remote,)).fetchone()
                    peers=db.execute("SELECT * FROM tasks WHERE account_id=? AND id<>? AND submitted_at BETWEEN ? AND ?",(account['id'],task['id'],stamp-1200,stamp+1200)).fetchall()
                    ambiguous=any(json.loads(p['config']).get('provider_prompt',p['prompt'])==expected for p in peers)
                    if not used and not ambiguous:
                        changed=db.execute("UPDATE tasks SET state='running',remote_id=?,draft_id=?,error='',poll_at=0,updated=? WHERE id=? AND state='unknown'",(remote,str(draft.get('id','')),time.time(),task['id'])).rowcount
                        if changed:self.log(db,task['owner'],'task_auto_reconcile',task['id'])
                        return
                    message='存在相同文案的批次或已关联的平台记录，无法安全自动匹配；请核对网页任务 ID，不会自动重提'
        except Exception as exc:
            message='核对平台记录失败；5 分钟后重查，不会重新生成'
            if isinstance(exc,ProviderError) and exc.auth:
                with self.db() as db:db.execute("UPDATE accounts SET status='reauth',error='登录失效，请重新连接' WHERE id=?",(account['id'],))
        with self.db() as db:
            db.execute("UPDATE tasks SET error=?,poll_at=?,updated=? WHERE id=? AND state='unknown'",(message,time.time()+300,time.time(),task['id']))

    def worker(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                # Avoid outputting potentially sensitive upstream exceptions.
                pass
            self.stop.wait(5)


def create_app(directory=None, provider=None, worker=True):
    hub = Hub(directory or os.getenv('HUB_STATE', str(ROOT/'state')), provider)
    origin = os.getenv('HUB_ORIGIN','http://127.0.0.1:8765').rstrip('/')
    secure = origin.startswith('https://')
    if not secure and urlsplit(origin).hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('LAN deployment requires an HTTPS HUB_ORIGIN; use TLS reverse proxy')
    @contextlib.asynccontextmanager
    async def lifespan(app):
        thread = None
        edit_thread = None
        ai_edit_thread = None
        voice_thread = None
        classification_thread = None
        kalodata_thread = None
        own_goods_thread = None
        own_goods_cover_thread = None
        apify_thread = None
        enrichment_thread = None
        script_thread = None
        case_thread = None
        case_data_thread = None
        comment_threads = []
        feishu_thread = None
        lock = None
        libtv_thread = None
        try:
            if worker:
                lock = (hub.directory/'worker.lock').open('a+b')
                try:
                    if os.name == 'nt':
                        import msvcrt
                        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
                        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except OSError:
                    lock.close()
                    lock = None
                    raise RuntimeError('Run exactly one hub process') from None
                with hub.db() as db:
                    db.execute("UPDATE tasks SET state='unknown',error='进程重启时提交结果不明确，请核对网页',updated=? WHERE state='submitting'",(time.time(),))
                thread = threading.Thread(target=hub.worker, daemon=True)
                thread.start()
                from asset_classification import loop as classification_loop
                classification_thread=threading.Thread(target=classification_loop,args=(hub,),daemon=True)
                classification_thread.start()
                app.state.editor.recover()
                edit_thread=threading.Thread(target=app.state.editor.loop,daemon=True)
                edit_thread.start()
                app.state.ai_editing.recover()
                ai_edit_thread=threading.Thread(target=app.state.ai_editing.loop,daemon=True)
                ai_edit_thread.start()
                app.state.apify_monitor.recover()
                app.state.script_automation.recover()
                app.state.video_cases.recover()
                case_data_thread=threading.Thread(target=app.state.video_cases.data_loop,name='case-data-lane',daemon=True)
                case_data_thread.start()
                case_thread=threading.Thread(target=app.state.video_cases.loop,daemon=True)
                case_thread.start()
                app.state.comment_samples.recover()
                for lane in ('collect','ai'):
                    t=threading.Thread(target=app.state.comment_samples.loop,args=(lane,),name='comment-samples-'+lane,daemon=True)
                    t.start();comment_threads.append(t)
                script_thread=threading.Thread(target=app.state.script_automation.loop,daemon=True)
                script_thread.start()
                apify_thread=threading.Thread(target=app.state.apify_monitor.loop,daemon=True)
                apify_thread.start()
                enrichment_thread=threading.Thread(target=app.state.video_enrichment.loop,daemon=True)
                enrichment_thread.start()
                app.state.kalodata.recover()
                kalodata_thread=threading.Thread(target=app.state.kalodata.loop,daemon=True)
                kalodata_thread.start()
                app.state.own_goods_lookup.recover()
                own_goods_thread=threading.Thread(target=app.state.own_goods_lookup.loop,name='own-goods-lookup',daemon=True)
                own_goods_thread.start()
                app.state.own_goods_covers.recover()
                own_goods_cover_thread=threading.Thread(target=app.state.own_goods_covers.loop,name='own-goods-cover',daemon=True)
                own_goods_cover_thread.start()
                app.state.feishu.recover()
                feishu_thread=threading.Thread(target=app.state.feishu.loop,daemon=True)
                feishu_thread.start()
                libtv_thread=threading.Thread(target=app.state.libtv_auto,daemon=True)
                libtv_thread.start()
                if os.getenv('HUB_VOICE_WORKER','1')=='1':
                    hub.voice.recover()
                    voice_thread=threading.Thread(target=hub.voice.loop,daemon=True)
                    voice_thread.start()
            yield
        finally:
            from worker_lifecycle import drain_workers
            threads=[t for t in (thread,edit_thread,ai_edit_thread,voice_thread,classification_thread,
                     feishu_thread,script_thread,case_thread,case_data_thread,apify_thread,
                     enrichment_thread,kalodata_thread,own_goods_thread,own_goods_cover_thread,libtv_thread) if t is not None]
            app.state.worker_drain=drain_workers(hub.stop,threads+comment_threads,lock)

    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.hub = hub

    @app.middleware('http')
    async def protect(request, call_next):
        if request.headers.get('host') != urlsplit(origin).netloc:
            return JSONResponse({'detail':'请使用配置的工作台地址访问'},status_code=400)
        if request.method not in ('GET','HEAD'):
            if request.headers.get('x-hub-request') != '1' or request.headers.get('origin') not in (None,origin):
                return JSONResponse({'detail':'请求来源校验失败'},status_code=403)
            if request.url.path not in ('/api/editor/footage','/api/mobile/upload','/api/assets'):
                try:
                    maximum=64*1024*1024 if request.url.path=='/api/assets' else 2*1024*1024
                    chunks=[]; received=0
                    async for chunk in request.stream():
                        received+=len(chunk)
                        if received>maximum:
                            return JSONResponse({'detail':'请求内容过大'},status_code=413)
                        chunks.append(chunk)
                    request._body=b''.join(chunks)
                except Exception:
                    return JSONResponse({'detail':'无法读取请求'},status_code=400)
        response = await call_next(request)
        # Static files may revalidate with ETag/Last-Modified; private APIs never cache.
        response.headers['Cache-Control'] = ('private, no-cache' if request.url.path.startswith('/static/') and request.method in ('GET','HEAD') and response.status_code in (200,304) else 'no-store')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data: blob: https://p16-oec-sg.ibyteimg.com https://p16-oec-ttp.tiktokcdn-us.com; media-src 'self' blob: https://fish.audio https://*.fish.audio; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    async def body(request):
        try:
            data = await request.json()
            if not isinstance(data,dict): raise ValueError()
            return data
        except Exception:
            raise HTTPException(400,'请求格式有误') from None

    def user(request, admin=False, allow_change=False):
        token = hashlib.sha256(request.cookies.get('hub_session','').encode()).hexdigest()
        with hub.db() as db:
            found = db.execute('SELECT u.* FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token=? AND s.expires>? AND u.enabled=1',(token,time.time())).fetchone()
        if not found: raise HTTPException(401,'请先登录')
        if admin and found['role']!='admin': raise HTTPException(403,'需要管理员权限')
        if found['must_change'] and not allow_change: raise HTTPException(403,'请先修改初始密码')
        return found

    def safe_user(u):
        return {k:u[k] for k in ('id','username','role','enabled','must_change')}

    def task_access(db, task_id, u):
        task = db.execute('SELECT t.*,a.scope FROM tasks t JOIN accounts a ON a.id=t.account_id WHERE t.id=?',(task_id,)).fetchone()
        if not task or (task['owner']!=u['id'] and not (u['role']=='admin' and task['scope']=='shared')): raise HTTPException(404,'任务不存在')
        return task

    @app.get('/api/status')
    def status():
        with hub.db() as db:
            setup = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
        return {'needs_setup':setup,'local_only':not secure,'model':'Dreamina Seedance 2.0','duration':5}

    @app.post('/api/setup')
    async def setup(request: Request):
        if request.client.host not in ('127.0.0.1','::1','testclient'): raise HTTPException(403,'首次设置仅允许本机访问')
        data = await body(request)
        name, password = str(data.get('username','')).strip(), str(data.get('password',''))
        if not 2<=len(name)<=40 or not 12<=len(password)<=200: raise HTTPException(400,'用户名需 2–40 字，密码需 12–200 字符')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]: raise HTTPException(409,'已经完成首次设置')
            db.execute('INSERT INTO users(id,username,password,role,daily_limit) VALUES(?,?,?,?,?)',(secrets.token_hex(12),name,password_hash(password),'admin',20))
        return {'ok':True}

    @app.post('/api/login')
    async def login(request: Request):
        data = await body(request)
        name = str(data.get('username',''))[:40]
        rate_key = request.client.host
        with hub.rate_lock:
            attempts = [t for t in hub.failures.get(rate_key,[]) if t>time.time()-300]
            if len(attempts)>=10: raise HTTPException(429,'尝试过于频繁，请五分钟后再试')
            hub.failures[rate_key] = attempts+[time.time()]
        with hub.db() as db:
            found = db.execute('SELECT * FROM users WHERE username=? AND enabled=1',(name,)).fetchone()
            password = str(data.get('password',''))
            if len(password)>200 or not found or not check_password(password,found['password']): raise HTTPException(401,'用户名或密码不正确')
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),found['id'],time.time()+8*3600))
        with hub.rate_lock:
            hub.failures.pop(rate_key,None)
        response = JSONResponse(safe_user(found))
        response.set_cookie('hub_session',token,httponly=True,secure=secure,samesite='strict',max_age=8*3600)
        return response

    @app.get('/api/me')
    def me(request: Request): return safe_user(user(request,allow_change=True))

    @app.get('/api/storage-status')
    def storage_status(request: Request):
        user(request)
        try:
            location = hub.media.resolve(strict=True)
            usage = shutil.disk_usage(location)
        except OSError:
            raise HTTPException(503, '无法读取视频存储空间，请检查存储磁盘是否可用') from None
        warning = 20 * 1024**3
        critical = 5 * 1024**3
        return {'drive': location.anchor or '存储磁盘', 'free': usage.free, 'total': usage.total,
                'level': 'critical' if usage.free < critical else 'warning' if usage.free < warning else 'normal',
                'warning_bytes': warning, 'critical_bytes': critical}

    @app.get('/api/admin/storage-report')
    def admin_storage_report(request: Request):
        user(request, admin=True)
        from storage_report import report
        return report(hub)

    @app.post('/api/logout')
    def logout(request: Request):
        with hub.db() as db:
            db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(request.cookies.get('hub_session','').encode()).hexdigest(),))
        response = JSONResponse({'ok':True}); response.delete_cookie('hub_session'); return response

    @app.post('/api/password')
    async def password(request: Request):
        u = user(request,allow_change=True); data = await body(request)
        old, new = str(data.get('old','')), str(data.get('new',''))
        if len(old)>200 or not check_password(old,u['password']): raise HTTPException(400,'当前密码不正确')
        if not 12<=len(new)<=200: raise HTTPException(400,'新密码至少 12 字符')
        with hub.db() as db:
            db.execute('UPDATE users SET password=?,must_change=0 WHERE id=?',(password_hash(new),u['id']))
            current = hashlib.sha256(request.cookies.get('hub_session','').encode()).hexdigest()
            db.execute('DELETE FROM sessions WHERE user_id=? AND token<>?',(u['id'],current))
        return {'ok':True}

    @app.get('/api/accounts')
    def accounts(request: Request):
        u = user(request)
        with hub.db() as db:
            rows = db.execute("SELECT * FROM accounts WHERE scope='shared'").fetchall()
        return [{**{k:r[k] for k in ('id','name','scope','enabled','status','checked','error')},
                 'can_manage':r['owner']==u['id'] or (r['scope']=='shared' and u['role']=='admin')} for r in rows]

    @app.post('/api/accounts')
    async def connect(request: Request):
        u = user(request,True); data = await body(request)
        scope = data.get('scope','shared'); name = str(data.get('name','')).strip()
        if scope != 'shared' or not 1<=len(name)<=60: raise HTTPException(400,'请填写账号名称和类型')
        if scope=='shared' and u['role']!='admin': raise HTTPException(403,'只有管理员可以连接公司账号')
        account_id = data.get('id')
        with hub.db() as db:
            if account_id:
                old = db.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
                if not old or not (old['owner']==u['id'] or old['scope']=='shared' and u['role']=='admin'): raise HTTPException(403,'不能更改该账号')
                if scope != old['scope']: raise HTTPException(400,'更新连接不能改变账号类型')
        try:
            headers = parse_curl(str(data.get('curl','')))
        except (ValueError,IndexError,TypeError):
            raise HTTPException(400,'请选择完整的 generating-task-count 或 create_generate_task 请求，使用 Copy as cURL (bash)，不要删去登录字段') from None
        # Run blocking provider check outside the event loop.
        import asyncio
        try:
            history = await asyncio.to_thread(hub.provider.history,headers)
        except ProviderError as e:
            raise HTTPException(400,str(e)) from None
        limit = 0  # Legacy column retained for database compatibility; no submission cap.
        secret = hub.cipher.encrypt(json.dumps(headers).encode())
        identities = {str(d.get('AIOId')) for d in history.get('draft_infos',[]) if d.get('AIOId')}
        identity = 'aio:'+next(iter(identities)) if len(identities)==1 else 'session:'+hashlib.sha256(headers['cookie'].encode()).hexdigest()
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            duplicate = db.execute('SELECT id,name FROM accounts WHERE identity=? AND id<>?',(identity,account_id or '')).fetchone()
            if duplicate: raise HTTPException(409,'该 TikTok 账号已有连接「'+duplicate['name']+'」，请在该账号旁点击“更新连接”，不要新建或更新其他账号')
            if account_id:
                existing = db.execute('SELECT identity FROM accounts WHERE id=?',(account_id,)).fetchone()
                active = db.execute("SELECT 1 FROM tasks WHERE account_id=? AND state IN ('queued','submitting','running','unknown','attention')",(account_id,)).fetchone()
                if existing['identity'] and existing['identity']!=identity and active:
                    raise HTTPException(409,'该连接还有未完成任务，不能换成另一个 TikTok 账号')
            if account_id:
                db.execute("UPDATE accounts SET name=?,secret=?,daily_limit=?,status='connected',error='',checked=?,identity=? WHERE id=?",(name,secret,limit,time.time(),identity,account_id))
            else:
                account_id = secrets.token_hex(12)
                db.execute('INSERT INTO accounts(id,name,scope,owner,secret,daily_limit,checked,identity) VALUES(?,?,?,?,?,?,?,?)',(account_id,name,scope,u['id'],secret,limit,time.time(),identity))
            hub.log(db,u['id'],'account_connected',account_id)
        return {'id':account_id}

    from tiktok_login import attach_tiktok_login
    attach_tiktok_login(app,hub,user)

    @app.post('/api/accounts/sync-login')
    async def sync_login(request: Request):
        u=user(request,True);data=await body(request)
        import shlex, asyncio
        supplied=data.get('headers')
        if not isinstance(supplied,dict):supplied={}
        allowed={'cookie','x-csrftoken','x-fp-id','user-agent','referer','origin','accept','accept-language','agw-js-conv','x-creative-source'}
        parts=['curl',shlex.quote('https://ads.tiktok.com/creative_bff_i18n/api/cue/generating-task-count')]
        for k,v in supplied.items():
            if k.lower() in allowed and isinstance(v,str):parts.extend(['-H',shlex.quote(k.lower()+': '+v)])
        try:
            headers=parse_curl(data['curl'] if isinstance(data.get('curl'),str) else ' '.join(parts))
            account={'secret':hub.cipher.encrypt(json.dumps(headers).encode()),'owner':u['id']}
            count=await asyncio.to_thread(hub.sync_subaccounts,account,u['id'])
            if not count:raise ProviderError('本次登录未返回可用子账号，未修改原连接')
        except (ProviderError,ValueError) as exc:raise HTTPException(400,str(exc)) from None
        return {'count':count}

    @app.post('/api/accounts/{account_id}/sync-subaccounts')
    async def sync_subaccounts(account_id: str, request: Request):
        u=user(request,True)
        with hub.db() as db:account=db.execute("SELECT * FROM accounts WHERE id=? AND scope='shared'",(account_id,)).fetchone()
        if not account:raise HTTPException(404,'连接不存在')
        import asyncio
        try:count=await asyncio.to_thread(hub.sync_subaccounts,account,u['id'])
        except ProviderError as e:
            if e.auth:
                with hub.db() as db:db.execute("UPDATE accounts SET status='reauth',error=?,checked=? WHERE id=?",(str(e),time.time(),account_id))
            raise HTTPException(400,str(e)) from None
        return {'count':count}

    @app.post('/api/accounts/{account_id}/toggle')
    async def toggle(account_id: str, request: Request):
        u=user(request)
        with hub.db() as db:
            a=db.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
            if not a or not (a['owner']==u['id'] or a['scope']=='shared' and u['role']=='admin'): raise HTTPException(404,'账号不存在')
            db.execute('UPDATE accounts SET enabled=1-enabled WHERE id=?',(account_id,))
            hub.log(db,u['id'],'account_toggle',account_id)
        return {'ok':True}

    @app.get('/api/studio/events')
    async def studio_events(request: Request):
        import asyncio
        from fastapi.responses import StreamingResponse
        uid=user(request)['id']
        async def changes():
            previous=None
            while not hub.stop.is_set() and not await request.is_disconnected():
                try:
                    if user(request)['id'] != uid: return
                except HTTPException:
                    return
                with hub.db() as db:
                    version=tuple(tuple(db.execute(
                        f'SELECT COUNT(*),MAX(updated) FROM {table} WHERE owner=?',(uid,)
                    ).fetchone()) for table in ('tasks','libtv_jobs'))
                if version != previous:
                    yield 'data: changed\n\n'
                    previous=version
                await asyncio.sleep(2)
        return StreamingResponse(changes(),media_type='text/event-stream',
                                 headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})

    @app.get('/api/tasks')
    def tasks(request: Request, offset: int=0, compact: bool=False):
        u=user(request)
        if offset<0 or offset>1000000: raise HTTPException(400,'分页位置无效')
        return task_rows(u,offset,compact)

    @app.post('/api/tasks/reconcile-loaded')
    async def reconcile_loaded(request: Request):
        u=user(request);data=await body(request);ids=data.get('ids')
        if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) or not i or len(i)>128 for i in ids):raise HTTPException(400,'任务列表无效')
        ids=list(dict.fromkeys(ids));versions=data.get('versions')
        if versions is not None and (not isinstance(versions,dict) or len(versions)>100 or any(not isinstance(k,str) or k not in ids or not isinstance(v,str) or not re.fullmatch(r'[0-9a-f]{64}',v) for k,v in versions.items())):raise HTTPException(400,'任务版本无效')
        rows=task_rows(u,0,True,ids)
        if versions is None:return {'items':rows,'requested':ids}
        current={row['id']:hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest() for row in rows}
        return {'items':[row for row in rows if versions.get(row['id'])!=current[row['id']]],'versions':current,'missing':[i for i in ids if i not in current]}

    def task_rows(u,offset,compact,ids=None):
        if ids is not None and not ids:return []
        selection=(' AND t.id IN ('+','.join('?' for _ in ids)+')') if ids is not None else ''
        limit='' if ids is not None else ' LIMIT 100 OFFSET ?'
        params=(int(u['role']=='admin'),u['id'],*(ids if ids is not None else (offset,)))
        with hub.db() as db:
            rows=db.execute("SELECT t.id,t.prompt,t.state,t.created,t.updated,t.remote_id,t.error,t.account_id,t.metadata,t.duration,t.config,t.batch_id,a.name account_name,a.scope account_scope,u.username owner_name,cr.error append_error,cr.state append_state FROM tasks t JOIN accounts a ON t.account_id=a.id JOIN users u ON t.owner=u.id LEFT JOIN continuation_results cr ON cr.task_id=t.id WHERE ((?=1 AND a.scope='shared') OR t.owner=?)"+selection+" ORDER BY t.created DESC,t.id DESC"+limit,params).fetchall()
            reasons={};positions={};account_reasons={}
            queued_accounts={r['account_id'] for r in rows if r['state']=='queued'}
            for account_id in queued_accounts:
                queued=db.execute("SELECT t.id FROM tasks t JOIN users u ON t.owner=u.id WHERE t.account_id=? AND t.state='queued' AND u.enabled=1 ORDER BY t.created,t.id",(account_id,)).fetchall()
                positions.update({item['id']:index for index,item in enumerate(queued,1)})
                a=db.execute('SELECT enabled,status FROM accounts WHERE id=?',(account_id,)).fetchone()
                active=db.execute("SELECT state,remote_id FROM tasks WHERE account_id=? AND state IN ('attention','submitting','running')",(account_id,)).fetchall()
                in_flight=sum(1 for x in active if x['state'] in ('running','submitting') or (x['state']=='attention' and x['remote_id']))
                account_reasons[account_id]=('账号已停用' if not a['enabled'] else '账号需要重新连接' if a['status']!='connected' else '该账号生成并发已满，等待空位' if in_flight>=MAX_INFLIGHT_PER_ACCOUNT else '等待后台调度提交')
            for r in rows:
                if r['state']=='queued':reasons[r['id']]=account_reasons[r['account_id']]
            diagnostics=feedback.latest_failures(db,[('tiktok',r['id']) for r in rows if r['state'] in ('failed','unknown','attention')])
        result=[dict({k:r[k] for k in ('id','prompt','state','created','updated','remote_id','error','account_name','account_scope','owner_name','metadata','duration','config','batch_id','append_error','append_state')},queue_reason=reasons.get(r['id'],''),queue_position=positions.get(r['id'])) for r in rows]
        for item in result:
            if item['state'] in ('failed','unknown','attention'):
                item['feedback']=diagnostics.get(('tiktok',item['id']))
                item['feedback_state']=feedback.outcome(item['state'],item['error'],item['feedback'])
            if item['error']:
                item['error']=safe_error(item['error'])
        if compact:
            for item in result:
                try:
                    config=json.loads(item['config'] or '{}')
                    if not isinstance(config,dict):continue
                except (ValueError,TypeError):
                    continue
                item['config']=json.dumps({k:v for k,v in config.items() if k not in ('prompt','provider_prompt')},ensure_ascii=False)
        return result

    @app.get('/api/studio/task-feedback/{channel}/{task_id}')
    def studio_feedback(channel: str, task_id: str, request: Request):
        u=user(request)
        feedback.valid_task(task_id)
        with hub.db() as db:
            if channel=='tiktok':
                task_access(db,task_id,u)
            elif channel=='libtv':
                if not db.execute('SELECT 1 FROM libtv_jobs WHERE id=? AND owner=?',(task_id,u['id'])).fetchone():
                    raise HTTPException(404,'任务不存在')
            else:
                raise HTTPException(404,'任务不存在')
            return {'items':feedback.timeline(db,channel,task_id)}

    @app.get('/api/tasks/{task_id}/config')
    def task_config(task_id: str, request: Request):
        u=user(request)
        with hub.db() as db:
            row=db.execute("SELECT t.config FROM tasks t JOIN accounts a ON t.account_id=a.id WHERE t.id=? AND ((?=1 AND a.scope='shared') OR t.owner=?)",(task_id,int(u['role']=='admin'),u['id'])).fetchone()
        if not row:raise HTTPException(404,'任务不存在')
        return {'config':row['config']}

    @app.get('/api/capabilities')
    def capabilities(request: Request):
        user(request)
        return {'models':[{'id':'5000005','name':'Seedance 2.0','connected':True},{'id':'mini','name':'Seedance 2.0 Mini','connected':hub.reference_enabled},{'id':'fast','name':'Seedance 2.0 Fast','connected':hub.reference_enabled}],
                'references':hub.reference_enabled,'reference_models':['auto','5000005','mini','fast'] if hub.reference_enabled else [],'frames':True,'media_references':True,'subaccount_switch':True,'quota_fallback':True,'duration_min':4,'duration_max':15,'max_batch':10,'inflight_per_account':MAX_INFLIGHT_PER_ACCOUNT}

    def validate_compositions(db, owner, items):
        if not isinstance(items,list) or not items or len(items)>100: raise HTTPException(400,'每次保存 1–100 组创作')
        for item in items:
            if not isinstance(item,dict): raise HTTPException(400,'创作内容格式有误')
            if not isinstance(item.get('prompt',''),str): raise HTTPException(400,'提示词格式有误')
            if type(item.get('duration',5)) is not int or not 4<=item.get('duration',5)<=15: raise HTTPException(400,'时长需为 4–15 秒')
            if type(item.get('count',1)) is not int or not 1<=item.get('count',1)<=10: raise HTTPException(400,'每组生成 1–10 条')
            if item.get('mode','omni') not in ('omni','frames'): raise HTTPException(400,'生成模式有误')
            if item.get('model','auto') not in ('auto','5000005','mini','fast'): raise HTTPException(400,'模型有误')
            assets=item.get('assets',[])
            if not isinstance(assets,list) or len(assets)>12: raise HTTPException(400,'素材数量有误')
            image_count=0; seen=set()
            for asset in assets:
                if not isinstance(asset,dict) or not isinstance(asset.get('id'),str) or asset['id'] in seen: raise HTTPException(400,'素材引用有误')
                seen.add(asset['id'])
                stored=db.execute('SELECT * FROM assets WHERE id=? AND owner=?',(asset['id'],owner)).fetchone()
                if not stored: raise HTTPException(400,'素材不存在或无权引用，请重新选择')
                if stored['mime'].startswith('image/'): image_count+=1
                if asset.get('role','reference') not in ('reference','first','last'): raise HTTPException(400,'素材用途有误')
            if image_count>9: raise HTTPException(400,'平台参考图片最多 9 张')

    @app.get('/api/compositions')
    def get_compositions(request: Request):
        u=user(request)
        with hub.db() as db: row=db.execute('SELECT content FROM compositions WHERE owner=?',(u['id'],)).fetchone()
        return {'items':json.loads(row['content']) if row else []}

    @app.post('/api/compositions')
    async def save_compositions(request: Request):
        u=user(request); data=await body(request); items=data.get('items')
        with hub.db() as db:
            validate_compositions(db,u['id'],items)
            db.execute('INSERT INTO compositions VALUES(?,?,?) ON CONFLICT(owner) DO UPDATE SET content=excluded.content,updated=excluded.updated',(u['id'],json.dumps(items,ensure_ascii=False),time.time()))
        return {'ok':True}

    @app.post('/api/assets')
    async def upload_asset(request: Request):
        u=user(request); mime=request.headers.get('content-type','').split(';')[0]
        from fastapi.concurrency import run_in_threadpool
        import anyio
        asset_id=secrets.token_hex(16); target=hub.assets/asset_id
        received=0;content=b'';created=False;committed=False
        from urllib.parse import unquote
        name=Path(unquote(request.headers.get('x-file-name','material')).replace('\\','/')).name[:160]
        async def validate_and_record():
            valid=(mime=='image/png' and content.startswith(b'\x89PNG\r\n\x1a\n') or
                   mime=='image/jpeg' and content.startswith(b'\xff\xd8\xff') or
                   mime=='image/webp' and content[:4]==b'RIFF' and content[8:12]==b'WEBP' or
                   mime=='video/mp4' and b'ftyp' in content[:32] or
                   mime in ('audio/wav','audio/x-wav') and content[:4]==b'RIFF' and content[8:12]==b'WAVE' or
                   mime=='audio/mpeg' and (content.startswith(b'ID3') or content[:2] in (b'\xff\xfb',b'\xff\xf3',b'\xff\xf2')) or
                   mime in ('audio/mp4','audio/x-m4a','audio/m4a') and b'ftyp' in content[:32] or
                   mime=='audio/aac' and content[:2] in (b'\xff\xf1',b'\xff\xf9') or
                   mime in ('audio/ogg','audio/oga') and content[:4]==b'OggS' or
                   mime=='audio/flac' and content[:4]==b'fLaC')
            if not valid:raise HTTPException(400,'请选择 PNG、JPG、WebP、MP4 图片或视频，或 MP3、WAV、M4A、AAC、OGG、FLAC 音频')
            if mime.startswith('image/'):
                from image_validation import validate_file
                try:await run_in_threadpool(validate_file,target,mime)
                except ValueError as exc:raise HTTPException(400,str(exc)) from None
            with hub.db() as db:db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(asset_id,u['id'],name,mime,received,time.time()))
        try:
            with anyio.CancelScope(shield=True):
                handle=await run_in_threadpool(target.open,'xb');created=True
            try:
                async for chunk in request.stream():
                    received+=len(chunk)
                    if received>64*1024*1024:raise HTTPException(413,'请求内容过大')
                    if len(content)<32:content=(content+chunk[:32-len(content)])
                    if chunk:await run_in_threadpool(handle.write,chunk)
            finally:
                with anyio.CancelScope(shield=True):await run_in_threadpool(handle.close)
            await validate_and_record()
            committed=True
        finally:
            if created and not committed:
                with anyio.CancelScope(shield=True):await run_in_threadpool(lambda:target.unlink(missing_ok=True))
        from asset_classification import record
        with hub.db() as db: classification=record(db,asset_id,mime)
        from asset_classification import enqueue
        state=enqueue(hub,asset_id,u['id'])
        classification['classification_status']=state['status']
        return {'id':asset_id,'name':name,'mime':mime,'size':received,'role':'reference',**classification}

    @app.get('/api/assets/{asset_id}')
    def get_asset(asset_id: str,request: Request):
        u=user(request)
        with hub.db() as db: row=db.execute('SELECT * FROM assets WHERE id=? AND owner=?',(asset_id,u['id'])).fetchone()
        if not row: raise HTTPException(404,'素材不存在')
        path=hub.assets/row['id']
        if not path.is_file():raise HTTPException(404,'素材文件不存在')
        if request.query_params.get('download')=='1':
            import re
            name=re.sub(r'[\\/\x00-\x1f\x7f]','_',row['name'] or 'material').strip()[:200] or 'material'
            import mimetypes
            if not Path(name).suffix:name+=mimetypes.guess_extension(row['mime']) or ''
            return FileResponse(path,media_type=row['mime'],filename=name)
        return FileResponse(path,media_type=row['mime'])

    @app.post('/api/tasks')
    async def enqueue(request: Request):
        u=user(request); data=await body(request)
        key=str(data.get('request_key',''))
        if not 16<=len(key)<=100: raise HTTPException(400,'请重新提交')
        from task_signature import signature
        input_signature=signature(data)
        items=data.get('items',[data])
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT id FROM tasks WHERE owner=? AND (batch_id=? OR request_key=?) ORDER BY rowid',(u['id'],key,key)).fetchall()
            if previous:
                bound=db.execute('SELECT signature FROM task_requests WHERE owner=? AND request_key=?',(u['id'],key)).fetchone()
                if not bound or bound['signature']!=input_signature:
                    raise HTTPException(409,'请求标识已对应其他或未验证的历史输入，请先核对原任务；未重新生成')
                return {'id':previous[0]['id'],'ids':[r['id'] for r in previous]}
            project_id=data.get('project_id')
            if project_id:
                from workspace import require_project
                require_project(db,str(project_id),u['id'])
            validate_compositions(db,u['id'],items)
            for item in items:
                from workspace import validate_continuation
                validate_continuation(db,item,u,project_id,hub)
                if not item.get('prompt','').strip(): raise HTTPException(400,'请填写每组提示词')
                model=item.get('model','auto');assets=item.get('assets',[])
                if assets:
                    if not hub.reference_enabled:raise HTTPException(409,'Mini 图片上传尚未完成验证')
                    if not assets:raise HTTPException(409,'目前接通的是 Mini 图片参考，请添加至少一张图片')
                    frames=item.get('mode')=='frames'
                    if frames:
                        if model not in ('auto','5000005'):raise HTTPException(400,'首尾帧请选择 Seedance 2.0')
                        if not 1<=len(assets)<=2 or len({a.get('role') for a in assets})!=len(assets) or {a.get('role') for a in assets} not in ({'first'},{'first','last'}):raise HTTPException(400,'请提供首帧，可选尾帧')
                        assets.sort(key=lambda a:0 if a['role']=='first' else 1)
                    tokens={};counts={'image':0,'video':0,'audio':0}
                    for index,asset in enumerate(assets,1):
                        stored=db.execute('SELECT mime FROM assets WHERE id=? AND owner=?',(asset['id'],u['id'])).fetchone()
                        kind=stored['mime'].split('/')[0];counts[kind]+=1
                        if frames and kind!='image' or not frames and asset.get('role','reference')!='reference':raise HTTPException(400,'素材用途与生成模式不匹配')
                        token=asset.get('token','')
                        if token:
                            label={'image':'图片','video':'视频','audio':'音频'}[kind]
                            if not isinstance(token,str) or not re.fullmatch(label+r'[0-9]+',token) or token in tokens:raise HTTPException(400,label+'引用编号有误，请重新添加素材')
                            tokens[token]=f'<|media:{index-1}|>'
                    if counts['image']>9 or counts['video']>3 or counts['audio']>3 or not counts['image']+counts['video']:raise HTTPException(400,'最多 9 图、3 视频、3 声音，声音需要配合图片或视频')
                    def replace_reference(match):
                        if match.group(1) not in tokens:raise HTTPException(400,'提示词引用了已移除的素材，请重新选择')
                        return tokens[match.group(1)]
                    item['provider_prompt']=re.sub(r'@(图片[0-9]+|视频[0-9]+|音频[0-9]+)',replace_reference,item['prompt'].strip())
                elif item.get('mode')=='frames':raise HTTPException(400,'请添加首帧图片')
                elif model not in ('auto','5000005'):
                    raise HTTPException(409,'Mini / Fast 当前需要至少一张参考图')
            requested=str(data.get('account_id','pool'))
            pool=db.execute("SELECT * FROM accounts WHERE scope='shared' AND enabled=1 AND status='connected' ORDER BY checked,id").fetchall()
            if requested!='pool': pool=[a for a in pool if a['id']==requested]
            if not pool: raise HTTPException(400,'公司账号池中没有可用连接，请联系管理员')
            db.execute('INSERT INTO task_requests VALUES(?,?,?)',(u['id'],key,input_signature))
            load={a['id']:db.execute("SELECT COUNT(*) FROM tasks WHERE account_id=? AND state IN ('queued','submitting','running','unknown','attention')",(a['id'],)).fetchone()[0] for a in pool}
            ids=[]
            for item in items:
                item['account_choice']=requested
                for _ in range(item.get('count',1)):
                    account=min(pool,key=lambda a:load[a['id']]); load[account['id']]+=1
                    tid=secrets.token_hex(12); now=time.time(); index=len(ids)
                    db.execute('INSERT INTO tasks(id,owner,account_id,prompt,state,created,updated,request_key,duration,config,batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(tid,u['id'],account['id'],item['prompt'].strip(),'queued',now,now,key+':'+str(index),item.get('duration',5),json.dumps(item,ensure_ascii=False),key))
                    hub.log(db,u['id'],'task_queued',tid); ids.append(tid)
                    if project_id:
                        db.execute('INSERT INTO project_tasks VALUES(?,?,?,?)',(str(project_id),tid,u['id'],now))
        return {'id':ids[0],'ids':ids}

    @app.post('/api/tasks/{task_id}/action')
    async def action(task_id: str,request: Request):
        u=user(request); data=await body(request); action=data.get('action')
        if action=='reconcile':
            with hub.db() as db:
                task=task_access(db,task_id,u)
                if task['state']!='unknown': raise HTTPException(400,'任务不需要关联')
                account=db.execute('SELECT * FROM accounts WHERE id=?',(task['account_id'],)).fetchone()
            remote=str(data.get('remote_id',''))
            if not remote.isdigit() or len(remote)>30: raise HTTPException(400,'请填写从网页核实的任务 ID')
            import asyncio
            try:
                found=await asyncio.to_thread(hub.provider.find,hub.headers(account),remote)
                settings=json.loads(found.get('settings','{}')) if found else {}
                expected=json.loads(task['config']).get('provider_prompt',task['prompt'])
                matched=found and settings.get('prompt')==expected and abs(float(found.get('createdAt',0))-(task['submitted_at'] or task['updated']))<600
            except Exception:
                matched=False
            if not matched: raise HTTPException(400,'网页任务的提示词和创建时间不匹配，无法关联')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE'); task=task_access(db,task_id,u)
            if action=='cancel' and task['state']=='queued':
                db.execute("UPDATE tasks SET state='cancelled',updated=? WHERE id=?",(time.time(),task_id))
            elif action=='sync' and task['remote_id'] and task['state'] in ('attention','running'):
                db.execute("UPDATE tasks SET state='running',poll_at=0,updated=? WHERE id=?",(time.time(),task_id))
            elif action=='reconcile' and task['state']=='unknown':
                remote=str(data.get('remote_id',''))
                if not remote.isdigit() or len(remote)>30: raise HTTPException(400,'请填写从网页核实的任务 ID')
                db.execute("UPDATE tasks SET state='running',remote_id=?,poll_at=0,updated=? WHERE id=?",(remote,time.time(),task_id))
            elif action=='close' and task['state'] in ('unknown','attention') and (u['role']=='admin' or task['scope']=='personal' and task['owner']==u['id']):
                db.execute("UPDATE tasks SET state='closed',error='账号负责人核对后关闭追踪；不代表平台取消',updated=? WHERE id=?",(time.time(),task_id))
            else: raise HTTPException(400,'当前状态不支持此操作')
            hub.log(db,u['id'],'task_'+action,task_id)
        return {'ok':True}

    @app.get('/api/tasks/{task_id}/video')
    def video(task_id: str,request: Request,download: bool=False):
        u=user(request)
        if task_id.startswith('footage_'):
            try:path=app.state.editor.source(u['id'],False,task_id)
            except ValueError:raise HTTPException(404,'视频不存在或无权使用') from None
            return FileResponse(path,media_type='video/mp4')
        with hub.db() as db:
            external=db.execute("SELECT asset_id FROM libtv_jobs WHERE id=? AND owner=? AND state='ready'",(task_id,u['id'])).fetchone()
        if external:
            path=hub.assets/external['asset_id']
            if not path.is_file():raise HTTPException(404,'视频文件不可用')
            return FileResponse(path,media_type='video/mp4',filename='LibTV-'+task_id+'.mp4' if download else None)

        with hub.db() as db:
            task=task_access(db,task_id,u)
        path=hub.media/(task['id']+'.mp4')
        if task['state']!='ready' or not path.is_file(): raise HTTPException(404,'视频尚不可用')
        return FileResponse(path,media_type='video/mp4',filename=task_id+'.mp4' if download else None)

    @app.get('/api/users')
    def users(request: Request):
        user(request,True)
        with hub.db() as db: return [safe_user(u) for u in db.execute('SELECT * FROM users ORDER BY username')]

    @app.post('/api/users')
    async def add_user(request: Request):
        admin=user(request,True); data=await body(request)
        name=str(data.get('username','')).strip(); pw=str(data.get('password','')); limit=0
        if not 2<=len(name)<=40 or not 12<=len(pw)<=200: raise HTTPException(400,'用户名 2–40 字，密码至少 12 字符')
        with hub.db() as db:
            try:
                uid=secrets.token_hex(12)
                db.execute('INSERT INTO users(id,username,password,role,daily_limit,must_change) VALUES(?,?,?,?,?,1)',(uid,name,password_hash(pw),'member',limit))
                hub.log(db,admin['id'],'user_created',uid)
            except sqlite3.IntegrityError: raise HTTPException(409,'用户名已存在') from None
        return {'ok':True}

    @app.post('/api/users/{uid}')
    async def update_user(uid: str,request: Request):
        admin=user(request,True); data=await body(request)
        if uid==admin['id']: raise HTTPException(400,'此处不能修改自己的权限')
        limit=0
        if type(data.get('enabled')) is not bool: raise HTTPException(400,'参数有误')
        with hub.db() as db:
            target=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            if not target or target['role']=='admin': raise HTTPException(400,'请选择普通成员')
            db.execute('UPDATE users SET daily_limit=?,enabled=? WHERE id=?',(limit,int(data['enabled']),uid))
            if not data['enabled']: db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            hub.log(db,admin['id'],'user_updated',uid)
        return {'ok':True}

    @app.post('/api/users/{uid}/reset-password')
    async def reset_member_password(uid: str,request: Request):
        admin=user(request,True);data=await body(request)
        pw=data.get('password')
        if not isinstance(pw,str) or not 12<=len(pw)<=200:raise HTTPException(400,'临时密码需 12–200 字符')
        encoded=password_hash(pw)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            target=db.execute('SELECT role FROM users WHERE id=?',(uid,)).fetchone()
            if not target or target['role']=='admin' or uid==admin['id']:raise HTTPException(400,'只能重置普通成员的密码')
            db.execute('UPDATE users SET password=?,must_change=1 WHERE id=?',(encoded,uid))
            db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            hub.log(db,admin['id'],'user_password_reset',uid)
        return {'ok':True}

    @app.get('/api/audit')
    def audit(request: Request):
        user(request,True)
        with hub.db() as db:
            return [dict(r) for r in db.execute('SELECT a.at,u.username,a.action,a.target FROM audit a LEFT JOIN users u ON a.actor=u.id ORDER BY a.id DESC LIMIT 100')]

    from kalodata_integration import attach as attach_kalodata
    attach_kalodata(app,hub,user,body)
    from apify_monitor import attach as attach_apify_monitor
    attach_apify_monitor(app,hub,user,body)
    from script_automation import attach as attach_script_automation
    attach_script_automation(app,hub,user,body)
    from script_library import attach as attach_script_library
    attach_script_library(app,hub,user,body)
    from video_cases import attach as attach_video_cases
    attach_video_cases(app,hub,user,body)
    from product_intel import attach as attach_goods
    attach_goods(app,hub,user,worker)
    from own_goods import attach as attach_own_goods
    attach_own_goods(app,hub,user,body)
    from editor import attach
    attach(app,hub,user,body)
    from ai_editing import attach as attach_ai_editing
    attach_ai_editing(app,hub,user,body)
    from mobile_transfer import attach as attach_mobile
    attach_mobile(app,hub,user,body,origin,app.state.store_mobile_footage)
    from feishu_integration import attach as attach_feishu
    attach_feishu(app,hub,user,body,origin)
    from workspace import attach as attach_workspace
    attach_workspace(app,hub,user,body)
    from asset_classification import initialize as initialize_classification
    initialize_classification(hub)
    from media_tools import attach as attach_media
    attach_media(app,hub,user,body)
    from sfx import attach as attach_sfx
    attach_sfx(app,hub,user,body)
    # --- AI 配音（独立 Fish Audio 服务，与 TikTok 调度隔离）---
    from voice import Voice
    hub.voice = Voice(hub)
    hub.voice.attach(app, user)


    from exception_center import attach as attach_exception_center
    attach_exception_center(app,hub,user)
    from assistant_chat import attach as attach_assistant
    attach_assistant(app,hub,user,body)
    from comment_samples import attach as attach_comment_samples
    attach_comment_samples(app,hub,user,body)
    from product_research import attach as attach_own_goods_research
    attach_own_goods_research(app,hub,user,body)
    from own_goods_cover import attach as attach_goods_cover
    attach_goods_cover(app,hub,user)
    from product_research_updates import attach as attach_research_updates
    attach_research_updates(app,hub,user)
    # Provider migration must not automatically enqueue old waiting assets.

    from libtv_gateway import attach as attach_libtv
    attach_libtv(app,hub,user,body)

    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
    @app.get('/')
    def index(): return FileResponse(ROOT/'static'/'index.html')
    return app


if __name__=='__main__':
    import uvicorn
    uvicorn.run(create_app(worker=os.getenv('HUB_WORKER','1')=='1'),host='127.0.0.1',port=int(os.getenv('HUB_PORT','8765')),proxy_headers=False,access_log=False)
