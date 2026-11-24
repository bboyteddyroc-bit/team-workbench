"""AI 配音服务：音色库、Fish Audio 任务队列、API 路由。

与 TikTok 调度完全隔离：
- 独立表 voice_jobs / voice_voices / voice_favorites / voice_settings
- 独立线程 loop（HUB_VOICE_WORKER 控制），不碰 tasks 表
- 不自动重试：每个 job 的 request_key 唯一，失败即终态
"""
from __future__ import annotations

import json
import math
import os
import queue
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import HTTPException, Request, APIRouter
from fastapi.routing import APIRoute
from fastapi.responses import FileResponse

import fishaudio as fa


class VoiceRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def guarded(request):
            try:return await handler(request)
            except (ValueError, TypeError) as exc:
                raise HTTPException(400,str(exc) if isinstance(exc,ValueError) else '配音参数格式无效') from None
        return guarded


# ------------------------------------------------------------------ 工具

def _now():
    return time.time()


def _ffprobe_duration(path):
    tool = shutil.which('ffprobe')
    if not tool:
        raise ValueError('执行机未找到 FFprobe，请联系管理员')
    import subprocess
    try:
        out = subprocess.run(
            [tool, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('音频校验超时') from None
    if out.returncode:
        raise ValueError('音频文件无法解码')
    data = json.loads(out.stdout or b'{}')
    try:
        duration = float(data.get('format', {}).get('duration', 0))
    except (TypeError, ValueError):
        duration = 0.0
    streams = data.get('streams', [])
    if not any(s.get('codec_type') == 'audio' for s in streams):
        raise ValueError('输出文件不含音频轨')
    if not math.isfinite(duration) or duration <= 0.05:
        raise ValueError('音频时长为 0，合成失败')
    return duration


# ------------------------------------------------------------------ 服务

class Voice:
    def __init__(self, hub):
        self.hub = hub
        self.root = hub.directory / 'voice'
        self.root.mkdir(exist_ok=True)
        self.files = self.root / 'audio'
        self.files.mkdir(exist_ok=True)
        self.samples = self.root / 'samples'
        self.samples.mkdir(exist_ok=True)
        self.wake = threading.Event()
        self._init_schema()
        self._seed_defaults()

    # -- DB --

    def _init_schema(self):
        with self.hub.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS voice_settings(
              id INTEGER PRIMARY KEY CHECK(id=1),
              api_key BLOB, model TEXT DEFAULT 's2.1-pro',
              format TEXT DEFAULT 'wav', enabled INTEGER DEFAULT 0,
              updated REAL, updated_by TEXT);

            CREATE TABLE IF NOT EXISTS voice_voices(
              id TEXT PRIMARY KEY, name TEXT NOT NULL, reference_id TEXT NOT NULL,
              language TEXT DEFAULT '', style TEXT DEFAULT '',
              sample_path TEXT DEFAULT '', created REAL, created_by TEXT,
              enabled INTEGER DEFAULT 1);

            CREATE TABLE IF NOT EXISTS voice_favorites(
              user_id TEXT NOT NULL, voice_id TEXT NOT NULL,
              created REAL, PRIMARY KEY(user_id, voice_id));

            CREATE TABLE IF NOT EXISTS voice_jobs(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_key TEXT NOT NULL,
              text TEXT NOT NULL, display_text TEXT DEFAULT '',
              voice_id TEXT NOT NULL, reference_id TEXT NOT NULL,
              model TEXT NOT NULL, fmt TEXT NOT NULL, speed REAL DEFAULT 1.0,
              insert_at REAL DEFAULT 0.0, make_captions INTEGER DEFAULT 1,
              project_id TEXT DEFAULT '',
              state TEXT NOT NULL, error TEXT DEFAULT '',
              audio_path TEXT DEFAULT '', duration REAL DEFAULT 0.0,
              captions TEXT DEFAULT '[]', warnings TEXT DEFAULT '[]',
              created REAL NOT NULL, updated REAL NOT NULL,
              UNIQUE(owner, request_key));
            CREATE INDEX IF NOT EXISTS voice_job_state ON voice_jobs(state, created);
            ''')
            for table,columns in {
                'voice_voices':{'official_sample':"TEXT DEFAULT ''"},
                'voice_jobs':{'input_signature':"TEXT NOT NULL DEFAULT ''",'language':"TEXT NOT NULL DEFAULT ''",'workflow':"TEXT DEFAULT '{}'",'asset_id':"TEXT DEFAULT ''",'completion_state':"TEXT DEFAULT ''",'timeline_status':"TEXT DEFAULT ''",'workflow_error':"TEXT DEFAULT ''"}
            }.items():
                existing={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
                for name,kind in columns.items():
                    if name not in existing:db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+kind)
            row = db.execute('SELECT COUNT(*) c FROM voice_settings').fetchone()
            if not row['c']:
                db.execute('INSERT INTO voice_settings(id,model,format,enabled,updated) '
                           'VALUES(1,?,?,0,?)', ('s2.1-pro', 'wav', _now()))
            if not db.execute('SELECT COUNT(*) c FROM voice_voices').fetchone()['c']:
                # 只在首次建库时插入占位音色；reference_id 为空，管理员必须填真实 ID
                db.execute('''INSERT INTO voice_voices
                    (id,name,reference_id,language,style,sample_path,created,enabled)
                    VALUES(?,?,?,?,?,?,?,0)''',
                    (secrets.token_hex(8), '示例音色（待配置）', '', 'zh-CN',
                     '占位条目，请管理员填写真实 reference_id 与示例音频', '', _now()))

    def _seed_defaults(self):
        pass

    # -- 配置 --

    def settings(self):
        with self.hub.db() as db:
            row = db.execute('SELECT * FROM voice_settings WHERE id=1').fetchone()
        if not row:
            return {'enabled': False, 'model': 's2.1-pro', 'format': 'wav',
                    'has_key': False, 'updated': 0}
        return {
            'enabled': bool(row['enabled']) and bool(row['api_key']),
            'configured': bool(row['api_key']),
            'has_key': bool(row['api_key']),
            'model': row['model'] or 's2.1-pro',
            'format': row['format'] or 'wav',
            'updated': row['updated'] or 0,
        }

    def _api_key(self):
        with self.hub.db() as db:
            row = db.execute('SELECT api_key FROM voice_settings WHERE id=1').fetchone()
        if not row or not row['api_key']:
            return None
        try:
            return self.hub.cipher.decrypt(row['api_key']).decode()
        except Exception:
            return None

    def configure(self, admin_id, api_key=None, model=None, fmt=None, enabled=None):
        if model is not None and model not in fa.MODELS:
            raise ValueError('TTS 模型不受支持')
        if fmt is not None and fmt not in ('wav','mp3','opus'):
            raise ValueError('音频格式不受支持')
        with self.hub.db() as db:
            cur = db.execute('SELECT * FROM voice_settings WHERE id=1').fetchone()
            blob = cur['api_key'] if cur else None
            if api_key is not None:
                key = api_key.strip()
                blob = self.hub.cipher.encrypt(key.encode()) if key else None
            db.execute('UPDATE voice_settings SET api_key=?,model=?,format=?,enabled=?,updated=?,updated_by=? WHERE id=1',
                       (blob,
                        model if model is not None else (cur['model'] if cur else 's2.1-pro'),
                        fmt if fmt is not None else (cur['format'] if cur else 'wav'),
                        1 if (enabled if enabled is not None else (cur['enabled'] if cur else 0)) else 0,
                        _now(), admin_id))
        return self.settings()

    # -- 音色 --

    def voices(self, user_id=None, include_disabled=False):
        with self.hub.db() as db:
            if include_disabled:
                rows = db.execute('SELECT * FROM voice_voices ORDER BY created').fetchall()
            else:
                rows = db.execute('SELECT * FROM voice_voices WHERE enabled=1 AND reference_id<>"" ORDER BY created').fetchall()
            favs = set()
            if user_id:
                favs = {r['voice_id'] for r in
                        db.execute('SELECT voice_id FROM voice_favorites WHERE user_id=?', (user_id,))}
        return [{
            'id': r['id'], 'name': r['name'], 'reference_id': r['reference_id'],
            'language': r['language'] or '', 'style': r['style'] or '',
            'has_sample': bool(r['sample_path'] or r['official_sample']),
            'official':r['created_by']=='catalog', 'languages':(r['language'] or '').split(','),
            'sample_url': ('/api/voice/voices/%s/sample' % r['id']) if r['sample_path'] or r['official_sample'] else '',
            'enabled': bool(r['enabled']),
            'favorite': r['id'] in favs,
            'usable': bool(r['enabled']) and bool(r['reference_id']),
        } for r in rows]

    def save_voice(self, admin_id, payload, voice_id=None):
        name = (payload.get('name') or '').strip()
        ref = (payload.get('reference_id') or '').strip()
        if not name:
            raise ValueError('音色名称不能为空')
        if len(name) > 60:
            raise ValueError('音色名称最多 60 字')
        if len(ref) > 200:
            raise ValueError('reference_id 过长')
        lang = (payload.get('language') or '').strip()[:35]
        style = (payload.get('style') or '').strip()[:80]
        enabled = 1 if payload.get('enabled', True) else 0
        with self.hub.db() as db:
            if voice_id:
                row = db.execute('SELECT * FROM voice_voices WHERE id=?', (voice_id,)).fetchone()
                if not row:
                    raise ValueError('音色不存在')
                db.execute('UPDATE voice_voices SET name=?,reference_id=?,language=?,style=?,enabled=? WHERE id=?',
                           (name, ref, lang, style, enabled, voice_id))
                return voice_id
            voice_id = secrets.token_hex(8)
            db.execute('''INSERT INTO voice_voices(id,name,reference_id,language,style,sample_path,created,created_by,enabled)
                          VALUES(?,?,?,?,?,?,?,?,?)''',
                       (voice_id, name, ref, lang, style, '', _now(), admin_id, enabled))
        return voice_id

    def delete_voice(self, voice_id):
        with self.hub.db() as db:
            row = db.execute('SELECT sample_path FROM voice_voices WHERE id=?', (voice_id,)).fetchone()
            if not row:
                raise ValueError('音色不存在')
            used = db.execute("SELECT COUNT(*) c FROM voice_jobs WHERE voice_id=? AND state IN ('queued','running')",
                              (voice_id,)).fetchone()['c']
            if used:
                raise ValueError('该音色有进行中的配音任务，暂不能删除')
            db.execute('DELETE FROM voice_voices WHERE id=?', (voice_id,))
            db.execute('DELETE FROM voice_favorites WHERE voice_id=?', (voice_id,))
        if row['sample_path']:
            try:
                (self.samples / row['sample_path']).unlink(missing_ok=True)
            except OSError:
                pass

    def set_sample(self, voice_id, src_path, suffix):
        with self.hub.db() as db:
            row = db.execute('SELECT sample_path FROM voice_voices WHERE id=?', (voice_id,)).fetchone()
            if not row:
                raise ValueError('音色不存在')
        fname = '%s%s' % (secrets.token_hex(6), suffix)
        dst = self.samples / fname
        shutil.copyfile(src_path, dst)
        try:
            _ffprobe_duration(dst)
        except Exception:
            dst.unlink(missing_ok=True)
            raise
        with self.hub.db() as db:
            db.execute('UPDATE voice_voices SET sample_path=? WHERE id=?', (fname, voice_id))
        if row['sample_path']:
            try:
                (self.samples / row['sample_path']).unlink(missing_ok=True)
            except OSError:
                pass
        return fname

    def toggle_favorite(self, user_id, voice_id):
        with self.hub.db() as db:
            if not db.execute('SELECT 1 FROM voice_voices WHERE id=?', (voice_id,)).fetchone():
                raise ValueError('音色不存在')
            exists = db.execute('SELECT 1 FROM voice_favorites WHERE user_id=? AND voice_id=?',
                                (user_id, voice_id)).fetchone()
            if exists:
                db.execute('DELETE FROM voice_favorites WHERE user_id=? AND voice_id=?', (user_id, voice_id))
                return False
            db.execute('INSERT INTO voice_favorites(user_id,voice_id,created) VALUES(?,?,?)',
                       (user_id, voice_id, _now()))
            return True

    # -- 任务 --

    def submit(self, user_id, request_key, payload, admin=False):
        if not isinstance(request_key,str) or not 1<=len(request_key)<=200:raise ValueError('请求标识无效')
        import hashlib
        if not isinstance(payload,dict):raise ValueError('配音参数无效')
        signature=hashlib.sha256(json.dumps({k:v for k,v in payload.items() if k!='request_key'},ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        def same_request(row):
            if not row['input_signature'] or row['input_signature']!=signature:
                raise HTTPException(409,'配音请求标识已对应其他输入或旧任务无法安全匹配，请先核对任务记录；未重新合成')
            return self._job_json(row)
        with self.hub.db() as db:
            existing=db.execute('SELECT * FROM voice_jobs WHERE owner=? AND request_key=?',(user_id,request_key)).fetchone()
        if existing:return same_request(existing)
        s = self.settings()
        if not s['configured']:
            raise HTTPException(503, '管理员尚未配置 Fish Audio API Key，AI 配音不可用')
        if not s['enabled']:
            raise HTTPException(503, 'AI 配音已被管理员停用')

        if s['format']=='pcm':raise ValueError('请先将输出格式改成 WAV；暂不支持裸 PCM')
        workflow={}
        if payload.get('source')=='subtitles':
            with self.hub.db() as db:project=db.execute('SELECT * FROM edit_projects WHERE id=? AND owner=?',(payload.get('project_id'),user_id)).fetchone()
            if not project or project['version']!=payload.get('project_version'):raise ValueError('剪辑已修改，请保存后重试')
            captions=json.loads(project['body']).get('captions',[])
            indexes=payload.get('caption_indices')
            if indexes is not None:
                if not isinstance(indexes,list) or not indexes or any(type(i) is not int or i<0 or i>=len(captions) for i in indexes):raise ValueError('请选择需要配音的字幕')
                captions=[captions[i] for i in sorted(set(indexes))]
            payload=dict(payload,text='\n'.join(c['text'].strip() for c in sorted(captions,key=lambda c:c['start']) if c['text'].strip()),make_captions=False,format='mp3')
        if payload.get('auto_asset') or payload.get('auto_timeline'):
            workflow={'auto_asset':True,'auto_timeline':bool(payload.get('auto_timeline')),'project_version':payload.get('project_version')}
        fmt=payload.get('format',s['format'])
        if fmt not in ('mp3','wav','opus'):raise ValueError('音频格式无效')
        text = payload.get('text')
        voice_id = payload.get('voice_id')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('请填写配音文案')

        with self.hub.db() as db:
            voice = db.execute('SELECT * FROM voice_voices WHERE id=?', (voice_id,)).fetchone()
        if not voice:
            raise ValueError('音色不存在')
        if not voice['enabled'] or not voice['reference_id']:
            raise ValueError('该音色尚未配置真实 reference_id，请联系管理员')

        speed = payload.get('speed', 1.0)
        headers, body = fa.build_request(
            text, voice['reference_id'], s['model'], speed=speed,
            fmt=fmt, language=(voice['language'] or None))
        try:
            duration_hint = float(payload.get('target_duration') or 0)
        except (TypeError, ValueError):
            duration_hint = 0.0

        insert_at = payload.get('insert_at', 0.0)
        try:
            insert_at = max(0.0, float(insert_at))
        except (TypeError, ValueError):
            raise ValueError('插入位置无效') from None

        if not math.isfinite(insert_at) or insert_at<0:raise ValueError('插入位置无效')
        jid = secrets.token_hex(12)
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # 幂等：同一 (owner, request_key) 只产生一条
            exist = db.execute('SELECT * FROM voice_jobs WHERE owner=? AND request_key=?',
                               (user_id, str(request_key or ''))).fetchone()
            if exist:
                return same_request(exist)
            if db.execute("SELECT COUNT(*) FROM voice_jobs WHERE owner=? AND state IN ('queued','running')",(user_id,)).fetchone()[0]>=10:raise ValueError('最多同时排队 10 条配音')
            pid=str(payload.get('project_id') or '')
            if pid and not db.execute('SELECT id FROM edit_projects WHERE id=? AND owner=?',(pid,user_id)).fetchone():raise ValueError('剪辑项目不存在或无权使用')
            db.execute('''INSERT INTO voice_jobs
                (id,owner,request_key,text,display_text,voice_id,reference_id,model,fmt,speed,
                 insert_at,make_captions,project_id,state,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (jid, user_id, str(request_key or ''), text, text,
                        voice_id, voice['reference_id'], s['model'], fmt, float(speed),
                        insert_at, 1 if payload.get('make_captions', True) else 0,
                        str(payload.get('project_id') or ''), 'queued', _now(), _now()))
            db.execute('UPDATE voice_jobs SET input_signature=?,language=? WHERE id=?',(signature,voice['language'] or '',jid))
            if workflow:db.execute("UPDATE voice_jobs SET workflow=?,completion_state='pending' WHERE id=?",(json.dumps(workflow),jid))
            row = db.execute('SELECT * FROM voice_jobs WHERE id=?', (jid,)).fetchone()
            self.hub.log(db, user_id, 'voice_submit', jid)
        self.wake.set()
        return self._job_json(row)

    def _job_json(self, row):
        try:
            captions = json.loads(row['captions'] or '[]')
        except json.JSONDecodeError:
            captions = []
        try:
            warnings = json.loads(row['warnings'] or '[]')
        except json.JSONDecodeError:
            warnings = []
        return {
            'asset_id':row['asset_id'],'timeline_status':row['timeline_status'],'workflow_error':row['workflow_error'],'completion_state':row['completion_state'],'format':row['fmt'],'project_version':json.loads(row['workflow'] or '{}').get('project_version'),'project_id':row['project_id'], 'id': row['id'], 'state': row['state'], 'error': row['error'] or '',
            'duration': row['duration'] or 0.0,
            'audio_url': ('/api/voice/jobs/%s/audio' % row['id']) if row['audio_path'] else '',
            'captions': captions, 'warnings': warnings,
            'insert_at': row['insert_at'] or 0.0,
            'voice_id': row['voice_id'], 'model': row['model'],
            'text': row['text'], 'created': row['created'], 'updated': row['updated'],
        }

    def job(self, user_id, admin, job_id):
        with self.hub.db() as db:
            row = db.execute('SELECT * FROM voice_jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise ValueError('配音任务不存在')
        if row['owner'] != user_id:
            raise ValueError('无权查看该配音任务')
        return self._job_json(row)

    def jobs(self, user_id, admin, limit=20):
        with self.hub.db() as db:
            rows = db.execute('SELECT * FROM voice_jobs WHERE owner=? ORDER BY created DESC LIMIT ?', (user_id, limit)).fetchall()
        return [self._job_json(r) for r in rows]

    # -- 调度 --

    def loop(self):
        while not self.hub.stop.is_set():
            try:
                self.tick()
            except Exception:
                pass
            self.wake.wait(2)
            self.wake.clear()

    def recover(self):
        """进程重启：把 running 标为 failed（上游可能已计费，绝不自动重提）。"""
        with self.hub.db() as db:
            db.execute("UPDATE voice_jobs SET state='failed',error=?,updated=? WHERE state='running'",
                       ('服务重启导致配音中断，请重新生成（可能已消耗额度）', _now()))

    def tick(self):
        with self.hub.db() as db:ready=db.execute("SELECT id FROM voice_jobs WHERE state='ready' AND completion_state='pending' LIMIT 1").fetchone()
        if ready:
            from voice_completion import finish
            finish(self,ready['id'])
        if not self.settings()['enabled']:return
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT j.*,u.enabled uenabled FROM voice_jobs j JOIN users u ON u.id=j.owner "
                             "WHERE j.state='queued' ORDER BY j.created LIMIT 1").fetchone()
            if not row:
                return
            db.execute("UPDATE voice_jobs SET state='running',updated=? WHERE id=?", (_now(), row['id']))
        try:
            if not row['uenabled']:
                raise ValueError('成员账号已停用')
            self._run(row['id'])
        except fa.StreamError as exc:
            self._fail(row['id'], str(exc))
        except ValueError as exc:
            self._fail(row['id'], str(exc))
        except PermissionError:
            self._fail(row['id'], '配音文件无法保存：服务器音频目录写入权限不足；请管理员修复，不要重复提交。')
        except Exception as exc:
            self._fail(row['id'], '配音处理失败（'+type(exc).__name__+'），未自动重试；请管理员检查音频处理与服务器连接。')

    def _fail(self, job_id, message):
        with self.hub.db() as db:
            db.execute('UPDATE voice_jobs SET state=?,error=?,updated=? WHERE id=?',
                       ('failed', message[:300], _now(), job_id))

    def _run(self, job_id):
        s = self.settings()
        if not s['enabled']:raise ValueError('AI 配音已停用')
        key = self._api_key()
        if not key:
            raise ValueError('管理员尚未配置 API Key')
        with self.hub.db() as db:
            job = db.execute('SELECT * FROM voice_jobs WHERE id=?', (job_id,)).fetchone()
        if not job:
            return

        parts=fa.split_text(job['text'])
        if len(parts)>1:
            return self._run_long(job, key, parts)
        collector=self._collect(job,key,job['text'])

        # 落盘 + 校验
        tmp = self.files / ('%s.tmp' % job_id)
        tmp.write_bytes(bytes(collector.audio))
        try:
            duration = _ffprobe_duration(tmp)
            from editor import run
            run([shutil.which('ffmpeg'),'-v','error','-xerror','-i',str(tmp),'-map','0:a:0','-f','null','-'],timeout=60)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

        ext = '.wav' if job['fmt'] == 'wav' else ('.mp3' if job['fmt'] == 'mp3' else '.pcm' if job['fmt'] == 'pcm' else '.opus')
        final = self.files / (job_id + ext)
        os.replace(tmp, final)

        captions = []
        warnings = list(collector.warnings)
        if job['make_captions']:
            if collector.has_alignment():
                captions = fa.group_into_captions(collector.timeline())
                captions = [dict(c,start=max(0,c['start']),end=min(duration,c['end'])) for c in captions
                            if min(duration,c['end'])>max(0,c['start'])]
            else:
                warnings.append('上游未返回同步时间戳，本条配音没有自动字幕，请手动添加')
        with self.hub.db() as db:
            db.execute('''UPDATE voice_jobs SET state='ready',audio_path=?,duration=?,
                          captions=?,warnings=?,updated=? WHERE id=?''',
                       (final.name, duration, json.dumps(captions, ensure_ascii=False),
                        json.dumps(warnings, ensure_ascii=False), _now(), job_id))

    def _collect(self, job, key, text):
        headers, body = fa.build_request(
            text, job['reference_id'], job['model'],
            speed=job['speed'], fmt=job['fmt'], language=(job['language'] or None))
        headers['Authorization'] = 'Bearer ' + key
        payload = json.dumps(body).encode()

        collector = fa.StreamCollector()
        req = urllib.request.Request(fa.STREAM_URL, data=payload, headers=headers, method='POST')
        timeout = float(os.getenv('HUB_VOICE_TIMEOUT', '180'))
        try:
            with __import__('voice_catalog').opener().open(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise ValueError('上游返回 HTTP %d' % resp.status)
                for data in fa.iter_sse_events(_read_blocks(resp, 65536, timeout)):
                    collector.feed_event(data)
        except urllib.error.HTTPError as exc:
            # Raw provider/proxy bodies may contain credentials. Do not read,
            # log or persist them, even a truncated excerpt.
            code=exc.code
            exc.close()
            diagnosis={400:'请求参数被拒绝',401:'服务凭据无效，请联系管理员',402:'服务额度不足',403:'服务权限不足',429:'服务请求限流'}.get(code,'服务暂时不可用')
            raise ValueError('配音上游 HTTP %d：%s；未自动重试，请先核对原任务与用量' % (code,diagnosis)) from None
        except urllib.error.URLError as exc:
            import socket, ssl
            reason=exc.reason
            if isinstance(reason,ssl.SSLCertVerificationError):
                detail='TLS 证书验证失败，请检查服务器代理和证书'
            elif isinstance(reason,(TimeoutError,socket.timeout)):
                detail='连接上游超时'
            elif isinstance(reason,socket.gaierror):
                detail='上游域名解析失败'
            elif isinstance(reason,ConnectionRefusedError):
                detail='连接被拒绝，请检查服务器代理是否运行'
            elif isinstance(reason,(ConnectionResetError,ConnectionAbortedError)):
                detail='上游或代理中断了连接'
            else:
                detail='连接上游失败（%s%s）' % (type(reason).__name__,
                    ', errno=%s'%reason.errno if isinstance(reason,OSError) and reason.errno is not None else '')
            raise ValueError(detail+'；未自动重试，请先核对上游用量后再提交') from None
        except TimeoutError:
            raise ValueError('上游超时（未自动重试，避免重复计费）') from None

        if not collector.audio:
            raise ValueError('上游没有返回音频数据')

        return collector

    def _run_long(self, job, key, parts):
        import tempfile
        from editor import run
        captions=[];warnings=[];offset=0.0
        with tempfile.TemporaryDirectory(prefix='speech-',dir=self.files) as folder:
            folder=Path(folder);files=[]
            for index,text in enumerate(parts):
                try:
                    collector=self._collect(job,key,text)
                    path=folder/('part-%06d.wav'%index)
                    raw=folder/('raw-%06d'%index)
                    raw.write_bytes(bytes(collector.audio))
                    run([shutil.which('ffmpeg'),'-v','error','-xerror','-y','-i',str(raw),'-vn','-ar','44100','-ac','1','-c:a','pcm_s16le',str(path)],timeout=180)
                    duration=_ffprobe_duration(path)
                except Exception as exc:
                    raise ValueError('第 %d/%d 段失败，未发布不完整音频；已完成段可能已计费。%s'%(index+1,len(parts),str(exc))) from None
                files.append(path)
                warnings.extend(collector.warnings)
                if job['make_captions']:
                    if collector.has_alignment():
                        captions.extend(dict(c,start=offset+max(0,c['start']),end=offset+min(duration,c['end'])) for c in fa.group_into_captions(collector.timeline()) if min(duration,c['end'])>max(0,c['start']))
                    else:
                        warnings.append('第 %d 段缺少同步字幕时间戳'%(index+1))
                offset+=duration
            manifest=folder/'concat.txt'
            manifest.write_text(''.join("file '%s'\n"%p.name for p in files),encoding='utf-8')
            ext={'mp3':'.mp3','wav':'.wav','opus':'.opus'}[job['fmt']]
            merged=folder/('complete'+ext)
            run([shutil.which('ffmpeg'),'-v','error','-y','-f','concat','-safe','1','-i',str(manifest),str(merged)],timeout=max(180,offset))
            duration=_ffprobe_duration(merged)
            if abs(duration-offset)>max(1,len(parts)*.1):
                raise ValueError('合并音频时长不完整，未发布结果')
            final=self.files/(job['id']+ext)
            os.replace(merged,final)
        with self.hub.db() as db:
            db.execute("UPDATE voice_jobs SET state='ready',audio_path=?,duration=?,captions=?,warnings=?,updated=? WHERE id=?",
                (final.name,duration,json.dumps(captions,ensure_ascii=False),json.dumps(warnings,ensure_ascii=False),_now(),job['id']))

    # -- 路由挂载 --

    def attach(self, app, current):
        voice = self
        router=APIRouter(route_class=VoiceRoute)

        @router.get('/api/voice/config')
        def get_config(request: Request):
            user = current(request)
            return {'ok': True, 'config': voice.settings(), 'admin': user['role'] == 'admin'}

        @router.post('/api/voice/config')
        async def set_config(request: Request):
            user = current(request)
            if user['role'] != 'admin':
                raise HTTPException(403, '只有管理员可以配置')
            payload = await request.json()
            return {'ok': True, 'config': voice.configure(
                user['id'], api_key=payload.get('api_key'),
                model=payload.get('model'), fmt=payload.get('format'),
                enabled=payload.get('enabled'))}

        @router.get('/api/voice/catalog')
        def catalog(request:Request,title:str='',language:str='',page:int=1,refresh:bool=False):
            from voice_catalog import browse
            user=current(request)
            return dict(ok=True,**browse(voice,user['id'],title,language,page,refresh))

        @router.get('/api/voice/voices')
        def list_voices(request: Request):
            user = current(request)
            return {'ok': True, 'voices': voice.voices(user['id'], include_disabled=user['role'] == 'admin'),
                    'admin': user['role'] == 'admin'}

        @router.get('/api/voice/voices/{vid}/sample')
        def get_sample(vid: str, request: Request):
            current(request)
            with voice.hub.db() as db:
                row = db.execute('SELECT sample_path,official_sample FROM voice_voices WHERE id=?', (vid,)).fetchone()
            if not row:raise HTTPException(404, '该音色暂无试听')
            if not row['sample_path'] and row['official_sample']:
                from voice_catalog import fetch_sample
                from fastapi.responses import Response
                try:body,mime=fetch_sample(row['official_sample'])
                except ValueError as exc:raise HTTPException(502,str(exc)) from None
                return Response(body,media_type=mime,headers={'Cache-Control':'private, max-age=3600'})
            if not row['sample_path']:raise HTTPException(404, '该音色暂无试听')
            path = voice.samples / row['sample_path']
            if not path.is_file():
                raise HTTPException(404, '示例音频文件缺失')
            return FileResponse(path)

        @router.post('/api/voice/voices/{vid}/sample')
        async def upload_sample(vid: str, request: Request):
            user = current(request)
            if user['role'] != 'admin':
                raise HTTPException(403, '只有管理员可以维护音色')
            form = await request.form()
            upload = form.get('file')
            if upload is None or not getattr(upload, 'filename', ''):
                raise HTTPException(400, '请选择示例音频文件')
            suffix = os.path.splitext(upload.filename)[1].lower()
            if suffix not in ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.opus', '.flac'):
                raise HTTPException(400, '示例音频仅支持 mp3/wav/m4a/aac/ogg/opus/flac')
            tmpdir = voice.root / 'tmp'
            tmpdir.mkdir(exist_ok=True)
            tmp = tmpdir / (secrets.token_hex(8) + suffix)
            size = 0
            with tmp.open('wb') as fh:
                while True:
                    block = await upload.read(1 << 20)
                    if not block:
                        break
                    size += len(block)
                    if size > 25 * 1024 * 1024:
                        fh.close()
                        tmp.unlink(missing_ok=True)
                        raise HTTPException(400, '示例音频不能超过 25MB（中台限制）')
                    fh.write(block)
            try:
                voice.set_sample(vid, tmp, suffix)
            finally:
                tmp.unlink(missing_ok=True)
            return {'ok': True}
        @router.post('/api/voice/voices')
        async def create_voice(request: Request):
            user = current(request)
            if user['role'] != 'admin':                raise HTTPException(403, '只有管理员可以维护音色')
            payload = await request.json()
            vid = voice.save_voice(user['id'], payload)
            return {'ok': True, 'id': vid}

        @router.put('/api/voice/voices/{vid}')
        async def update_voice(vid: str, request: Request):
            user = current(request)
            if user['role'] != 'admin':
                raise HTTPException(403, '只有管理员可以维护音色')
            payload = await request.json()
            voice.save_voice(user['id'], payload, voice_id=vid)
            return {'ok': True}

        @router.delete('/api/voice/voices/{vid}')
        def remove_voice(vid: str, request: Request):
            user = current(request)
            if user['role'] != 'admin':
                raise HTTPException(403, '只有管理员可以维护音色')
            voice.delete_voice(vid)
            return {'ok': True}

        @router.post('/api/voice/voices/{vid}/favorite')
        def favorite(vid: str, request: Request):
            user = current(request)
            state = voice.toggle_favorite(user['id'], vid)
            return {'ok': True, 'favorite': state}

        @router.post('/api/voice/jobs')
        async def create_job(request: Request):
            user = current(request)
            payload = await request.json()
            key = str(payload.get('request_key') or '')
            if not key:
                raise HTTPException(400, '缺少请求标识')
            return {'ok': True, 'job': voice.submit(user['id'], key, payload,
                                                    admin=user['role'] == 'admin')}

        @router.get('/api/voice/jobs')
        def list_jobs(request: Request, limit: int = 20):
            user = current(request)
            return {'ok': True, 'jobs': voice.jobs(user['id'], user['role'] == 'admin',
                                                   limit=max(1, min(50, limit)))}

        @router.get('/api/voice/request-status')
        def request_status(request:Request,request_key:str):
            user=current(request)
            if not 1<=len(request_key)<=200:raise HTTPException(400,'请求标识无效')
            with voice.hub.db() as db:row=db.execute('SELECT * FROM voice_jobs WHERE owner=? AND request_key=?',(user['id'],request_key)).fetchone()
            return {'found':bool(row),'job':voice._job_json(row) if row else None}

        @router.get('/api/voice/jobs/{jid}')
        def get_job(jid: str, request: Request):
            user = current(request)
            return {'ok': True, 'job': voice.job(user['id'], user['role'] == 'admin', jid)}

        @router.get('/api/voice/jobs/{jid}/audio')
        def get_audio(jid: str, request: Request):
            user = current(request)
            with voice.hub.db() as db:
                row = db.execute('SELECT * FROM voice_jobs WHERE id=?', (jid,)).fetchone()
            if not row or row['owner'] != user['id']:
                raise HTTPException(404, '配音不存在')
            if row['state']!='ready' or not row['audio_path']:
                raise HTTPException(404, '音频尚未生成')
            path = voice.files / row['audio_path']
            if not path.is_file():
                raise HTTPException(404, '音频文件缺失')
            return FileResponse(path)

        @router.post('/api/voice/jobs/{jid}/asset')
        def save_asset(jid: str, request: Request):
            from voice_completion import save_asset as store
            user=current(request)
            return {'ok':True,'asset_id':store(voice,user['id'],jid)}

        app.include_router(router)


def _read_blocks(resp, size, timeout=180):
    """逐块读取响应体，供 SSE 增量解析。"""
    started=time.monotonic();received=0
    while True:
        if time.monotonic()-started>timeout:raise TimeoutError()
        block = resp.read(size)
        received+=len(block)
        if received>100*1024*1024:raise ValueError('音频响应超过 100MB 限制')
        if not block:
            return
        yield block
