"""Shared LibTV CLI gateway. Owner-scoped jobs; never retry generation."""
import hashlib, json, os, re, secrets, shutil, sqlite3, subprocess, time, logging, asyncio, threading
from bounded_process import run as run_bounded
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from libtv_isolation import environment as profile_environment, bind as bind_profile
from fastapi import HTTPException, Request
import task_feedback as feedback
from exception_center import safe_error

VIDEO_MODELS={'star-video2':'Seedance 2.0 VIP','star-video2-fast':'Seedance 2.0 Fast VIP','star-video2-mini':'Seedance 2.0 Mini','magi-2':'MAGI-2'}
RESOLUTIONS={'star-video2':('480p','720p','1080p','4k'),'star-video2-fast':('480p','720p'),'star-video2-mini':('480p','720p'),'magi-2':('1080p',)}
MAGI_MODEL = 'magi-2'
MAGI_MAX_SECONDS = 30
MAGI_MAX_REFERENCES = 20
MAGI_REFERENCE_LIMITS = {'image': 10, 'video': 5, 'audio': 5}

def decoded(raw):
    """CLI output is UTF-8 on most hosts but GBK on Chinese Windows consoles."""
    if raw is None:return ''
    if not isinstance(raw,bytes):return str(raw)
    for codec in ('utf-8','gbk'):
        try:return raw.decode(codec)
        except UnicodeDecodeError:pass
    return raw.decode('utf-8','replace')


class ProviderGenerationFailed(RuntimeError):
    pass

class Transient(RuntimeError):
    """A read-only step (download / canvas probe) failed for a reason that usually clears by itself."""


DOWNLOAD_RETRY_DELAYS = (5, 15, 30)  # seconds between in-request download attempts
AUTO_RETRY_LIMIT = 12                # background recovery attempts per job


def _concurrency_cap():
    """Operator cap for parallel generations. 0 (the default) means the whole team may submit at once."""
    try:return max(0,int(os.environ.get('LIBTV_MAX_CONCURRENT') or 0))
    except (TypeError,ValueError):return 0


CONCURRENCY_CAP = _concurrency_cap()  # shared account, one canvas per job: parallel by design


def _worker_count():
    """Threads reserved for generations. Each job parks its thread for minutes, so it must not
    eat the shared API pool (default 40) that serves every other request."""
    try:return max(1,int(os.environ.get('LIBTV_MAX_WORKERS') or 64))
    except (TypeError,ValueError):return 64


MAX_WORKERS = _worker_count()
GENERATIONS = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='libtv-gen')
_EXECUTION_SLOTS=threading.BoundedSemaphore(MAX_WORKERS)
async def execute_bounded(function,*args):
    if not _EXECUTION_SLOTS.acquire(False):raise HTTPException(429,'LibTV 执行资源繁忙，请稍后核对原任务；未排入无界等待队列')
    def work():
        try:return function(*args)
        finally:_EXECUTION_SLOTS.release()
    try:future=asyncio.get_running_loop().run_in_executor(GENERATIONS,work)
    except Exception:
        _EXECUTION_SLOTS.release();raise
    return await asyncio.shield(future)
NOISE = re.compile(r'UNDICI|trace-warnings|ExperimentalWarning|DeprecationWarning')


def scrub(text):
    """Short, credential-free excerpt of CLI output for the diagnostics file."""
    text = '\n'.join(l for l in text.splitlines() if not NOISE.search(l))
    text = re.sub(r'https?://[^\s"\'<>]+', lambda m: '<' + (m.group(0).split('/')[2] if m.group(0).count('/') >= 2 else 'url') + '>', text)
    text = re.sub(r'(?i)(token|authorization|bearer|cookie|secret|password|api[_-]?key)[^\n]{0,80}', r'\1 <redacted>', text)
    return re.sub(r'\s+', ' ', text).strip()[-300:]


def error_excerpt(text, args=()):
    """Keep error fields only; redact before truncating, never store CLI arguments."""
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    # Remove exact invocation values (prompts, paths, reference payloads).
    for value in sorted((str(v) for v in args if len(str(v)) > 8), key=len, reverse=True):
        text = text.replace(value, '<argument>')
    try:
        obj = json.loads(text)
        parts = []
        def visit(item):
            if isinstance(item, dict):
                for key, value in item.items():
                    if key.lower() in ('message','msg','error','detail','reason','code','error_code'):
                        if isinstance(value, (str, int)): parts.append(str(value))
                        else: visit(value)
                    elif isinstance(value, dict): visit(value)
        visit(obj)
        text = '\n'.join(parts)
    except ValueError:
        text = re.sub(r'https?://[^\s"<>]+', '<address>', text)
        text = '\n'.join(line for line in text.splitlines()
                         if re.search(r'error|fail|exception|错误|失败|code|msg|message', line, re.I)
                         and not re.search(r'prompt|提示词|cookie|authorization|password|secret|token|api[_-]?key', line, re.I))
    text = re.sub(r'(?i)(?:https?://|[a-z]:[\\/])[^\s\"\'<>]+', '<address>', text)
    text = re.sub(r'(?i)(token|authorization|bearer|cookie|secret|password|api[_-]?key)\s*[\"\x27]*\s*[:=]?\s*[^\n]+', r'\1 <redacted>', text)
    text = re.sub(r'\b[A-Za-z0-9_+/=-]{32,}\b', '<identifier>', text)
    return re.sub(r'\s+', ' ', text).strip()[:800]


def retryable_download(text):
    """Downloading only reads; every failure except a definite one is worth retrying."""
    return not re.search(r'\b(?:401|10001|10002)\b|用户未授权|未登录|未授权|登录已过期|unauthorized|没有可下载|无可下载|no\s+downloadable|与 --watermark (?:true|false) 不一致|未找到|不存在|not\s+found', text, re.I)


def api_code(text):
    m=re.search(r'(?i)(?:error_)?code[\"\x27]?\s*[:=]\s*[\"\x27]?(\d{3,9})',text) or re.search(r'\[(\d{3,9})\]',text)
    return m.group(1) if m else ''


def cli_failure(args,stdout,stderr):
    """Expose only allowlisted diagnoses; CLI output may contain credentials."""
    text=decoded(stdout)+'\n'+decoded(stderr)
    operation={'account':'账号检查','model':'模型检查','project':'画布操作','upload':'参考图上传','node':'节点操作','download':'结果下载'}.get(args[0] if args else '', '操作')
    if re.search(r'\b(?:401|10001|10002)\b|用户未授权|未登录|未授权|登录已过期|token\s+(?:expired|invalid)|\bunauthorized\b',text,re.I):
        code=api_code(text)
        return f'LibTV {operation}失败：中台这台电脑的 LibTV 登录已失效（接口 {code or "401"} 未登录/未授权）。这是登录状态问题，不需要去官网重做视频；请管理员在运行中台的电脑执行 libtv login web 完成浏览器授权，然后在制作台点“重新核验 LibTV 连接”，再点“取回已生成视频”。未自动重试。'
    if re.search(r'无法确认账号会员态', text):
        return f'LibTV {operation}暂时失败：下载前无法确认账号会员状态（服务端临时无响应）。这是读取操作，不会重新生成也不扣费；中台会自动重试取回。'
    if re.search(r'与 --watermark (?:true|false) 不一致', text):
        return f'LibTV {operation}失败：账号会员状态与下载水印设置不一致，请管理员核对 LIBTV_DOWNLOAD_WATERMARK 与官网会员状态。视频已在画布上，修正后点“取回已生成视频”即可，不需要重新生成。'
    if re.search(r'未通过.*合规|合规.*不通过|真人资产录入',text):
        refs=list(dict.fromkeys(re.findall(r'参考[0-9]{1,3}',text)))
        label='、'.join(refs) or '参考素材'
        return f'LibTV 生成前校验未通过：{label}未通过 Seedance 合规检测，生成尚未启动。若涉及真人素材，请先在 LibTV 官方角色库完成真人资产录入，再使用合规素材。未自动重试。'
    if re.search(r'余额不足|积分不足|额度不足|insufficient\s+(?:credits?|balance|quota)',text,re.I):
        return f'LibTV {operation}失败：账号可用额度不足；请管理员核对官网余额。未自动重试；已有画布请先核对原任务。'
    if re.search(r'ECONNRESET|ETIMEDOUT|ENOTFOUND|fetch failed|connection reset|ECONNREFUSED',text,re.I):
        return f'LibTV {operation}失败：网络连接异常，操作结果可能未知；请先核对官网原任务，未自动重试。'
    if re.search(r'没有可下载的资源|无可下载|no\s+downloadable',text,re.I):
        return f'LibTV {operation}失败：节点上没有可下载的成片（生成未产出视频）。未自动重试，也不会重复扣费；请在画布核对后重新发起生成。'
    if re.search(r'未找到模型|模型.*不存在|unknown\s+model|model.*not\s+found',text,re.I):
        return f'LibTV {operation}失败：模型名称未被 CLI 识别，请管理员核对 model search 中的模型名称。未自动重试。'
    if re.search(r'画布不存在|节点不存在|未找到|not\s+found|no\s+(?:video|node|result)',text,re.I):
        return f'LibTV {operation}失败：画布或节点在 LibTV 上找不到（可能已被删除）；未自动重试，也不会重复扣费。'
    code=api_code(text)
    if args and args[0]=='upload':
        return f'LibTV 参考素材上传未成功（接口 {code or "未知"}），原因尚无法确认；请管理员排查素材和连接。未自动重试。'
    return f'LibTV {operation}未成功（接口 {code or "未知"}）；具体原因尚未确认。未自动重试；请先核对原任务，不要直接重新生成。'


def cli(args,cwd):
    operation=args[0] if args else ''
    mapping={'account':'libtv_account','model':'libtv_model','project':'libtv_project','upload':'upload','download':'video_download'}
    stage,failure=(('submit','unknown') if '--run' in args else
                   ('libtv_probe','attention') if operation=='node' and args[1:2]!=['create'] else
                   ('libtv_node','blocked') if operation=='node' else
                   (mapping.get(operation,'libtv_probe'),'attention' if operation=='download' else 'blocked'))
    with feedback.step(stage,failure) as attempt:
        return _invoke_cli(args,cwd,attempt)


def _invoke_cli(args,cwd,observed):
    executable=shutil.which('libtv',path=str(Path(__file__).resolve().parent/'tools/libtv-1.2.0')) or shutil.which('libtv')
    if not executable or Path(executable).suffix.lower() not in ('.exe',''):raise RuntimeError('LibTV CLI 不可用')
    if args and args[0]=='download' and '--watermark' not in args:
        # Shared account is an active VIP; server independently enforces entitlement.
        watermark=os.environ.get('LIBTV_DOWNLOAD_WATERMARK','false')
        if watermark not in ('true','false'):raise RuntimeError('LibTV 下载水印配置无效')
        at=args.index('-o') if '-o' in args else len(args)
        args=[*args[:at],'--watermark',watermark,*args[at:]]
    # Retry only the read-only identity probe, never upload or generation.
    attempts=3 if args==['account','list'] else 1
    for attempt in range(attempts):
        try:
            budget=30 if args[0]=='account' else 900 if '--run' in args else 180 if args[0] in ('upload','download') else 60
            result=run_bounded([executable,*args],cwd=cwd,env=profile_environment(cwd),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=budget)
        except subprocess.TimeoutExpired:
            if attempt+1<attempts:
                time.sleep(attempt+1)
                continue
            observed.error_type('TimeoutExpired')
            if args[0]=='account':raise RuntimeError('LibTV 账号检查超时，已尝试三次；生成尚未启动，请稍后再试。') from None
            if args[0]=='download':raise Transient('LibTV 原结果下载超时，未重新生成；可稍后取回') from None
            raise RuntimeError('LibTV 操作超时，已停止本地命令；远端结果可能未知，请核对原画布，未自动重新提交') from None
        transient=re.search(r'ECONNRESET|ETIMEDOUT|ENOTFOUND|fetch failed|connection reset|ECONNREFUSED',decoded(result.stdout)+'\n'+decoded(result.stderr),re.I)
        if not result.returncode or not transient or attempt+1==attempts:break
        time.sleep(attempt+1)
    stdout=decoded(result.stdout);stderr=decoded(result.stderr)
    observed.exit_code(result.returncode)
    if result.returncode:
        observed.code(api_code(stdout+'\n'+stderr))
        # Retain a safe diagnostic, never credentials, prompts, URLs or raw output.
        record={'operation':args[0] if args else '', 'run':'--run' in args,
                'exit_code':result.returncode, 'api_code':api_code(stdout+'\n'+stderr),
                'output_sha256':hashlib.sha256((stdout+'\n'+stderr).encode()).hexdigest(),
                'diagnosis':cli_failure(args,stdout,stderr), 'time':time.time()}
        record['diagnostic_id']=secrets.token_hex(6)
        record['stage']='启动生成' if '--run' in args else {'upload':'上传素材','download':'下载成片','account':'账号检查','project':'画布操作','node':'配置或查询节点'}.get(args[0] if args else '', 'CLI 操作')
        record['task_id']=Path(cwd).name
        record['excerpt']=' | '.join(filter(None,(error_excerpt(stdout,args),error_excerpt(stderr,args))))[:1200]
        try:
            with (Path(cwd)/'cli-diagnostics.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps(record,ensure_ascii=False)+'\n')
        except OSError:
            logging.getLogger(__name__).error('LibTV diagnostic fallback: %s',json.dumps(record,ensure_ascii=False))
        record['diagnosis'] += ' 排查编号：'+record['diagnostic_id']+'。'
        if record['excerpt']: record['diagnosis'] += ' 错误摘要：'+record['excerpt'][:300]
        if '--run' in args and '生成前校验未通过' in record['diagnosis']:observed.mark('blocked')
        if args and args[0] == 'download' and retryable_download(stdout + '\n' + stderr): raise Transient(record['diagnosis'])
        raise RuntimeError(record['diagnosis'])
    # `download` writes the file and prints a human-readable completion message
    # in CLI 1.1.x. Its callers validate the actual media file, not stdout JSON.
    if args and args[0]=='download':return {'download_completed':True}
    try:return json.loads(stdout)
    except ValueError:
        rows=[]
        for line in stdout.splitlines():
            try:rows.append(json.loads(line))
            except ValueError:pass
        if rows:return rows[-1]
        raise RuntimeError('LibTV 返回格式无法识别，请核对官网任务，未自动重试')

def prepare_reference_image(source, jobdir, index):
    """Make a bounded upload copy for oversized images; leave the library original untouched."""
    from PIL import Image, ImageOps
    source = Path(source)
    try:
        with Image.open(source) as image:
            if max(image.size) <= 4096 and source.stat().st_size <= 8 * 1024 * 1024:
                return source
            image = ImageOps.exif_transpose(image)
            image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            target = Path(jobdir) / f'reference-{index}.png'
            if image.mode not in ('RGB', 'RGBA'):
                image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
            image.save(target, format='PNG', optimize=True)
            # Large photographic PNGs can still exceed upload limits; retain transparency
            # with PNG, otherwise use a compact high-quality JPEG copy.
            if target.stat().st_size > 8 * 1024 * 1024 and image.mode == 'RGB':
                target.unlink()
                target = target.with_suffix('.jpg')
                image.save(target, format='JPEG', quality=90, optimize=True)
            while target.stat().st_size > 8 * 1024 * 1024 and max(image.size) > 1024:
                image.thumbnail((max(1, int(image.width * .75)), max(1, int(image.height * .75))), Image.Resampling.LANCZOS)
                if target.suffix == '.jpg':
                    image.save(target, format='JPEG', quality=88, optimize=True)
                else:
                    image.save(target, format='PNG', optimize=True)
            if target.stat().st_size > 8 * 1024 * 1024:
                target.unlink(missing_ok=True)
                raise ValueError('image cannot be reduced sufficiently')
            return target
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise RuntimeError(f'参考图片 {index} 无法读取或尺寸过大，请更换图片；生成尚未提交。') from exc


def node_output(project,cwd):
    """Read the 成片 node: finished media urls, provider failure reason, task status."""
    result=cli(['node','成片','-p',project],cwd)
    data=result.get('data') if isinstance(result,dict) else None
    recognized=isinstance(data,dict) and bool(data)
    if not isinstance(data,dict):data={}
    urls=[u for u in (data.get('url') or []) if isinstance(u,str) and u.startswith('http')]
    task=data.get('taskInfo') if isinstance(data.get('taskInfo'),dict) else {}
    return urls,str(task.get('failedReason') or '').strip(),task.get('status'),bool(task),recognized


def ensure_output(project,cwd,announce,wait_seconds=240):
    """Generation is asynchronous: never download before the canvas has a real video.

    Returns None when the node probe itself is unavailable (unsupported CLI output or
    a transport error), so the caller keeps the plain download path and its own error.
    """
    try:
        urls,reason,status,task,recognized=node_output(project,cwd)
        deadline=time.time()+wait_seconds
        while recognized and not urls and not reason and task and status in (0,1,None) and time.time()<deadline:
            announce('等待 LibTV 出片 · 已排队或生成中，取回会自动继续')
            time.sleep(10)
            urls,reason,status,task,recognized=node_output(project,cwd)
    except Exception:
        return None
    if not recognized:return None
    if urls:return urls
    if reason:
        with feedback.step('libtv_probe','failed'):
            raise ProviderGenerationFailed(f'LibTV 生成未通过：{safe_error(reason)}；未自动重试，积分以官网为准。')
    if task and status in (0, 1, None):
        with feedback.step('libtv_probe','waiting'):
            raise Transient('LibTV 仍在生成中（排队或渲染较慢），不是失败。中台会自动等待并取回，无需重新生成。')
    raise RuntimeError('画布上没有可下载成片：LibTV 未记录到本次生成结果（生成未开始或已失败）。未自动重试，也不会重复扣费；请先在画布核对，必要时重新发起生成。')


def run_video(project,cwd,stage):
    """Run the existing node exactly once; never equate node creation with submission."""
    stage('正在提交生成 · 等待 LibTV 确认')
    failure=None
    try:
        cli(['node','成片','-p',project,'--run'],cwd)
    except RuntimeError as exc:
        failure=exc
        if '生成前校验未通过' in str(exc):
            stage('参考素材校验未通过 · 生成未启动')
            raise
    try:
        urls,reason,status,task,recognized=node_output(project,cwd)
    except Exception:
        stage('生成提交状态待核对')
        with feedback.step('libtv_probe','unknown'):
            raise RuntimeError('LibTV 生成提交状态无法确认；请核对原画布，未自动重试。'+(str(failure).split('未自动重试；已有画布')[0] if failure else '')) from None
    if urls:
        stage('已确认生成完成 · 准备取回')
        return
    if reason:
        stage('LibTV 生成失败')
        with feedback.step('libtv_probe','failed'):
            raise ProviderGenerationFailed('LibTV 生成失败：'+safe_error(reason)+'；未自动重试')
    if recognized and not task:
        stage('未检测到生成任务 · 需核对')
        with feedback.step('libtv_probe','unknown'):
            raise RuntimeError('画布和节点已创建，但未检测到生成任务，尚无成片可取回。请核对官网原画布后再决定是否生成；未自动重试。'+(str(failure).split('未自动重试；已有画布')[0] if failure else ''))
    if task and status in (0,1):
        stage('LibTV 已确认任务 · 排队或生成中')
        return
    stage('生成提交状态待核对')
    raise RuntimeError('LibTV 尚未返回可确认的生成状态；请核对原画布，未自动重试。'+(str(failure).split('未自动重试；已有画布')[0] if failure else ''))


def attach(app,hub,user,body):
    work=hub.directory/'libtv';work.mkdir(exist_ok=True)
    with hub.db() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS libtv_settings(id INTEGER PRIMARY KEY CHECK(id=1),account TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS libtv_jobs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,request_key TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,project TEXT DEFAULT '',asset_id TEXT DEFAULT '',error TEXT DEFAULT '',UNIQUE(owner,request_key));''')

        if 'runner' not in {r['name'] for r in db.execute('PRAGMA table_info(libtv_jobs)')}:
            db.execute('ALTER TABLE libtv_jobs ADD COLUMN runner INTEGER DEFAULT 0')

        if 'stage' not in {r['name'] for r in db.execute('PRAGMA table_info(libtv_jobs)')}:db.execute("ALTER TABLE libtv_jobs ADD COLUMN stage TEXT DEFAULT '准备提交'")
        have = {r['name'] for r in db.execute('PRAGMA table_info(libtv_jobs)')}
        if 'profile' not in have:db.execute("ALTER TABLE libtv_jobs ADD COLUMN profile TEXT NOT NULL DEFAULT 'legacy'")
        db.execute('CREATE TABLE IF NOT EXISTS libtv_profiles(id TEXT PRIMARY KEY,name TEXT NOT NULL,account TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1)')
        for col,ddl in (("retry_at","REAL DEFAULT 0"),("auto_tries","INTEGER DEFAULT 0")):
            if col not in have:
                try: db.execute(f"ALTER TABLE libtv_jobs ADD COLUMN {col} {ddl}")
                except sqlite3.OperationalError: pass  # another hub process added it first

    def recover_interrupted(db):
        # Never resubmit an interrupted CLI invocation; only permit result import.
        import ctypes
        for row in db.execute("SELECT id,runner FROM libtv_jobs WHERE state IN ('running','importing')").fetchall():
            if not row['runner']:continue
            alive=True
            if os.name=='nt':
                kernel=ctypes.windll.kernel32
                kernel.OpenProcess.restype=ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
                kernel.CloseHandle.argtypes=[ctypes.c_void_p]
                handle=kernel.OpenProcess(0x100000,False,row['runner'])
                if handle:
                    alive=kernel.WaitForSingleObject(handle,0)==258;kernel.CloseHandle(handle)
                else:alive=ctypes.get_last_error()==5
            else:
                try:os.kill(row['runner'],0)
                except ProcessLookupError:alive=False
            if not alive:db.execute("UPDATE libtv_jobs SET state='attention',error='服务重启后提交结果待核对；请导入已完成结果，不会自动重新生成' WHERE id=?",(row['id'],))

    def account(directory=None):
        result=cli(['account','list'],directory or work)
        active=next((a for a in result.get('accounts',[]) if a.get('isActive')),None)
        if not active:
            with feedback.step('libtv_account','blocked'):
                raise RuntimeError('LibTV 尚未登录')
        return str(active['accountId'])

    @app.get('/api/libtv/profiles')
    def profiles(request:Request):
        user(request)
        with hub.db() as db:
            result=[dict(r) for r in db.execute('SELECT id,name,enabled FROM libtv_profiles')]
            if db.execute('SELECT 1 FROM libtv_settings').fetchone():result.insert(0,{'id':'legacy','name':'原共享账号','enabled':1})
        return result

    @app.post('/api/libtv/profiles')
    async def create_profile(request:Request):
        user(request,True);data=await body(request)
        name=str(data.get('name','')).strip()[:80]
        if not name:raise HTTPException(400,'请输入账号名称')
        from libtv_isolation import profile_dir
        pid=secrets.token_hex(12);directory=profile_dir(pid);directory.mkdir(parents=True)
        with hub.db() as db:db.execute('INSERT INTO libtv_profiles VALUES(?,?,?,0)',(pid,name,''))
        return {'id':pid,'config_dir':str(directory),'enabled':False}

    @app.get('/api/libtv/profiles/{pid}/setup')
    def profile_setup(pid:str,request:Request):
        user(request,True)
        with hub.db() as db:
            if not db.execute('SELECT 1 FROM libtv_profiles WHERE id=?',(pid,)).fetchone():raise HTTPException(404,'账号不存在')
        from libtv_isolation import profile_dir
        executable=Path(__file__).resolve().parent/'tools/libtv-1.2.0/libtv.exe'
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        command="$previousConfig=$env:LIBTV_CONFIG_DIR; $previousToken=$env:LIBTV_TOKEN; try { $env:LIBTV_CONFIG_DIR="+quote(profile_dir(pid))+"; Remove-Item Env:LIBTV_TOKEN -ErrorAction SilentlyContinue; & "+quote(executable)+" login web --open } finally { $env:LIBTV_CONFIG_DIR=$previousConfig; $env:LIBTV_TOKEN=$previousToken }"
        return {'command':command}

    @app.post('/api/libtv/profiles/{pid}/verify')
    def verify_profile(pid:str,request:Request):
        user(request,True)
        with hub.db() as db:
            if not db.execute('SELECT 1 FROM libtv_profiles WHERE id=?',(pid,)).fetchone():raise HTTPException(404,'账号不存在')
        try:
            directory=work/('profile-'+pid);directory.mkdir(exist_ok=True);bind_profile(directory,pid)
            aid=account(directory)
        except OSError:
            logging.getLogger(__name__).exception('LibTV profile verification filesystem/process failure')
            raise HTTPException(503,'LibTV 账号工作目录或进程访问失败，请管理员检查服务权限；尚未提交生成任务') from None
        except RuntimeError as exc:raise HTTPException(409,str(exc)) from None
        with hub.db() as db:
            old=db.execute('SELECT account FROM libtv_profiles WHERE id=?',(pid,)).fetchone()
            if old['account'] and old['account']!=aid:raise HTTPException(409,'此隔离账号已绑定其他身份，请新建账号')
            db.execute('UPDATE libtv_profiles SET account=?,enabled=1 WHERE id=?',(aid,pid))
        return {'connected':True}

    @app.post('/api/libtv/connect')
    def connect(request:Request):
        u=user(request,True)
        try:aid=account()
        except RuntimeError as e:raise HTTPException(503,str(e)) from None
        with hub.db() as db:
            if db.execute("SELECT 1 FROM libtv_jobs WHERE state='running'").fetchone():raise HTTPException(409,'生成期间不能更换共享连接')
            previous=db.execute('SELECT account FROM libtv_settings WHERE id=1').fetchone()
            if previous and previous['account']!=aid:raise HTTPException(409,'原共享账号身份不可覆盖，请添加独立账号')
            db.execute('INSERT INTO libtv_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET account=excluded.account',(aid,))
            hub.log(db,u['id'],'libtv_connected','shared')
        return {'connected':True}

    @app.get('/api/libtv/status')
    def status(request:Request):
        user(request)
        with hub.db() as db:return {'connected':bool(db.execute('SELECT 1 FROM libtv_settings').fetchone()),'models':VIDEO_MODELS,'resolutions':RESOLUTIONS}

    @app.get('/api/libtv/jobs')
    def jobs(request:Request):
        u=user(request)
        with hub.db() as db:
            recover_interrupted(db)
            rows=[dict(r) for r in db.execute('SELECT id,state,stage,request_key,created,updated,project,asset_id,error,payload,retry_at FROM libtv_jobs WHERE owner=? ORDER BY created DESC LIMIT 100',(u['id'],))]
            diagnostics=feedback.latest_failures(db,[('libtv',r['id']) for r in rows if r['state'] in ('failed','attention')])
        for r in rows:
            p=json.loads(r.pop('payload'));r['prompt']=p['prompt'];r['duration']=p['duration'];r['model']=VIDEO_MODELS.get(p.get('model'),'Seedance 2.5');r['resolution']=p.get('resolution','720p');r['composition_id']=p.get('composition_id','')
            if r['state'] in ('failed','attention'):
                waiting=r['state']=='attention' and (r['retry_at'] or 0)>0 and '仍在生成中' in (r['error'] or '')
                r['feedback']=None if waiting else diagnostics.get(('libtv',r['id']))
                r['feedback_state']='waiting' if waiting else feedback.outcome(r['state'],r['error'],r['feedback'])
            r.pop('retry_at')
            if r['error']:r['error']=safe_error(r['error'])
        return rows

    def mark_failed(jid,reason):
        with hub.db() as db:
            db.execute("UPDATE libtv_jobs SET state='failed',stage='生成失败',error=?,retry_at=0,runner=0,updated=? WHERE id=?",(str(reason)[:1500],time.time(),jid))

    def mark_attention(jid,detail,transient):
        """Park a job for retrieval; schedule background retries only for read-only failures."""
        with hub.db() as db:
            row=db.execute('SELECT auto_tries FROM libtv_jobs WHERE id=?',(jid,)).fetchone()
            tries=(row['auto_tries'] or 0) if row else 0
            retry=time.time()+min(30*2**min(tries,3),180) if transient and (tries<AUTO_RETRY_LIMIT or '仍在生成中' in detail) else 0
            if retry and '自动' not in detail: detail+=' 中台会自动重试取回，无需重新生成。'
            db.execute("UPDATE libtv_jobs SET state='attention',runner=0,error=?,retry_at=?,updated=? WHERE id=?",(detail,retry,time.time(),jid))
            if retry: db.execute("UPDATE libtv_jobs SET stage='等待自动取回' WHERE id=?",(jid,))
        return detail

    def generate(uid,data):
        key=data.get('request_key');prompt=data.get('prompt');assets=data.get('assets',[]);duration=data.get('duration',5);mode=data.get('mode','omni')
        model=data.get('model','star-video2')
        magi=model==MAGI_MODEL
        resolution=data.get('resolution','1080p' if magi else '720p')
        if model not in VIDEO_MODELS or resolution not in RESOLUTIONS[model]:raise HTTPException(400,'模型或分辨率不支持')
        if not isinstance(key,str) or not 16<=len(key)<=100:raise HTTPException(400,'请求标识无效')
        if not isinstance(prompt,str) or not prompt.strip():raise HTTPException(400,'请填写提示词')
        max_duration=MAGI_MAX_SECONDS if magi else 15
        if type(duration) is not int or not 4<=duration<=max_duration or mode not in ('omni','frames'):raise HTTPException(400,'生成参数无效')
        if magi and mode=='frames':raise HTTPException(400,'MAGI-2 请使用全能模式')
        if not isinstance(assets,list) or len(assets)>(MAGI_MAX_REFERENCES if magi else 12) or any(not isinstance(a,dict) or not isinstance(a.get('id'),str) for a in assets):raise HTTPException(400,'素材参数无效')
        if len({a['id'] for a in assets})!=len(assets):raise HTTPException(400,'请勿重复选择素材')
        profile=str(data.get('libtv_profile') or 'legacy')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',profile):raise HTTPException(400,'LibTV 账号标识无效')
        composition=str(data.get('composition_id') or '')
        if composition and not re.fullmatch(r'[a-zA-Z0-9-]{1,64}',composition):raise HTTPException(400,'创作窗口标识无效')
        clean={'profile':profile,'model':model,'resolution':resolution,'prompt':prompt.strip(),'duration':duration,'mode':mode,'composition_id':composition,'assets':[{'id':a['id'],'role':a.get('role','reference'),'token':str(a.get('token',''))[:100]} for a in assets]}
        encoded=json.dumps(clean,sort_keys=True,ensure_ascii=False);jid=secrets.token_hex(16)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            recover_interrupted(db)
            old=db.execute('SELECT * FROM libtv_jobs WHERE owner=? AND request_key=?',(uid,key)).fetchone()
            if old:
                if old['payload']!=encoded:raise HTTPException(409,'请求标识冲突')
                return {'id':old['id'],'state':old['state'],'asset_id':old['asset_id']}
            setting=db.execute('SELECT account FROM libtv_settings WHERE id=1').fetchone() if profile=='legacy' else db.execute('SELECT account FROM libtv_profiles WHERE id=? AND enabled=1',(profile,)).fetchone()
            if not setting:raise HTTPException(409,'请管理员先连接共享 LibTV 账号')
            # 中台的意义就是让整组人同时出片：一个共享账号、多条并行画布，每条任务都有自己的
            # work 目录和项目，互不覆盖。只有管理员显式设了上限（LIBTV_MAX_CONCURRENT>0）才排队。
            if CONCURRENCY_CAP:
                busy=db.execute("SELECT COUNT(*) FROM libtv_jobs WHERE state IN ('running','importing')").fetchone()[0]
                if busy>=CONCURRENCY_CAP:raise HTTPException(429,f'共享 LibTV 当前已有 {busy} 条在生成（并发上限 {CONCURRENCY_CAP}）；请稍后重试，或由管理员调整 LIBTV_MAX_CONCURRENT')
            stored=[]
            for a in clean['assets']:
                row=db.execute('SELECT * FROM assets WHERE id=? AND owner=?',(a['id'],uid)).fetchone()
                if not row or row['mime'].split('/')[0] not in ('image','video','audio'):raise HTTPException(404,'参考素材不存在或无权限')
                stored.append(dict(row,role=a['role'],token=a['token']))
            if magi:
                kinds=[a['mime'].split('/')[0] for a in stored]
                if any(kinds.count(kind)>limit for kind,limit in MAGI_REFERENCE_LIMITS.items()):
                    raise HTTPException(400,'MAGI-2 最多 10 张图、5 条视频、5 条音频')
            if mode=='frames':
                if not 1<=len(stored)<=2 or any(a['mime'].split('/')[0]!='image' for a in stored) or {a['role'] for a in stored} not in ({'first'},{'first','last'}):raise HTTPException(400,'首尾帧需要首帧图片，可选尾帧')
                stored.sort(key=lambda a:a['role']!='first')
            db.execute('INSERT INTO libtv_jobs(id,owner,request_key,payload,state,created,updated) VALUES(?,?,?,?,?,?,?)',(jid,uid,key,encoded,'running',time.time(),time.time()))
            db.execute('UPDATE libtv_jobs SET runner=?,profile=? WHERE id=?',(os.getpid(),profile,jid))
            hub.log(db,uid,'libtv_submitted',jid)
        with feedback.bound(hub,'libtv',jid):
            return generate_video(uid,jid,profile,setting['account'],stored,clean)

    def generate_video(uid,jid,profile,expected_account,stored,clean):
        model,resolution,duration,mode=(clean[k] for k in ('model','resolution','duration','mode'))
        def stage(text):
            with hub.db() as db:db.execute('UPDATE libtv_jobs SET stage=?,updated=? WHERE id=?',(text,time.time(),jid))
        jobdir=work/jid;project='';importing=False
        try:
            with feedback.step('libtv_account','blocked'):
                jobdir.mkdir()
                bind_profile(jobdir,profile)
            active=account(jobdir)
            if active!=expected_account:
                with feedback.step('libtv_account','blocked'):
                    raise RuntimeError('共享 LibTV 账号已切换，请管理员重新连接')
            schema=cli(['model',model],jobdir)
            if schema.get('schema',{}).get('modelKey')!=model:
                with feedback.step('libtv_model','blocked'):
                    raise RuntimeError('模型配置已变化，请管理员检查')
            stage('正在创建画布')
            result=cli(['project','create','中台-'+jid,'--team-id','0','-w','0'],jobdir)
            with feedback.step('save_task','blocked'), hub.db() as db:
                project=(result.get('projectMeta') or {}).get('uuid') or result.get('uuid') or result.get('projectUuid') or (result.get('data') or {}).get('uuid')
                if not isinstance(project,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,64}',project):raise RuntimeError('无法识别新画布，请管理员核对 LibTV；生成尚未提交')
                db.execute('UPDATE libtv_jobs SET project=? WHERE id=?',(project,jid))
            links=[];prompt=clean['prompt']
            for index,a in enumerate(stored,1):
                stage('正在上传参考素材 '+str(index)+'/'+str(len(stored)))
                name='参考'+str(index)
                source=(hub.assets/a['id']).resolve()
                with feedback.step('upload','blocked'):
                    upload_path=prepare_reference_image(source,jobdir,index) if a['mime'].startswith('image/') else source
                try:
                    cli(['upload',name,'-p',project,'-f',str(upload_path),'-t',a['mime'].split('/')[0]],jobdir)
                except RuntimeError as exc:
                    raise RuntimeError(f'参考素材 {index} 上传失败，生成尚未提交；请检查图片大小和格式或联系管理员。未自动重试。'+str(exc)) from exc
                links.extend(['--left',name])
                if a['token']:prompt=re.sub('@'+re.escape(a['token'])+r'(?![0-9])','{{Node "'+name+'"}}',prompt)
            kind='frames2video' if mode=='frames' else 'mixed2video' if stored else 'text2video'
            stage('正在创建生成节点')
            count_settings=[] if model==MAGI_MODEL else ['-s','count=1']
            cli(['node','create','成片','-p',project,'-t','video','--prompt',prompt,'-s','model='+VIDEO_MODELS[model],'-s','modeType='+kind,'-s','ratio=9:16','-s','duration='+str(duration),'-s','resolution='+resolution,*count_settings,*links],jobdir)
            run_video(project,jobdir,stage)
            importing=True  # from here on only read-only steps remain; safe to retry in the background
            return import_result(uid,jid,project,jobdir)
        except ProviderGenerationFailed as exc:
            mark_failed(jid,exc)
            raise HTTPException(502,str(exc)) from None
        except Exception as e:
            detail=str(e) if isinstance(e,RuntimeError) else 'LibTV 处理未完成，请核对官网任务；未自动重试'
            detail=mark_attention(jid,detail,importing and isinstance(e,Transient))
            raise HTTPException(502,detail) from None

    def import_result(uid,jid,project,jobdir):
        def put_stage(text):
            with hub.db() as db:db.execute("UPDATE libtv_jobs SET stage=?,updated=? WHERE id=? AND owner=?",(text,time.time(),jid,uid))
        put_stage('正在核对画布成片状态')
        output=jobdir/'download';output.mkdir(parents=True,exist_ok=True)
        def cached():return [p for p in output.iterdir() if p.is_file() and p.suffix.lower()=='.mp4']
        videos=cached()
        # A previous successful download may have failed only at stdout parsing or
        # publishing. Import those bytes without touching the provider again.
        if not videos:
            # Do not treat a submitted run as a finished video: the canvas decides.
            ensure_output(project,jobdir,put_stage)
            put_stage('生成完成 · 正在下载入库')
            for attempt in range(len(DOWNLOAD_RETRY_DELAYS) + 1):
                try:
                    cli(['download','-p',project,'-n','成片','-o',str(output.resolve())],jobdir)
                    break
                except Transient:
                    for part in cached(): part.unlink(missing_ok=True)  # never keep a partial file
                    if attempt == len(DOWNLOAD_RETRY_DELAYS): raise
                    put_stage(f'下载暂未成功 · {DOWNLOAD_RETRY_DELAYS[attempt]} 秒后自动重试（{attempt+1}/{len(DOWNLOAD_RETRY_DELAYS)}）')
                    time.sleep(DOWNLOAD_RETRY_DELAYS[attempt])
            videos=cached()
        with feedback.step('libtv_save'):
            return publish_result(uid,jid,videos)

    def publish_result(uid,jid,videos):
        if len(videos)!=1 or videos[0].stat().st_size==0:raise RuntimeError('未取得单条 MP4，请在官网核对结果；不会重新生成')
        from editor import probe
        try:duration,streams=probe(videos[0])
        except ValueError as e:raise RuntimeError(str(e)) from None
        if not any(s.get('codec_type')=='video' for s in streams):raise RuntimeError('下载结果不包含有效视频')
        aid=secrets.token_hex(16);target=hub.assets/aid
        try:
            # Keep the downloaded source until the asset and job commit together.
            shutil.copyfile(videos[0],target)
            with hub.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT state,asset_id FROM libtv_jobs WHERE id=? AND owner=?',(jid,uid)).fetchone()
                if not row or row['state'] not in ('running','importing'):raise RuntimeError('任务状态已变化，请刷新任务列表')
                db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(aid,uid,'LibTV-'+jid[:8]+'.mp4','video/mp4',target.stat().st_size,time.time()))
                db.execute("INSERT INTO asset_classification(asset_id,status,folder,source,updated) VALUES(?,'classified','video','file_type',?)",(aid,time.time()))
                db.execute("UPDATE libtv_jobs SET state='ready',stage='已完成 · 已保存到素材库',asset_id=?,error='',runner=0,updated=? WHERE id=? AND owner=?",(aid,time.time(),jid,uid))
        except Exception:
            target.unlink(missing_ok=True);raise
        try:videos[0].unlink()
        except OSError:pass  # Cleanup must not turn a committed result into an error.
        return {'id':jid,'state':'ready','asset_id':aid}

    @app.post('/api/libtv/jobs')
    async def submit(request:Request):
        u=user(request);data=await body(request)
        return await execute_bounded(generate,u['id'],data)

    def recover_job(uid,jid,auto=False):
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM libtv_jobs WHERE id=? AND owner=?',(jid,uid)).fetchone()
            if not row:raise HTTPException(404,'任务不存在')
            if row['state']=='ready':return {'state':'ready','asset_id':row['asset_id']}
            if row['state']!='attention' or not row['project']:raise HTTPException(409,'当前任务不能导入结果')
            db.execute("UPDATE libtv_jobs SET state='importing',runner=?,error='',retry_at=0,auto_tries=COALESCE(auto_tries,0)+?,updated=? WHERE id=?",(os.getpid(),1 if auto else 0,time.time(),jid))
        try:
            with feedback.bound(hub,'libtv',jid,retrieval=True):
                with feedback.step('libtv_account'):
                    bind_profile(work/jid,row['profile'])
                    with hub.db() as db:
                        expected=db.execute('SELECT account FROM libtv_settings WHERE id=1').fetchone() if row['profile']=='legacy' else db.execute('SELECT account FROM libtv_profiles WHERE id=?',(row['profile'],)).fetchone()
                    if not expected:raise RuntimeError('任务原账号身份不匹配，请恢复该账号授权')
                if account(work/jid)!=expected['account']:
                    with feedback.step('libtv_account'):
                        raise RuntimeError('任务原账号身份不匹配，请恢复该账号授权')
                return import_result(uid,jid,row['project'],work/jid)
        except ProviderGenerationFailed as exc:
            mark_failed(jid,exc)
            raise HTTPException(502,str(exc)) from None
        except Exception as e:
            detail=str(e) if isinstance(e,RuntimeError) else '视频入库未完成，已保留下载文件，可再次取回；不会重新生成'
            detail=mark_attention(jid,detail,isinstance(e,Transient))
            raise HTTPException(502,detail) from None

    @app.post('/api/libtv/jobs/{jid}/recover')
    async def recover(jid:str,request:Request):
        return await execute_bounded(recover_job,user(request)['id'],jid)

    def auto_recover_once():
        """Retrieve one parked job whose last failure was read-only. Never generates."""
        with hub.db() as db:
            row=db.execute("SELECT id,owner FROM libtv_jobs WHERE state='attention' AND project!='' AND retry_at>0 AND retry_at<=? ORDER BY retry_at LIMIT 1",(time.time(),)).fetchone()
        if not row:return None
        try:return recover_job(row['owner'],row['id'],True)
        except HTTPException:return None

    def auto_loop():
        while not hub.stop.wait(15):
            try:auto_recover_once()
            except Exception:pass

    app.state.libtv_auto_once=auto_recover_once
    app.state.libtv_auto=auto_loop
