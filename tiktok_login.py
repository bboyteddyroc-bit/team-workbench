"""Admin-initiated visible login helper; credentials travel through a private pipe only."""
import json,os,subprocess,threading,time
from pathlib import Path
from fastapi import HTTPException,Request
from provider import ProviderError


def attach_tiktok_login(app,hub,user):
    root=Path(__file__).resolve().parent
    runtime=Path(os.environ.get('HUB_LOGIN_ELECTRON',str(root.parents[3]/'2026-11-11/windows-agents-md-c-users-111/outputs/seedance-desktop/node_modules/electron/dist/electron.exe')))
    lock=threading.Lock(); state={'state':'idle'}
    def run(actor):
        try:
            env=os.environ.copy();env.pop('ELECTRON_RUN_AS_NODE',None)
            with subprocess.Popen([str(runtime),str(root/'tiktok_login_helper.cjs'),str(root/'state/tiktok-login-browser')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,creationflags=subprocess.CREATE_NO_WINDOW) as proc:
                try:out,diagnostic=proc.communicate(timeout=620)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.communicate();raise ValueError('登录超时，请重新连接')
            lines=[x for x in out.decode('utf-8',errors='replace').splitlines() if x.startswith('HUB_LOGIN:')]
            if not lines:
                # Log only known crash categories, never request headers or raw browser output.
                category='GPU' if b'gpu' in diagnostic.lower() else 'runtime'
                raise ValueError(f'登录工具退出（退出码 {proc.returncode}，{category}）；未更新账号，请重试登录窗口')
            result=json.loads(lines[-1][10:])
            if 'error' in result:raise ValueError(result['error'])
            state.update(state='verifying',message='正在核验全部子账号')
            result['headers']['content-type']='application/json'
            account={'secret':hub.cipher.encrypt(json.dumps(result['headers']).encode()),'owner':actor}
            count=hub.sync_subaccounts(account,actor)
            if not count:raise ValueError('未返回可用子账号，原连接未更改')
            state.update(state='ready',message=f'已核验并更新 {count} 个子账号')
        except (ValueError,ProviderError) as exc:state.update(state='error',message=str(exc))
        except Exception:state.update(state='error',message='登录同步未完成，请检查服务器登录工具或网络')
        finally:lock.release()
    @app.post('/api/accounts/browser-login')
    async def start(request:Request):
        actor=user(request,True)
        if not runtime.is_file():raise HTTPException(503,'服务器缺少登录工具，请管理员配置 HUB_LOGIN_ELECTRON')
        if not lock.acquire(False):return dict(state)
        state.clear();state.update(state='waiting',message='请在服务器电脑弹出的 TikTok 窗口登录，成功后自动同步')
        threading.Thread(target=run,args=(actor['id'],),daemon=True).start()
        return dict(state)
    @app.get('/api/accounts/browser-login')
    async def status(request:Request):
        user(request,True)
        return dict(state)
