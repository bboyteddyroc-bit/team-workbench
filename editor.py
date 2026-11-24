"""Local, owner-scoped editing projects and a single FFmpeg export queue."""
import contextlib
import array
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
import asr
import editor_media_cache


@contextlib.contextmanager
def render_directory(root):
    path=Path(root)/('render-'+secrets.token_hex(16))
    try:path.mkdir()
    except OSError:raise ValueError('无法创建导出工作目录，请管理员检查服务器目录写入权限') from None
    try:yield str(path)
    finally:shutil.rmtree(path,ignore_errors=True)


def run(args, cwd=None, timeout=900, env=None):
    try:
        result=subprocess.run(args,cwd=cwd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError('媒体处理超时或工具不可用，请缩短项目后重试') from None
    if result.returncode:raise ValueError('媒体处理失败，请检查文件是否可播放或减少片段后重试')
    return result.stdout


def probe(path):
    try:return editor_media_cache.metadata(path,_probe_uncached)
    except OSError:raise ValueError("原素材文件不可用") from None


def _probe_uncached(path):
    tool=shutil.which('ffprobe')
    if not tool:raise ValueError('执行机未找到 FFprobe，请联系管理员')
    data=json.loads(run([tool,'-v','error','-show_format','-show_streams','-of','json',str(path)],timeout=30))
    duration=float(data.get('format',{}).get('duration',0))
    if not math.isfinite(duration) or duration<=0:raise ValueError('无法读取素材时长')
    return duration,data.get('streams',[])


def readable(path,limit=1<<20):
    """Read head and tail so a file that stats but cannot be opened fails before we stream it."""
    try:
        with open(path,'rb') as handle:
            handle.read(limit)
            size=os.fstat(handle.fileno()).st_size
            if size>limit:
                handle.seek(size-limit);handle.read(limit)
        return True
    except OSError:
        return False


def ensure_shared(path):
    """A LAN worker may run as another Windows account; restore inherited ACLs so the editor can stream it."""
    if os.name!='nt':return False
    tool=shutil.which('icacls')
    if not tool:return False
    try:
        subprocess.run([tool,str(path),'/inheritance:e'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired):
        return False
    return True


def verify_export(root,job_id):
    path=root/(job_id+'.mp4')
    try:size=path.stat().st_size
    except OSError:raise ValueError('导出成品没有生成，请重试') from None
    if size<=0:raise ValueError('导出成品为空，请重试')
    if not readable(path):
        ensure_shared(path)
        if not readable(path):raise ValueError('导出成品无法读取（导出进程与预览账户不同或文件权限异常），请重新导出；若反复出现请联系管理员')
    _,streams=probe(path)
    if not any(stream.get('codec_type')=='video' for stream in streams):raise ValueError('导出成品缺少视频轨，请重试')


def number(value, low, high):
    if isinstance(value,bool):raise ValueError('时间或音量有误')
    result=float(value)
    if not math.isfinite(result) or not low<=result<=high:raise ValueError('时间或音量超出范围')
    return result


def clip_speed(clip):
    speed=clip.get('speed',1)
    if isinstance(speed,bool):raise ValueError('变速倍率无效')
    speed=float(speed)
    if not math.isfinite(speed) or not .25<=speed<=4:raise ValueError('变速范围 0.25–4 倍')
    return round(speed,3)


def atempo_chain(speed):
    """FFmpeg atempo accepts 0.5–2 per filter; chain filters for wider ratios."""
    if abs(speed-1)<1e-6:return ''
    parts=[];value=speed
    while value>2+1e-9:parts.append('atempo=2');value/=2
    while value<.5-1e-9:parts.append('atempo=0.5');value/=0.5
    if abs(value-1)>1e-6:parts.append(f'atempo={value:.6f}')
    return ','.join(parts)



def record_version(db, pid):
    db.execute('''INSERT OR IGNORE INTO edit_versions(project_id,version,title,body,created)
        SELECT id,version,title,body,updated FROM edit_projects WHERE id=?''',(pid,))


class Editor:
    def __init__(self,hub):
        self.hub=hub;self.root=hub.directory/'edits';self.root.mkdir(exist_ok=True)
        self.footage=hub.directory/'edit_footage';self.footage.mkdir(exist_ok=True)
        with hub.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS edit_projects(id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,version INTEGER NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS edit_exports(id TEXT PRIMARY KEY,owner TEXT NOT NULL,project_id TEXT NOT NULL,body TEXT NOT NULL,state TEXT NOT NULL,error TEXT DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL,request_key TEXT NOT NULL,UNIQUE(owner,request_key));''')
            db.execute('''CREATE TABLE IF NOT EXISTS edit_versions(project_id TEXT NOT NULL,version INTEGER NOT NULL,
                title TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(project_id,version))''')
            db.execute('CREATE TABLE IF NOT EXISTS edit_export_requests(owner TEXT NOT NULL,request_key TEXT NOT NULL,project_id TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(owner,request_key))')
            db.execute('''INSERT OR IGNORE INTO edit_versions SELECT id,version,title,body,updated FROM edit_projects''')
            db.execute('''CREATE TABLE IF NOT EXISTS edit_footage(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,size INTEGER NOT NULL,duration REAL NOT NULL,created REAL NOT NULL)''')

        from editor_proxy_service import PreviewProxies
        self.proxies=PreviewProxies(self,_probe_uncached)

    def footage_path(self,row):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        day=datetime.fromtimestamp(row['created'],ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        dated=self.footage/day/row['id']
        return dated if dated.is_file() else self.footage/row['id']

    def source(self,owner,admin,task_id):
        with self.hub.db() as db:
            row=db.execute('SELECT t.*,a.scope FROM tasks t JOIN accounts a ON a.id=t.account_id WHERE t.id=?',(str(task_id),)).fetchone()
        if not row:
            with self.hub.db() as db:
                footage=db.execute('SELECT id,created FROM edit_footage WHERE id=? AND owner=?',(str(task_id),owner)).fetchone()
            if footage:
                path=self.footage_path(footage)
                if path.is_file():return path
                raise ValueError('实拍视频文件不可用')
            with self.hub.db() as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='libtv_jobs'").fetchone()
                remote=db.execute("SELECT asset_id FROM libtv_jobs WHERE id=? AND owner=? AND state='ready'",(str(task_id),owner)).fetchone() if exists else None
            if remote:
                path=self.hub.assets/remote['asset_id']
                if path.is_file():return path
        if not row or row['state']!='ready' or row['owner']!=owner and not (admin and row['scope']=='shared'):raise ValueError('视频不存在或无权使用')
        path=self.hub.media/(row['id']+'.mp4')
        if not path.is_file():raise ValueError('原视频文件不可用')
        return path

    def audio_source(self,owner,admin,clip):
        kind=clip.get('source','video')
        if kind=='video':return self.source(owner,admin,clip.get('task_id',''))
        if kind=='voice':
            with self.hub.db() as db:
                row=db.execute("SELECT * FROM voice_jobs WHERE id=? AND owner=? AND state='ready'",(clip.get('voice_job_id',''),owner)).fetchone()
            if not row or not row['audio_path']:raise ValueError('配音不存在、未完成或无权使用')
            base=self.hub.directory/'voice'/'audio';path=(base/row['audio_path']).resolve()
            if path.parent!=base.resolve() or not path.is_file():raise ValueError('配音文件不可用')
            return path
        if kind=='asset':
            with self.hub.db() as db:
                row=db.execute('SELECT * FROM assets WHERE id=? AND owner=?',(clip.get('asset_id',''),owner)).fetchone()
            if not row or not row['mime'].startswith('audio/'):raise ValueError('音频素材不存在或无权使用')
            path=self.hub.assets/row['id']
            if not path.is_file():raise ValueError('音频素材文件不可用')
            return path
        raise ValueError('音频来源无效')

    def validate(self,data,owner,admin=False):
        clips=data.get('clips',[]);captions=data.get('captions',[])
        if not isinstance(clips,list) or len(clips)>50 or not isinstance(captions,list) or len(captions)>600:raise ValueError('最多 50 个片段、600 条字幕')
        ratio=data.get('ratio','9:16')
        if ratio not in ('9:16','16:9','1:1'):raise ValueError('画幅无效')
        result={'clips':[],'captions':[],'ratio':ratio,'audio':None,
                'target_duration':number(data.get('target_duration',30),1,3600)};total=0;durations={}
        for clip in clips:
            task=str(clip.get('task_id',''))
            if task not in durations:
                duration,streams=probe(self.source(owner,admin,task))
                if not any(s['codec_type']=='video' for s in streams):raise ValueError('素材没有视频画面')
                durations[task]=duration
            start=number(clip.get('start',0),0,durations[task]);end=number(clip.get('end',durations[task]),0,durations[task]+.05)
            if end-start<.1:raise ValueError('每个片段至少保留 0.1 秒')
            end=min(end,durations[task]);speed=clip_speed(clip);total+=(end-start)/speed
            from color_adjust import validate as validate_color
            result['clips'].append(dict(task_id=task,start=start,end=end,volume=number(clip.get('volume',1),0,2),speed=speed,color=validate_color(clip.get('color'))))
        for caption in captions:
            text=str(caption.get('text','')).strip()
            if not text:raise ValueError('字幕内容不能为空')
            start=number(caption.get('start',0),0,float('inf'));end=number(caption.get('end',total),0,float('inf'))
            if end<=start:raise ValueError('字幕结束时间应晚于开始时间')
            font=caption.get('font','default')
            if font not in subtitle_fonts():raise ValueError('字幕字体无效')
            extra={}
            if caption.get('voice_job_id'):extra['voice_job_id']=str(caption['voice_job_id'])
            source=str(caption.get('source_text','') or '').strip()
            if source:
                if len(source)>300:raise ValueError('字幕原文过长，请缩短后重试')
                extra['source_text']=source
            lang=str(caption.get('lang','') or '').strip()
            if lang:
                if lang not in asr.LANGUAGES:raise ValueError('字幕语种无效')
                extra['lang']=lang
            words=caption_words(caption,text,end-start)
            if words:extra['words']=words
            result['captions'].append(dict(text=text,start=start,end=end,font=font,anim=caption_anim(caption),**caption_style(caption),**extra))
        if data.get('audio'):
            audio=data['audio'];asset=str(audio.get('asset_id',''))
            with self.hub.db() as db:row=db.execute('SELECT * FROM assets WHERE id=? AND owner=?',(asset,owner)).fetchone()
            if not row or not row['mime'].startswith('audio/'):raise ValueError('配音文件不存在或无权使用')
            result['audio']=dict(asset_id=asset,volume=number(audio.get('volume',.7),0,2),duration=probe(self.hub.assets/asset)[0])
        detached=data.get('audio_clips',[])
        if not isinstance(detached,list) or len(detached)>50:raise ValueError('最多 50 段独立原声')
        result['audio_clips']=[]
        for clip in detached:
            task=str(clip.get('task_id',''))
            duration,streams=probe(self.audio_source(owner,admin,clip))
            if not any(s['codec_type']=='audio' for s in streams):raise ValueError('该素材没有原声音轨')
            start=number(clip.get('start',0),0,duration);end=number(clip.get('end',duration),0,duration+.05)
            at=number(clip.get('at',0),0,float('inf'))
            if end-start<.1:raise ValueError('独立原声时长或时间轴位置无效')
            if type(clip.get('locked',True)) is not bool:raise ValueError('音轨锁定状态无效')
            if type(clip.get('muted',False)) is not bool:raise ValueError('音轨静音状态无效')
            fade_in=number(clip.get('fade_in',0),0,end-start);fade_out=number(clip.get('fade_out',0),0,end-start)
            if fade_in+fade_out>end-start:raise ValueError('淡入淡出总时长不能超过音轨长度')
            identity=({'source':'voice','voice_job_id':str(clip.get('voice_job_id',''))} if clip.get('source')=='voice' else {'source':'asset','asset_id':str(clip.get('asset_id',''))} if clip.get('source')=='asset' else {'task_id':task})
            result['audio_clips'].append(dict(**identity,**({'source_duration':duration,'link_captions':bool(clip.get('link_captions',True))} if clip.get('source')=='voice' else {}),start=start,end=min(end,duration),at=at,
                volume=number(clip.get('volume',1),0,2),locked=clip.get('locked',True),muted=clip.get('muted',False),fade_in=fade_in,fade_out=fade_out))
        for key in ('clips','captions','audio_clips'):
            for original,clean in zip(data.get(key,[]),result[key]):
                for field in ('edit_group','edit_compound'):
                    value=original.get(field)
                    if value is not None:
                        if not isinstance(value,str) or not 1<=len(value)<=64 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in value):raise ValueError('片段组合标识无效')
                        clean[field]=value
        from sticker_model import validate_stickers
        result['stickers']=validate_stickers(data.get('stickers',[]))
        from multitrack import normalize
        normalize(data,result)
        archives=data.get('compound_sources',{})
        if not isinstance(archives,dict) or len(archives)>100:raise ValueError('复合片段源数据无效')
        live={c.get('edit_compound') for k in ('clips','captions','audio_clips') for c in result[k]}
        result['compound_sources']={}
        for key,entry in archives.items():
            if key not in live:continue
            if not isinstance(entry,dict):raise ValueError('复合片段源数据无效')
            clean_entry={}
            for field in ('source','visible'):
                raw=entry.get(field)
                if not isinstance(raw,dict):raise ValueError('复合片段源数据无效')
                subset={'ratio':ratio}
                for kind in ('clips','captions','audio_clips'):
                    rows=raw.get(kind,[])
                    if not isinstance(rows,list) or any(not isinstance(c,dict) or c.get('edit_compound')!=key for c in rows):raise ValueError('复合片段源归属无效')
                    subset[kind]=rows
                # Validate archived media with the same ownership and bounds checks.
                cleaned=self.validate(subset,owner,admin)
                clean_entry[field]={k:cleaned[k] for k in ('clips','captions','audio_clips')}
            result['compound_sources'][key]=clean_entry
        return result

    def recover(self):
        self.proxies.recover()
        with self.hub.db() as db:db.execute("UPDATE edit_exports SET state='failed',error='导出因服务重启中断，请重新导出' WHERE state='rendering'")

    def loop(self):
        while not self.hub.stop.is_set():
            # Both stages run on the single worker-lock holder. Proxy encode
            # checks the shared export queue even when the LAN HTTP app enqueues.
            self.proxies.recover()
            self.tick()
            self.proxies.tick()
            self.hub.stop.wait(2)

    def tick(self):
        from editor_proxy_claims import claim_export
        with self.hub.db() as db:
            job=claim_export(db)
        if not job:return
        try:
            if not job['enabled']:raise ValueError('成员账号已停用')
            data=self.validate(json.loads(job['body']),job['owner'],job['role']=='admin')
            from media_work import MEDIA_LOCK
            with MEDIA_LOCK:
                self.render(job['id'],data,job['owner'],job['role']=='admin')
            verify_export(self.root,job['id'])
            state,error='ready',''
        except Exception as exc:
            state,error='failed',str(exc) if isinstance(exc,ValueError) else '导出失败，请重试或联系管理员'
        with self.hub.db() as db:db.execute('UPDATE edit_exports SET state=?,error=?,updated=? WHERE id=?',(state,error,time.time(),job['id']))
        if state=='ready':
            from ai_edit_vision import queue_review
            queue_review(self,job)

    def render(self,job_id,data,owner,admin=False):
        if data.get('schema_version',0)>=4:
            from multitrack import render
            return render(self,job_id,data,owner,admin)
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:raise ValueError('执行机未找到 FFmpeg')
        if not timeline_duration(data):raise ValueError('请先加入素材或字幕')
        width,height={'9:16':(1080,1920),'16:9':(1920,1080),'1:1':(1080,1080)}[data['ratio']]
        video_total=sum((c['end']-c['start'])/c.get('speed',1) for c in data['clips'])
        total=timeline_duration(data)
        with render_directory(self.root) as tmp:
            folder=Path(tmp)
            for index,clip in enumerate(data['clips']):
                source=self.source(owner,admin,clip['task_id']);_,streams=probe(source);speed=clip.get('speed',1)
                length=(clip['end']-clip['start'])/speed
                args=[ffmpeg,'-hide_banner','-loglevel','error','-y','-threads','2','-ss',str(clip['start']),'-i',str(source)]
                has_audio=any(s['codec_type']=='audio' for s in streams)
                if not has_audio:args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                setpts=f',setpts=(PTS-STARTPTS)/{speed}' if abs(speed-1)>1e-6 else ''
                atempo=atempo_chain(speed)
                audio_filter=f"volume={clip['volume']}"+(f",{atempo}" if atempo else '')+',apad'
                from color_adjust import enabled,write_lut
                grade=''
                if enabled(clip.get('color',{})):
                    write_lut(folder/f'grade{index}.cube',clip['color']);grade=f',lut3d=file=grade{index}.cube:interp=trilinear'
                args+=['-map','0:v:0','-map','0:a:0' if has_audio else '1:a:0','-t',str(length),'-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1{setpts},fps=30{grade}','-af',audio_filter,'-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-threads','2',str(folder/f'clip{index}.mp4')]
                run(args,cwd=folder)
            count=len(data['clips'])
            if total-video_total>.001:
                run([ffmpeg,'-v','error','-y','-f','lavfi','-i',f'color=c=black:s={width}x{height}:r=30','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(total-video_total),'-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','aac','-threads','2',str(folder/f'clip{count}.mp4')])
                count+=1
            (folder/'concat.txt').write_text(''.join(f"file 'clip{i}.mp4'\n" for i in range(count)),encoding='utf-8')
            run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','1','-i','concat.txt','-c','copy','joined.mp4'],cwd=folder)
            args=[ffmpeg,'-hide_banner','-loglevel','error','-y','-i','joined.mp4']
            filters=[];labels=['[0:a]'];input_index=1
            if data['audio']:
                args+=['-i',str(self.hub.assets/data['audio']['asset_id'])]
                filters.append(f"[{input_index}:a]volume={data['audio']['volume']},apad[a{input_index}]")
                labels.append(f'[a{input_index}]');input_index+=1
            for clip in data.get('audio_clips',[]):
                args+=['-i',str(self.audio_source(owner,admin,clip))]
                delay=round(clip['at']*1000)
                volume=0 if clip.get('muted') else clip['volume']
                fades=''
                if clip.get('fade_in'):fades+=f",afade=t=in:st=0:d={clip['fade_in']}"
                if clip.get('fade_out'):fades+=f",afade=t=out:st={clip['end']-clip['start']-clip['fade_out']}:d={clip['fade_out']}"
                filters.append(f"[{input_index}:a]atrim=start={clip['start']}:end={clip['end']},asetpts=PTS-STARTPTS,volume={volume}{fades},adelay={delay}:all=1[a{input_index}]")
                labels.append(f'[a{input_index}]');input_index+=1
            if filters:
                filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=first:normalize=0[a]')
                args+=['-filter_complex',';'.join(filters),'-map','0:v','-map','[a]']
            if data['captions']:
                write_ass(folder/'captions.ass',data['captions'],width,height)
                args+=['-vf','ass=captions.ass:fontsdir=subtitle-fonts','-c:v','libx264','-preset','veryfast','-crf','21']
            else:args+=['-c:v','copy']
            args+=['-t',str(total),'-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-threads','2','-movflags','+faststart','finished.mp4'];run(args,cwd=folder)
            duration,streams=probe(folder/'finished.mp4')
            if abs(duration-total)>.3 or not any(s['codec_type']=='video' for s in streams):raise ValueError('导出时长校验失败，请重试')
            os.replace(folder/'finished.mp4',self.root/(job_id+'.mp4'))


FONT_DIR=Path(__file__).parent/'static'/'fonts'

def subtitle_fonts():
    """Subtitle font manifest shared with the browser preview (static/fonts/fonts.json)."""
    return {item['id']:item for item in json.loads((FONT_DIR/'fonts.json').read_text(encoding='utf-8'))}


CAPTION_STYLE_DEFAULTS={'size':150,'color':'#ffffff','outline':3,'outline_color':'#101010',
                        'align':'center','bold':False,'italic':False,'spacing':0,'case':'none'}
CAPTION_ALIGNS={'left':1,'center':2,'right':3}
CAPTION_CASES=('none','upper','lower')


def style_number(value,low,high,label):
    if isinstance(value,bool):raise ValueError(label+'无效')
    try:result=float(value)
    except (TypeError,ValueError):raise ValueError(label+'无效') from None
    if not math.isfinite(result) or not low<=result<=high:raise ValueError(f'{label}需在 {low}–{high} 之间')
    return round(result,2)


def style_color(value,label):
    text=str(value or '').strip().lower()
    if not re.fullmatch(r'#[0-9a-f]{6}',text):raise ValueError(label+'无效，请用 #RRGGBB')
    return text


def style_flag(value):
    if isinstance(value,str):return value.strip().lower() in ('1','true','yes','on')
    return bool(value)


def caption_style(caption):
    """Per-caption text style edited in the 文本栏 (browser preview + burned-in ASS share it)."""
    style=dict(CAPTION_STYLE_DEFAULTS)
    style['size']=style_number(caption.get('size',150),1,300,'字号')
    style['color']=style_color(caption.get('color','#ffffff'),'字幕颜色')
    style['outline']=style_number(caption.get('outline',3),0,12,'描边宽度')
    style['outline_color']=style_color(caption.get('outline_color','#101010'),'描边颜色')
    align=str(caption.get('align','center') or 'center').strip().lower()
    if align not in CAPTION_ALIGNS:raise ValueError('字幕对齐方式无效')
    style['align']=align
    style['bold']=style_flag(caption.get('bold',False))
    style['italic']=style_flag(caption.get('italic',False))
    style['spacing']=style_number(caption.get('spacing',0),-10,40,'字间距')
    case=str(caption.get('case','none') or 'none').strip().lower()
    if case not in CAPTION_CASES:raise ValueError('字幕大小写无效')
    style['case']=case
    # Optional free position: anchor point as a percentage of the frame. Both or neither.
    has_x=caption.get('x') is not None;has_y=caption.get('y') is not None
    if has_x!=has_y:raise ValueError('字幕位置需要同时提供 x 和 y')
    if has_x:
        style['x']=style_number(caption['x'],0,100,'字幕横向位置')
        style['y']=style_number(caption['y'],0,100,'字幕纵向位置')
    return style


def caption_text(text,style):
    if style['case']=='upper':return text.upper()
    if style['case']=='lower':return text.lower()
    return text


# Subtitle animations: entrance / exit effects plus a loop while the caption is on screen.
# They are pure ASS override tags (fad / move / t / k) so preview and burned-in export share them.
CAPTION_ANIMS_IN=('fade','rise','zoom','pop','type')
CAPTION_ANIMS_OUT=('fade','sink','shrink')
CAPTION_ANIMS_LOOP=('breathe','shake','karaoke','spoken')
CAPTION_ANIM_SLOTS=(('in',CAPTION_ANIMS_IN),('out',CAPTION_ANIMS_OUT),('loop',CAPTION_ANIMS_LOOP))
KARAOKE_COLOR='#23a9bd'


def caption_words(caption, text, span):
    raw=caption.get('words',[])
    if not isinstance(raw,list) or len(raw)>300:raise ValueError('词级时间数据无效')
    out=[];last=0
    for w in raw:
        if not isinstance(w,dict):raise ValueError('词级时间数据无效')
        a=w.get('from');b=w.get('to')
        if type(a) is not int or type(b) is not int or a<last or b<=a or b>len(text):raise ValueError('词级文字范围无效')
        start=number(w.get('start'),0,span+.05);end=number(w.get('end'),0,span+.05)
        if end<=start or w.get('text')!=text[a:b]:raise ValueError('词级时间与字幕文字不一致')
        out.append({'text':text[a:b],'from':a,'to':b,'start':start,'end':end});last=b
    return out


def caption_anim(caption):
    """Validated animation block: {'in':{'id','dur'},'out':{...},'loop':{...}} (all optional)."""
    raw=caption.get('anim')
    if raw in (None,'',{}):return {}
    if not isinstance(raw,dict):raise ValueError('字幕动画参数无效')
    result={}
    for slot,allowed in CAPTION_ANIM_SLOTS:
        item=raw.get(slot)
        if item in (None,'',{}):continue
        if isinstance(item,str):item={'id':item}
        if not isinstance(item,dict):raise ValueError('字幕动画参数无效')
        ident=str(item.get('id','')).strip().lower()
        if ident not in allowed:raise ValueError('字幕动画类型无效')
        entry={'id':ident}
        if ident=='spoken':entry['color']=style_color(item.get('color','#ff0000'),'跟读高亮颜色')
        elif ident!='karaoke':entry['dur']=style_number(item.get('dur',.4),.1,2,'动画时长')
        result[slot]=entry
    return result


def ass_color(code,alpha='00'):
    """#RRGGBB -> &HAABBGGRR as used by ASS colours."""
    value=code.lstrip('#')
    return f'&H{alpha}{value[4:6]}{value[2:4]}{value[0:2]}'.upper()


def caption_anchor(style,width,height,margin):
    """Text anchor used by \\move: free captions use their own point, stacked ones the style margins."""
    align=style['align']
    if 'x' in style:
        return ({'left':4,'center':5,'right':6}[align],round(style['x']/100*width),round(style['y']/100*height))
    return ({'left':1,'center':2,'right':3}[align],{'left':30,'center':width//2,'right':width-30}[align],height-margin)


def animation_block(enter,leave,loop,style,width,height,margin,span_ms,body):
    """ASS override tags + text for one Dialogue event covering `span_ms` milliseconds.

    Timeline inside the event: entrance 0..in_ms, exit span-out_ms..span, loop in_ms..span.
    Ranges never overlap on the same property (libass keeps one value per property per moment).
    """
    tags=[];fade_in=fade_out=0
    anchor,px,py=caption_anchor(style,width,height,margin)
    in_ms=min(round(enter['dur']*1000),span_ms) if enter else 0
    out_ms=min(round(leave['dur']*1000),max(0,span_ms-in_ms)) if leave else 0
    out_at=max(in_ms,span_ms-out_ms)
    if enter:
        ident=enter['id']
        if ident=='fade':fade_in=in_ms
        elif ident=='rise':
            fade_in=in_ms;dy=max(8,round(height*.12))
            tags.append(f'\\an{anchor}\\move({px},{py+dy},{px},{py},0,{in_ms})')
        elif ident=='zoom':
            fade_in=in_ms;tags.append(f'\\fscx165\\fscy165\\t(0,{in_ms},\\fscx100\\fscy100)')
        elif ident=='pop':
            fade_in=in_ms;mid=max(1,round(in_ms*.55))
            tags.append(f'\\fscx55\\fscy55\\t(0,{mid},\\fscx112\\fscy112)\\t({mid},{in_ms},\\fscx100\\fscy100)')
        elif ident=='type':
            # SecondaryColour made transparent: each character pops in when its \k syllable elapses.
            tags.append('\\2a&HFF&')
            count=len(body) or 1;step=max(1,round(in_ms/count))
            body=''.join('{\\k%d}%s'%(step,ch) for ch in body)
    if leave:
        ident=leave['id']
        if ident=='fade':fade_out=out_ms
        elif ident=='sink':
            fade_out=out_ms;dy=max(8,round(height*.12))
            tags.append(f'\\an{anchor}\\move({px},{py},{px},{py+dy},{out_at},{span_ms})')
        elif ident=='shrink':
            fade_out=out_ms;tags.append(f'\\t({out_at},{span_ms},\\fscx72\\fscy72)')
    if loop:
        ident=loop['id']
        if ident=='karaoke':
            count=len(body) or 1;step=max(1,round(span_ms/count))
            body=''.join('{\\kf%d}%s'%(step,ch) for ch in body)
            tags.append('\\1c'+ass_color(KARAOKE_COLOR))
        elif ident=='breathe':
            half=max(150,round(loop['dur']*500));tags.append('\\fscx100\\fscy100')
            at=in_ms;rounds=0
            while at+half<span_ms and rounds<10:
                tags.append(f'\\t({at},{at+half},\\fscx105\\fscy105)')
                tags.append(f'\\t({at+half},{min(span_ms,at+2*half)},\\fscx100\\fscy100)')
                at+=2*half;rounds+=1
        elif ident=='shake':
            half=max(80,round(loop['dur']*350));tags.append('\\frz0')
            at=in_ms;rounds=0
            while at+half<span_ms and rounds<14:
                tags.append(f'\\t({at},{at+half},\\frz2)')
                tags.append(f'\\t({at+half},{min(span_ms,at+2*half)},\\frz-2)')
                at+=2*half;rounds+=1
    lead=''.join(tags)
    if fade_in or fade_out:lead=f'\\fad({fade_in},{fade_out})'+lead
    return lead,body


def write_ass(path,captions,width,height):
    font_dir=path.parent/'subtitle-fonts'
    font_dir.mkdir(exist_ok=True)
    fonts=subtitle_fonts();used=[]
    for caption in captions:
        font=caption.get('font','default')
        if font in fonts and fonts[font].get('file') and font not in used:used.append(font)
    for font in used:shutil.copyfile(FONT_DIR/fonts[font]['file'],font_dir/fonts[font]['file'])
    margin=round(height*.07);scale=width/720
    def style(name,caption):
        font=caption.get('font','default');item=fonts.get(font,{})
        family=item.get('family') or 'Microsoft YaHei'
        look=caption_style(caption)
        raw_size=width*.045*look['size']/100
        size=max(0.01,round(raw_size,2)) if raw_size<8 else round(raw_size)
        outline=round(look['outline']*scale,1)
        spacing=round(look['spacing']*scale,1)
        fill=ass_color(look['color']);edge=ass_color(look['outline_color'])
        return (f'Style: {name},{family},{size},{fill},{fill},{edge},&H80000000,'
                f'{-1 if look["bold"] else 0},{-1 if look["italic"] else 0},0,0,100,100,'
                f'{spacing},0,1,{outline},0,{CAPTION_ALIGNS[look["align"]]},30,30,{margin},1\n')
    styles=style('Default',{})+''.join(style('C'+str(index),caption) for index,caption in enumerate(captions))
    def stamp(seconds):
        centis=round(seconds*100);return f'{centis//360000}:{centis//6000%60:02}:{centis//100%60:02}.{centis%100:02}'
    text=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    for index,caption in enumerate(captions):
        look=caption_style(caption)
        anim=caption_anim(caption)
        def ass_safe(value):
            return caption_text(value,look).replace('\\','＼').replace('{','｛').replace('}','｝').replace('\r','').replace('\n',r'\N')
        safe=ass_safe(caption['text'])
        words=caption_words(caption,caption['text'],caption['end']-caption['start']) if anim.get('loop',{}).get('id')=='spoken' else []
        enter=anim.get('in');leave=anim.get('out');loop=anim.get('loop')
        span=max(120,round((caption['end']-caption['start'])*1000))
        # A slide-in and a slide-out both need \move, and libass keeps only one position per event,
        # so that combination is emitted as two back-to-back events instead.
        split=bool(enter and enter['id']=='rise' and leave and leave['id']=='sink')
        if split:
            cut=max(span//4,min(span-80,span-round(leave['dur']*1000)))
            parts=[(0,cut,enter,None),(cut,span,None,leave)]
        else:
            parts=[(0,span,enter,leave)]
        for offset,until,part_in,part_out in parts:
            shown=safe
            if words:
                chunks=[];last=0;original=caption['text'];base=ass_color(look['color']);accent=ass_color(loop['color'])
                for word in words:
                    a,b=word['from'],word['to'];start=round(word['start']*1000)-offset;end=round(word['end']*1000)-offset
                    chunks.append(ass_safe(original[last:a]))
                    if end>0 and start<until-offset:
                        initial=accent if start<=0 else base
                        tags='\\1c'+initial
                        if start>0:tags+=f'\\t({start},{start+1},\\1c{accent})'
                        if end<until-offset:tags+=f'\\t({end},{end+1},\\1c{base})'
                        chunks.append('{'+tags+'}'+ass_safe(original[a:b])+'{\\1c'+base+'}')
                    else:chunks.append(ass_safe(original[a:b]))
                    last=b
                chunks.append(ass_safe(original[last:]));shown=''.join(chunks)
            lead,body=animation_block(part_in,part_out,loop,look,width,height,margin,until-offset,shown)
            over=[]
            if 'x' in look and r'\move' not in lead:
                anchor={'left':4,'center':5,'right':6}[look['align']]
                over.append(f"\\an{anchor}\\pos({round(look['x']/100*width)},{round(look['y']/100*height)})")
            if lead:over.append(lead)
            prefix='{'+''.join(over)+'}' if over else ''
            begin=caption['start']+offset/1000;finish=caption['start']+until/1000
            text+=f"Dialogue: 0,{stamp(begin)},{stamp(finish)},C{index},,0,0,0,,{prefix}{body}\n"
    path.write_text(text,encoding='utf-8-sig')


def attach(app,hub,user,body):
    editor=Editor(hub);app.state.editor=editor
    def owned(db,pid,u):
        row=db.execute('SELECT * FROM edit_projects WHERE id=? AND owner=?',(pid,u['id'])).fetchone()
        if not row:raise HTTPException(404,'剪辑项目不存在')
        return row

    @app.post('/api/editor/preview-proxy/{task_id}')
    def preview_proxy_status(request:Request,task_id:str):
        u=user(request)
        try:return editor.proxies.status(u['id'],u['role']=='admin',task_id)
        except (ValueError,OSError):raise HTTPException(404,'素材不可用') from None

    @app.get('/api/editor/preview-proxy/{task_id}/{version}')
    def preview_proxy_file(request:Request,task_id:str,version:str):
        u=user(request)
        try:path=editor.proxies.file(u['id'],u['role']=='admin',task_id,version)
        except (ValueError,OSError):path=None
        if not path:raise HTTPException(404,'预览代理不可用')
        return FileResponse(path,media_type='video/mp4')

    @app.post('/api/editor/footage')
    async def upload_footage(request:Request):
        return await store_footage(request,user(request))

    async def store_footage(request,u):
        from urllib.parse import unquote
        name=Path(unquote(request.headers.get('x-file-name','实拍视频')).replace('\\','/')).name[:160] or '实拍视频'
        if Path(name).suffix.lower() not in ('.mp4','.mov','.m4v'):
            raise HTTPException(400,'请选择 MP4、MOV 或 M4V 视频')
        limit=1024*1024*1024
        try:
            if int(request.headers.get('content-length','0'))>limit:raise HTTPException(413,'单个视频不能超过 1 GB')
        except ValueError:raise HTTPException(400,'文件大小无效') from None
        from datetime import datetime
        from zoneinfo import ZoneInfo
        created=time.time();day=datetime.fromtimestamp(created,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        folder=editor.footage/day
        fid='footage_'+secrets.token_hex(12);tmp=folder/(fid+'.part');target=folder/fid;size=0
        try:
            folder.mkdir(exist_ok=True)
            with tmp.open('xb') as out:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>limit:raise HTTPException(413,'单个视频不能超过 1 GB')
                    out.write(chunk)
            duration,streams=await run_in_threadpool(probe,tmp)
            if not any(s.get('codec_type')=='video' for s in streams):raise ValueError('文件没有视频画面')
            os.replace(tmp,target)
            with hub.db() as db:
                db.execute('INSERT INTO edit_footage VALUES(?,?,?,?,?,?)',(fid,u['id'],name,size,duration,created))
        except HTTPException:
            tmp.unlink(missing_ok=True);target.unlink(missing_ok=True);raise
        except PermissionError:
            for path in (tmp,target):
                try:path.unlink(missing_ok=True)
                except OSError:pass
            raise HTTPException(503,'实拍素材保存失败：服务器素材目录没有写入权限，请联系管理员') from None
        except (ValueError,OSError):
            tmp.unlink(missing_ok=True);target.unlink(missing_ok=True);raise HTTPException(400,'视频读取失败，请检查文件格式和磁盘空间') from None
        except BaseException:
            tmp.unlink(missing_ok=True);target.unlink(missing_ok=True);raise
        return {'id':fid,'name':name,'duration':duration,'size':size}

    @app.get('/api/editor/library')
    def library(request:Request, after:float=0, before:float=0):
        u=user(request)
        if not math.isfinite(after) or not math.isfinite(before) or after<0 or before<0 or (before and before<=after):raise HTTPException(400,'素材时间范围无效')
        bounds=' AND created>=?'+(' AND created<?' if before else '') if after or before else ''
        bound_args=(after,before) if before else (after,) if after else ()
        task_bounds=' AND t.created>=?'+(' AND t.created<?' if before else '') if after or before else ''
        with hub.db() as db:rows=db.execute("SELECT t.id,t.prompt,t.metadata,t.created FROM tasks t JOIN accounts a ON a.id=t.account_id WHERE t.state='ready' AND (t.owner=? OR (?='admin' AND a.scope='shared'))"+task_bounds+" ORDER BY t.created DESC",(u['id'],u['role'],*bound_args)).fetchall()
        result=[]
        for row in rows:
            try:
                duration,_=probe(editor.source(u['id'],u['role']=='admin',row['id']))
                result.append(dict(id=row['id'],title=row['prompt'][:65],duration=duration,created=row['created']))
            except ValueError:continue
        with hub.db() as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='libtv_jobs'").fetchone()
            extra=db.execute("SELECT id,payload,created FROM libtv_jobs WHERE owner=? AND state='ready'"+bounds+" ORDER BY created DESC",(u['id'],*bound_args)).fetchall() if exists else []
        for row in extra:
            try:
                duration,_=probe(editor.source(u['id'],False,row['id']))
                result.append(dict(id=row['id'],title=json.loads(row['payload'])['prompt'][:65],duration=duration,created=row['created']))
            except ValueError:continue
        with hub.db() as db:
            footage=db.execute('SELECT * FROM edit_footage WHERE owner=?'+bounds+' ORDER BY created DESC',(u['id'],*bound_args)).fetchall()
        for row in footage:
            if editor.footage_path(row).is_file():result.append(dict(id=row['id'],title=row['name'],duration=row['duration'],created=row['created'],kind='footage'))
        result.sort(key=lambda item:item.get('created') or 0,reverse=True)
        return {'items':result,'timeline_bundles':True,'multitrack':True,'time_range_filter':True,'available':bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))}

    @app.get('/api/editor/thumbnail/{task_id}')
    def thumbnail(task_id:str,request:Request,at:float=0):
        u=user(request)
        try:
            path=editor.source(u['id'],u['role']=='admin',task_id)
            duration,_=probe(path)
            at=round(number(at,0,duration),3)
            at=min(at,max(0,duration-1/24))
            tool=shutil.which('ffmpeg')
            if not tool:raise ValueError('执行机缺少缩略图工具')
            image=editor_media_cache.thumbnail(path,at,run,tool)
            return FileResponse(image,media_type='image/jpeg',headers={'Cache-Control':'private, no-cache'})
        except ValueError as exc:raise HTTPException(400,str(exc)) from None

    @app.get('/api/editor/waveform/{task_id}')
    def waveform(task_id:str,request:Request):
        u=user(request)
        try:
            kind=request.query_params.get('source','video')
            path=editor.audio_source(u['id'],u['role']=='admin',{'source':kind,'task_id':task_id,'voice_job_id':task_id,'asset_id':task_id})
            duration,streams=probe(path)
            if duration>600:raise ValueError('波形仅支持 10 分钟以内素材')
            if not any(s['codec_type']=='audio' for s in streams):return {'duration':duration,'peaks':[]}
            def calculate():
                raw=run([shutil.which('ffmpeg'),'-v','error','-i',str(path),'-vn','-ac','1','-ar','8000','-t','600','-f','s16le','pipe:1'],timeout=60)
                samples=array.array('h');samples.frombytes(raw)
                step=max(1,math.ceil(len(samples)/1200))
                peaks=[round(max(abs(v) for v in samples[i:i+step])/32768,4) for i in range(0,len(samples),step)]
                return {'duration':duration,'peaks':peaks}
            return editor_media_cache.waveform(path,calculate)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None

    @app.get('/api/editor/asr')
    def asr_status(request:Request):
        user(request)
        return asr.status()

    @app.post('/api/editor/asr/recognize')
    async def asr_recognize(request:Request):
        u=user(request);data=await body(request)
        try:content=editor.validate(data.get('body',{}),u['id'],u['role']=='admin')
        except (ValueError,TypeError,KeyError,AttributeError):raise HTTPException(400,'剪辑参数无效，请检查片段时长、素材权限和字幕时间') from None
        if not content['clips'] and not content['audio_clips'] and not content['audio']:raise HTTPException(400,'时间轴上还没有可识别的素材')
        language=str(data.get('language','auto') or 'auto')
        target=str(data.get('translate_to') or data.get('target_language') or '')
        try:
            result=await run_in_threadpool(asr.recognize,editor,hub,content,u['id'],u['role']=='admin',language,target)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        except Exception:
            import logging
            logging.getLogger('editor.asr').exception('asr recognize failed')
            raise HTTPException(500,'语音识别过程出错，请缩短项目后重试') from None
        return result

    @app.get('/api/editor/projects')
    def projects(request:Request, summary:bool=False):
        u=user(request)
        columns='p.id,p.owner,p.title,p.version,p.updated' if summary else 'p.*'
        with hub.db() as db:rows=db.execute('SELECT '+columns+', COALESCE((SELECT MIN(v.created) FROM edit_versions v WHERE v.project_id=p.id),p.updated) AS created FROM edit_projects p WHERE p.owner=? ORDER BY created DESC,p.updated DESC',(u['id'],)).fetchall()
        return [dict(r) if summary else {**dict(r),'body':json.loads(r['body'])} for r in rows]
    @app.get('/api/editor/projects/{pid}')
    def project_detail(pid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            row=db.execute('SELECT p.*, COALESCE((SELECT MIN(v.created) FROM edit_versions v WHERE v.project_id=p.id),p.updated) AS created FROM edit_projects p WHERE p.owner=? AND p.id=?',(u['id'],pid)).fetchone()
        if not row:raise HTTPException(404,'项目不存在')
        return {**dict(row),'body':json.loads(row['body'])}
    @app.post('/api/editor/projects')
    async def save(request:Request):
        u=user(request);data=await body(request);pid=data.get('id');title=str(data.get('title','未命名剪辑')).strip()[:80]
        try:content=editor.validate(data.get('body',{}),u['id'],u['role']=='admin')
        except (ValueError,TypeError,KeyError,AttributeError):raise HTTPException(400,'剪辑参数无效，请检查片段时长、素材权限和字幕时间') from None
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if pid:
                old=owned(db,pid,u)
                if data.get('version')!=old['version']:raise HTTPException(409,'项目已在其他窗口更新，请重新打开后编辑')
                version=old['version']+1
                db.execute('UPDATE edit_projects SET title=?,body=?,version=?,updated=? WHERE id=?',(title,json.dumps(content,ensure_ascii=False),version,time.time(),pid))
            else:
                pid=secrets.token_hex(12);version=1
                db.execute('INSERT INTO edit_projects VALUES(?,?,?,?,?,?)',(pid,u['id'],title,json.dumps(content,ensure_ascii=False),version,time.time()))
            for clip in content['clips']:
                db.execute('INSERT OR IGNORE INTO project_tasks VALUES(?,?,?,?)',(pid,clip['task_id'],u['id'],time.time()))
            record_version(db,pid)
            created=db.execute('SELECT MIN(created) FROM edit_versions WHERE project_id=?',(pid,)).fetchone()[0]
        return dict(id=pid,version=version,title=title,body=content,created=created)

    @app.get('/api/editor/projects/{pid}/versions')
    def versions(pid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            owned(db,pid,u)
            rows=db.execute('SELECT version,title,body,created FROM edit_versions WHERE project_id=? ORDER BY version DESC',(pid,)).fetchall()
        result=[]
        for row in rows:
            content=json.loads(row['body'])
            result.append(dict(version=row['version'],title=row['title'],created=row['created'],
                               clips=len(content.get('clips',[])),
                               duration=timeline_duration(content)))
        return result

    @app.post('/api/editor/projects/{pid}/restore')
    async def restore(pid:str,request:Request):
        u=user(request);data=await body(request)
        if type(data.get('version')) is not int or type(data.get('expected_version')) is not int:
            raise HTTPException(400,'请选择有效的工程版本')
        with hub.db() as db:
            owned(db,pid,u)
            target=db.execute('SELECT title,body FROM edit_versions WHERE project_id=? AND version=?',(pid,data.get('version'))).fetchone()
        if not target:raise HTTPException(404,'工程版本不存在')
        try:content=editor.validate(json.loads(target['body']),u['id'],u['role']=='admin')
        except (ValueError,TypeError,KeyError):raise HTTPException(400,'旧版本有素材缺失或不可访问，当前工程没有更改') from None
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');current=owned(db,pid,u)
            if data.get('expected_version')!=current['version']:raise HTTPException(409,'项目已更新，请重新载入后再恢复')
            version=current['version']+1
            db.execute('UPDATE edit_projects SET title=?,body=?,version=?,updated=? WHERE id=?',
                       (target['title'],json.dumps(content,ensure_ascii=False),version,time.time(),pid))
            record_version(db,pid)
        return dict(id=pid,version=version,title=target['title'],body=content)

    @app.get('/api/editor/selection-export-capability')
    def selection_export_capability(request:Request):
        user(request)
        return {'selection_export':1}

    @app.post('/api/editor/projects/{pid}/export')
    async def export(pid:str,request:Request):
        u=user(request);data=await body(request);key=str(data.get('request_key',''))
        if not 16<=len(key)<=100:raise HTTPException(400,'导出请求无效')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');project=owned(db,pid,u)
            import hashlib
            request_content={k:v for k,v in data.items() if k!='request_key'}
            signature=hashlib.sha256(json.dumps(request_content,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            old=db.execute('SELECT id,project_id FROM edit_exports WHERE owner=? AND request_key=?',(u['id'],key)).fetchone()
            if old:
                prior=db.execute('SELECT project_id,signature FROM edit_export_requests WHERE owner=? AND request_key=?',(u['id'],key)).fetchone()
                if old['project_id']!=pid or not prior or prior['project_id']!=pid or prior['signature']!=signature:
                    raise HTTPException(409,'导出请求标识已对应其他工程或参数（旧任务无法安全匹配时请核对导出记录），未重复导出')
                return {'id':old['id']}
            content=json.loads(project['body'])
            if 'selection' in data:
                selection=data['selection']
                if selection is None:
                    content['export_range']=None
                else:
                    if not isinstance(selection,dict):raise HTTPException(400,'导出选择无效')
                    for field in ('clips','captions','audio_clips'):
                        indexes=selection.get(field,[]);rows=content.get(field,[])
                        if not isinstance(indexes,list) or len(indexes)!=len(set(i for i in indexes if type(i) is int)) or any(type(i) is not int or i<0 or i>=len(rows) for i in indexes):raise HTTPException(400,'导出选择无效，请重新选择')
                        content[field]=[rows[i] for i in indexes]
                    if type(selection.get('audio',False)) is not bool:raise HTTPException(400,'导出选择无效')
                    if not selection.get('audio'):content['audio']=None
                    try:
                        from multitrack import export_range
                        content['export_range']=export_range(selection.get('range'))
                    except ValueError as e:raise HTTPException(400,str(e)) from None
                    if not any((content['clips'],content['captions'],content['audio_clips'],content['audio'])) or not content['export_range']:raise HTTPException(400,'请选择要导出的片段')
            if not timeline_duration(content):raise HTTPException(400,'请先加入素材或字幕')
            try:validate_export_range(content)
            except ValueError as e:raise HTTPException(400,str(e))
            if data.get('version')!=project['version']:raise HTTPException(409,'项目版本已变化，请保存后重试')
            if db.execute("SELECT COUNT(*) FROM edit_exports WHERE owner=? AND state IN ('queued','rendering')",(u['id'],)).fetchone()[0]>=3:raise HTTPException(409,'已有 3 个导出任务，请等待完成')
            name=str(data.get('name',project['title'])).strip()
            name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).strip(' .')
            if name.lower().endswith('.mp4'):name=name[:-4].rstrip(' .')
            if not name or len(name)>100:raise HTTPException(400,'视频名称请输入 1–100 个字符')
            content['export_name']=name
            eid=secrets.token_hex(12);now=time.time()
            db.execute('INSERT INTO edit_exports(id,owner,project_id,body,state,created,updated,request_key) VALUES(?,?,?,?,?,?,?,?)',(eid,u['id'],pid,json.dumps(content,ensure_ascii=False),'queued',now,now,key))
            db.execute('INSERT INTO edit_export_requests VALUES(?,?,?,?)',(u['id'],key,pid,signature))
            if hasattr(hub,'feishu'):hub.feishu.queue(db,eid,u['id'],now)
        return {'id':eid}

    @app.get('/api/editor/exports')
    def exports(request:Request):
        u=user(request)
        with hub.db() as db:
            rows=[dict(r) for r in db.execute("SELECT id,project_id,state,error,created,json_extract(body, '$.export_name') AS name FROM edit_exports WHERE owner=? ORDER BY created DESC LIMIT 30",(u['id'],))]
            if hasattr(hub,'feishu'):
                for r in rows:
                    archive=db.execute('SELECT state,error,file_token FROM feishu_uploads WHERE export_id=? AND owner=?',(r['id'],u['id'])).fetchone()
                    r['archive']=dict(archive) if archive else None
            return rows

    @app.get('/api/editor/exports/{eid}/video')
    def video(eid:str,request:Request,download:bool=False):
        u=user(request)
        with hub.db() as db:row=db.execute("SELECT id,body FROM edit_exports WHERE id=? AND owner=? AND state='ready'",(eid,u['id'])).fetchone()
        path=editor.root/(eid+'.mp4')
        if not row or not path.is_file():raise HTTPException(404,'成品尚未完成或无权访问')
        if not readable(path):
            raise HTTPException(503,'成品文件当前无法读取（常见于导出进程与预览账户不同），请重新导出或联系管理员修复文件权限')
        return FileResponse(path,media_type='video/mp4',filename=(json.loads(row['body']).get('export_name') or 'edited-video')+'.mp4' if download else None)
    @app.get('/api/editor/exports/{eid}/thumbnail')
    def export_thumbnail(eid:str,request:Request):
        u=user(request)
        with hub.db() as db:row=db.execute("SELECT id FROM edit_exports WHERE id=? AND owner=? AND state='ready'",(eid,u['id'])).fetchone()
        path=editor.root/(eid+'.mp4')
        if not row or not path.is_file():raise HTTPException(404,'成品尚未完成或无权访问')
        from editor_media_cache import thumbnail
        try:thumb=thumbnail(path,0.1,run,shutil.which('ffmpeg'))
        except (ValueError,OSError):raise HTTPException(503,'成品缩略图暂不可用') from None
        return FileResponse(thumb,media_type='image/jpeg')

    app.state.store_mobile_footage=store_footage
    return editor


def validate_export_range(data):
    if data.get('schema_version',0)<4 or not data.get('export_range'):return
    from multitrack import export_range,window
    window({'export_range':export_range(data['export_range'])},timeline_duration(data))


def timeline_duration(data):
    if data.get('schema_version',0)>=4:
        from multitrack import duration
        return duration(data)
    return max([sum((c['end']-c['start'])/c.get('speed',1) for c in data.get('clips',[])),
                (data.get('audio') or {}).get('duration',0)]+
               [c['end'] for c in data.get('captions',[])]+
               [c.get('at',0)+c['end']-c['start'] for c in data.get('audio_clips',[])])
