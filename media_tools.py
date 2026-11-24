"""Local reference extraction. Never calls a generation provider."""
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import threading
import time
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from editor import probe, number, run


def attach(app, hub, user, body):
    slots=threading.BoundedSemaphore(2)
    with hub.db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS derived_assets(
            asset_id TEXT PRIMARY KEY, owner TEXT NOT NULL, source_task TEXT NOT NULL,
            kind TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL, created REAL NOT NULL)''')

    def source_info(u, tid):
        path=app.state.editor.source(u['id'],u['role']=='admin',tid)
        duration,streams=probe(path)
        with hub.db() as db:
            row=db.execute('SELECT prompt,config FROM tasks WHERE id=?',(tid,)).fetchone()
            config=json.loads(row['config'] or '{}') if row else {};assets=[]
            for a in config.get('assets',[]):
                stored=db.execute('SELECT id,name,mime,size FROM assets WHERE id=? AND owner=?',(a.get('id'),u['id'])).fetchone()
                if stored and (hub.assets/stored['id']).is_file():assets.append(dict(stored))
        return {'id':tid,'duration':duration,'has_audio':any(s['codec_type']=='audio' for s in streams),
                'prompt':row['prompt'] if row else '', 'assets':assets}

    @app.get('/api/media/source/{tid}')
    def info(tid: str, request: Request):
        u=user(request)
        try:return source_info(u,tid)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None

    def extract(u,data):
        tid=str(data.get('source_id',''));kind=data.get('kind')
        if kind not in ('frame','audio'):raise ValueError('请选择画面或原声提取')
        source=app.state.editor.source(u['id'],u['role']=='admin',tid)
        duration,streams=probe(source)
        if kind=='frame':
            start=number(data.get('time',max(0,duration-.2)),0,duration)
            start=round(min(start,max(0,duration-.05)),4);end=start
            extension='.png';mime='image/png'
        else:
            if not any(s['codec_type']=='audio' for s in streams):raise ValueError('这段视频没有原声音轨，可另外上传人物声音参考')
            start=round(number(data.get('start',0),0,duration),4)
            end=round(number(data.get('end',min(duration,start+15)),start,duration),4)
            if not .1<=end-start<=15.2:raise ValueError('每段原声提取长度为 0.1–15 秒；生成声音参考至少需要 2 秒')
            extension='.wav';mime='audio/wav'
        with hub.db() as db:
            cached=db.execute('''SELECT a.id,a.name,a.mime,a.size FROM derived_assets d JOIN assets a ON a.id=d.asset_id
                WHERE d.owner=? AND d.source_task=? AND d.kind=? AND d.start=? AND d.end=?''',(u['id'],tid,kind,start,end)).fetchone()
        if cached and (hub.assets/cached['id']).is_file():
            return {**dict(cached),'source_id':tid,'start':start,'end':end,'kind':kind}
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:raise ValueError('执行机未找到 FFmpeg，请联系管理员')
        if not slots.acquire(blocking=False):raise HTTPException(409,'本机正在处理其他素材，请稍后重试')
        try:
            with tempfile.TemporaryDirectory(prefix='extract-',dir=app.state.editor.root) as tmp:
                output=Path(tmp)/('reference'+extension)
                args=[ffmpeg,'-hide_banner','-loglevel','error','-y','-ss',str(start),'-i',str(source)]
                if kind=='frame':args+=['-map','0:v:0','-frames:v','1','-vf','scale=1280:1280:force_original_aspect_ratio=decrease','-threads','1',str(output)]
                else:args+=['-map','0:a:0','-vn','-t',str(end-start),'-ar','44100','-ac','2','-c:a','pcm_s16le',str(output)]
                run(args,timeout=90)
                if not output.is_file() or output.stat().st_size==0:raise ValueError('该位置未提取到素材，请换一个时间点重试')
                if kind=='audio':
                    actual,_=probe(output)
                    if abs(actual-(end-start))>.2:raise ValueError('提取原声时长不一致，请重试')
                aid=secrets.token_hex(16);name=('参考帧' if kind=='frame' else '原声')+f'-{tid[:8]}-{start:.2f}'+extension
                target=hub.assets/aid;shutil.copyfile(output,target)
                try:
                    with hub.db() as db:
                        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(aid,u['id'],name,mime,target.stat().st_size,time.time()))
                        db.execute('INSERT INTO derived_assets VALUES(?,?,?,?,?,?,?)',(aid,u['id'],tid,kind,start,end,time.time()))
                except Exception:
                    target.unlink(missing_ok=True);raise
            return {'id':aid,'name':name,'mime':mime,'size':target.stat().st_size,'source_id':tid,'start':start,'end':end,'kind':kind}
        finally:slots.release()

    @app.post('/api/media/extract')
    async def extract_reference(request: Request):
        u=user(request);data=await body(request)
        try:return await run_in_threadpool(extract,u,data)
        except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc)) from None

    vocal_slots=threading.BoundedSemaphore(1)

    def demucs_python():
        configured=os.environ.get('HUB_DEMUCS_PYTHON','').strip()
        candidates=[configured] if configured else []
        separation_root=Path(__file__).resolve().parents[3]/'vocal-separation-test'
        # Demucs selects CUDA automatically when the GPU runtime is available; retain CPU environment as fallback.
        candidates.extend(str(separation_root/env/'Scripts'/'python.exe') for env in ('.venv-gpu','.venv'))
        for candidate in candidates:
            if candidate and Path(candidate).is_file():return Path(candidate)
        raise ValueError('本机没有可用的 Demucs 运行环境，请先安装人声分离环境或设置 HUB_DEMUCS_PYTHON')

    def separate(u,data):
        tid=str(data.get('source_id',''))
        source=app.state.editor.source(u['id'],u['role']=='admin',tid)
        duration,streams=probe(source)
        if not any(s['codec_type']=='audio' for s in streams):raise ValueError('这段视频没有音轨，无法分离人声')
        start=round(number(data.get('start',0),0,duration),4)
        end=round(number(data.get('end',min(duration,start+12)),start,duration),4)
        if not 1<=round(end-start,4)<=60:raise ValueError('声音分离片段需为 1–60 秒')
        kind=str(data.get('kind','vocal'))
        if kind not in ('vocal','background'):raise ValueError('请选择人声或背景声音')
        with hub.db() as db:
            cached=db.execute('''SELECT a.id,a.name,a.mime,a.size FROM derived_assets d JOIN assets a ON a.id=d.asset_id
                WHERE d.owner=? AND d.source_task=? AND d.kind=? AND d.start=? AND d.end=?''',(u['id'],tid,kind,start,end)).fetchone()
        if cached and (hub.assets/cached['id']).is_file():
            return {**dict(cached),'source_id':tid,'start':start,'end':end,'kind':kind}
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:raise ValueError('执行机未找到 FFmpeg，请联系管理员')
        python=demucs_python()
        if not vocal_slots.acquire(blocking=False):raise HTTPException(409,'本机正在处理另一段人声分离，请稍后重试')
        try:
            with tempfile.TemporaryDirectory(prefix='vocals-',dir=app.state.editor.root) as tmp:
                raw=Path(tmp)/'input.wav'
                run([ffmpeg,'-hide_banner','-loglevel','error','-y','-ss',str(start),'-i',str(source),'-map','0:a:0','-vn','-t',str(end-start),'-ar','44100','-ac','2','-c:a','pcm_s16le',str(raw)],timeout=120)
                stems=Path(tmp)/'stems'
                environment={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1','OMP_NUM_THREADS':'2'}
                run([str(python),'-m','demucs.separate','--two-stems','vocals','-n','htdemucs','--shifts','0','-o',str(stems),str(raw)],timeout=900,env=environment)
                vocal=stems/'htdemucs'/'input'/('vocals.wav' if kind=='vocal' else 'no_vocals.wav')
                if not vocal.is_file():raise ValueError('声音分离没有生成结果，请重试或换一段视频')
                output=Path(tmp)/'result.wav'
                run([ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(vocal),'-ar','44100','-ac','2','-c:a','pcm_s16le',str(output)],timeout=120)
                actual,_=probe(output)
                if abs(actual-(end-start))>.2:raise ValueError('声音分离结果时长不一致，请重试')
                aid=secrets.token_hex(16);name=f"{'人声' if kind=='vocal' else '背景声'}-{tid[:8]}-{start:.2f}.wav";mime='audio/wav'
                target=hub.assets/aid;shutil.copyfile(output,target)
                try:
                    with hub.db() as db:
                        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(aid,u['id'],name,mime,target.stat().st_size,time.time()))
                        db.execute('INSERT INTO derived_assets VALUES(?,?,?,?,?,?,?)',(aid,u['id'],tid,kind,start,end,time.time()))
                except Exception:
                    target.unlink(missing_ok=True);raise
            return {'id':aid,'name':name,'mime':mime,'size':target.stat().st_size,'source_id':tid,'start':start,'end':end,'kind':kind}
        finally:vocal_slots.release()

    @app.post('/api/media/vocals')
    async def separate_vocals(request: Request):
        u=user(request);data=await body(request)
        try:return await run_in_threadpool(separate,u,data)
        except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc)) from None
