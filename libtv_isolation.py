"""Per-profile CLI credentials; never mutate the parent process environment."""
import json,os,re,shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'state'/'libtv-profiles'
def profile_dir(profile):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',profile):raise ValueError('Invalid LibTV profile')
    return ROOT/profile

def bind(work,profile):
    profile_dir(profile)
    marker=Path(work)/'hub-libtv-profile.json'
    if marker.exists():
        if json.loads(marker.read_text(encoding='utf-8'))['profile']!=profile:
            raise RuntimeError('Cannot change account of an existing LibTV task')
        return  # Identity bindings are immutable; do not rewrite them on verification.
    with marker.open('x',encoding='utf-8') as stream:
        json.dump({'profile':profile},stream)

def environment(work):
    marker=Path(work)/'hub-libtv-profile.json'
    profile=json.loads(marker.read_text(encoding='utf-8'))['profile'] if marker.exists() else 'legacy'
    directory=profile_dir(profile)
    if not (directory/'credentials.json').is_file():
        raise RuntimeError('LibTV 账号尚未独立授权，请管理员完成登录；不会使用其他账号')
    env=os.environ.copy()
    env.pop('LIBTV_TOKEN',None)
    env['LIBTV_CONFIG_DIR']=str(directory.resolve())
    return env

def migrate_legacy():
    target=profile_dir('legacy');target.mkdir(parents=True,exist_ok=True)
    dest=target/'credentials.json'
    if dest.exists():return
    source=Path(os.environ.get('LIBTV_CONFIG_DIR') or Path.home()/'.libtv')/'credentials.json'
    if not source.is_file():return
    # Copy once: later global logins must never replace the shared hub identity.
    with dest.open('xb') as out:out.write(source.read_bytes())
