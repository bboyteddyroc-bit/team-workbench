"""Frame-aligned multitrack metadata and export. Original media stays untouched."""
import math
import logging
import os
import shutil
import tempfile
from pathlib import Path
FPS=24  # Existing timeline and project timing remain 24 fps.
EXPORT_FPS=30

def frames(seconds):
    return max(1,math.floor(seconds*FPS+.5))

def video_length(clip):
    return frames((clip['end']-clip['start'])/clip.get('speed',1))/FPS

def normalize(data,result):
    supplied=data.get('tracks',[])
    if not isinstance(supplied,list) or len(supplied)>100:raise ValueError('轨道数据无效')
    tracks=[];seen=set()
    def track(key,muted=False):
        if not isinstance(key,str) or not 1<=len(key)<=80 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in key):raise ValueError('轨道标识无效')
        if key not in seen:seen.add(key);tracks.append({'id':key,'muted':muted})
        return key
    for row in supplied:
        if not isinstance(row,dict) or type(row.get('muted',False)) is not bool:raise ValueError('轨道设置无效')
        track(row.get('id'),row.get('muted',False))
    at=0
    for i,c in enumerate(result['clips']):
        raw=data['clips'][i];start=float(raw.get('at',at))
        if not math.isfinite(start) or start<0:raise ValueError('视频时间位置无效')
        c['audio_detached']=bool(raw.get('audio_detached',False));c['at']=math.floor(start*FPS+.5)/FPS;c['track']=track(raw.get('track','video-main'))
        at=c['at']+video_length(c)
    for kind,default in [('captions','caption-main'),('audio_clips','audio'),('stickers','sticker-main')]:
        for i,c in enumerate(result.get(kind,[])):
            raw=(data.get(kind) or [])
            c['track']=track((raw[i] if i<len(raw) else {}).get('track',default if kind!='audio_clips' else f'audio-{i}'))
    if result.get('audio'):result['audio']['track']=track(data.get('audio',{}).get('track','background-audio'))
    main=data.get('main_track')
    if main is not None:
        track(main)
        result['main_track']=main
    result['tracks']=tracks;result['schema_version']=4
    result['export_range']=export_range(data.get('export_range'))

def export_range(raw):
    """Optional {start,end} in seconds, quantised to frames; None exports the whole timeline."""
    if raw is None:return None
    if not isinstance(raw,dict):raise ValueError('导出选区无效')
    try:start=float(raw.get('start'));end=float(raw.get('end'))
    except (TypeError,ValueError):raise ValueError('导出选区无效')
    if not (math.isfinite(start) and math.isfinite(end)) or start<0 or end>86400:raise ValueError('导出选区无效')
    start=math.floor(start*FPS+.5)/FPS;end=math.floor(end*FPS+.5)/FPS
    if end-start<1/FPS-1e-9:raise ValueError('导出选区至少 1 帧')
    return {'start':start,'end':end}

def window(data,total):
    """Resolve the exported (start,end) inside the full timeline length."""
    r=data.get('export_range')
    if not r:return 0.0,total
    start=r['start'];end=min(r['end'],total)
    if start>=total-1e-9 or end-start<1/FPS-1e-9:raise ValueError('导出选区超出时间轴，请重新设置入点和出点')
    return start,end

def duration(data):
    return max([0]+[c.get('at',0)+video_length(c) for c in data['clips']]+[c['end'] for c in data['captions']]+[c['at']+c['end']-c['start'] for c in data.get('audio_clips',[])]+[c['end'] for c in data.get('stickers',[])]+[data.get('audio',{}).get('duration',0) if data.get('audio') else 0])

_NVENC_CAPABILITIES={}

def nvenc_available(run,executable):
    """Probe the actual encoder once per executable version, not just its listing."""
    try:
        stat=Path(executable).stat()
        key=(str(executable),stat.st_mtime_ns,stat.st_size)
    except OSError:
        key=(str(executable),None,None)
    if key not in _NVENC_CAPABILITIES:
        try:
            run([executable,'-v','error','-f','lavfi','-i','color=s=64x64:r=24',
                 '-frames:v','1','-c:v','h264_nvenc','-f','null','-'],timeout=15)
            _NVENC_CAPABILITIES[key]=True
        except ValueError:
            _NVENC_CAPABILITIES[key]=False
    return _NVENC_CAPABILITIES[key]

def run_final_encode(run,args,cwd):
    """Prefer NVENC for the final composition; retry CPU on encoder failure.

    The temporary output is overwritten by the CPU retry and is never published
    until the normal duration check has passed.
    """
    cpu=['-c:v','libx264','-preset','veryfast','-crf','21']
    gpu=['-c:v','h264_nvenc','-preset','p4','-rc','vbr','-cq','21','-b:v','0']
    index=args.index('-c:v')
    if args[index:index+len(cpu)] != cpu:raise ValueError('导出编码参数无效')
    if not nvenc_available(run,args[0]):
        run(args,cwd=cwd)
        return 'cpu'
    try:
        run(args[:index]+gpu+args[index+len(cpu):],cwd=cwd)
        logging.getLogger(__name__).info('Final export encoded with NVIDIA NVENC')
        return 'gpu'
    except ValueError:
        logging.getLogger(__name__).warning('GPU export failed; retrying final encode with CPU')
        run(args,cwd=cwd)
        return 'cpu'

def render(editor,job_id,data,owner,admin):
    from editor import run,probe,atempo_chain,write_ass,render_directory
    ffmpeg=shutil.which('ffmpeg');width,height={'9:16':(1080,1920),'16:9':(1920,1080),'1:1':(1080,1080)}[data['ratio']]
    total=math.ceil(duration(data)*FPS-1e-7)/FPS
    if total<=0:raise ValueError('请先加入素材')
    cut_start,cut_end=window(data,total);ranged=bool(data.get('export_range'));out_total=cut_end-cut_start
    muted={t['id'] for t in data['tracks'] if t.get('muted')};order={t['id']:i for i,t in enumerate(data['tracks'])}
    with render_directory(editor.root) as temp:
        folder=Path(temp);files=[]
        # A clip outside the output window cannot affect its video or embedded audio.
        # Keep original timeline positions for the remaining clips and for compositing.
        clips=[c for c in data['clips'] if not ranged or (c['at'] < cut_end and c['at']+video_length(c) > cut_start)]
        for i,c in enumerate(clips):
            path=editor.source(owner,admin,c['task_id']);_,streams=probe(path);has_audio=any(s['codec_type']=='audio' for s in streams)
            rate=c.get('speed',1);span=video_length(c);volume=0 if c['track'] in muted else c['volume']
            args=[ffmpeg,'-v','error','-y','-threads','2','-ss',str(c['start']),'-i',str(path)]
            if not has_audio:args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
            vf=f"trim=duration={c['end']-c['start']},setpts=(PTS-STARTPTS)/{rate},fps={EXPORT_FPS},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,tpad=stop_mode=clone:stop_duration=1"
            from color_adjust import enabled,write_lut
            if enabled(c.get('color',{})):
                lut=folder/f'grade{i}.cube';write_lut(lut,c['color'])
                # Run FFmpeg in the render directory so the filter path is portable on Windows.
                vf+=f',lut3d=file=grade{i}.cube:interp=trilinear'
            af=f"atrim=duration={c['end']-c['start']},asetpts=PTS-STARTPTS,{atempo_chain(rate)},volume={volume},apad".replace(',,',',')
            out=folder/f'video{i}.mp4';files.append(out)
            run(args+['-map','0:v:0','-map','0:a:0' if has_audio else '1:a:0','-vf',vf,'-af',af,'-t',str(span),'-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-threads','2',str(out)],cwd=folder)
        # Stickers are bundled animated GIFs. Bake each one into a short alpha video
        # at the export frame rate and final pixel size, so the composite graph only
        # has to overlay a bounded, predictable stream instead of looping a GIF.
        from sticker_model import sticker_path
        stickers=[c for c in data.get('stickers',[]) if not ranged or (c['start'] < cut_end and c['end'] > cut_start)]
        sticker_boxes=[]
        for i,c in enumerate(stickers):
            span=round((c['end']-c['start'])*EXPORT_FPS)/EXPORT_FPS
            if span<1/EXPORT_FPS:continue
            size=max(2,round(width*c['width']/2)*2)
            big=max(2,math.ceil(size*math.sqrt(2)/2)*2)
            angle=math.radians(c['rotation'])
            vf=(f'fps={EXPORT_FPS},scale={size}:{size}:flags=lanczos,format=rgba,'
                f'pad={big}:{big}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,'
                f'rotate={angle}:ow={big}:oh={big}:c=none,format=rgba')
            out=folder/f'sticker{i}.mov'
            run([ffmpeg,'-v','error','-y','-stream_loop','-1','-i',str(sticker_path(c['style'])),
                 '-t',f'{span:.6f}','-vf',vf,'-an','-c:v','qtrle','-pix_fmt','argb',str(out)],cwd=folder)
            sticker_boxes.append((c,out,big))
        args=[ffmpeg,'-v','error','-y','-filter_complex_threads','1','-f','lavfi','-i',f'color=c=black:s={width}x{height}:r={EXPORT_FPS}:d={total}']
        for file in files:args+=['-i',str(file)]
        filters=[];audios=[];base='0:v'
        # Lower row first; upper row composites on top. Each clip has exact frame-aligned bounds.
        for i in sorted(range(len(files)),key=lambda n:order[clips[n]['track']],reverse=True):
            c=clips[i];at=c['at'];end=at+video_length(c);idx=i+1
            filters.append(f'[{idx}:v]setpts=PTS-STARTPTS+{at}/TB[v{i}]')
            filters.append(f"[{base}][v{i}]overlay=eof_action=pass:repeatlast=0:enable='gte(t,{at})*lt(t,{end})'[layer{i}]");base=f'layer{i}'
            filters.append(f'[{idx}:a]asetpts=PTS-STARTPTS,adelay={round(at*1000)}:all=1[va{i}]');audios.append(f'[va{i}]')
        sounds=list(data.get('audio_clips',[]))
        if data.get('audio'):
            a=data['audio'];sounds.append(dict(source='asset',asset_id=a['asset_id'],start=0,end=a['duration'],at=0,volume=a['volume'],track=a['track']))
        for i,c in enumerate(sounds):
            idx=len(files)+1+i;args+=['-i',str(editor.audio_source(owner,admin,c))];volume=0 if c.get('muted') or c['track'] in muted else c['volume']
            af=f"atrim=start={c['start']}:end={c['end']},asetpts=PTS-STARTPTS,volume={volume}"
            if c.get('fade_in'):af+=f",afade=t=in:st=0:d={c['fade_in']}"
            if c.get('fade_out'):af+=f",afade=t=out:st={c['end']-c['start']-c['fade_out']}:d={c['fade_out']}"
            filters.append(f'[{idx}:a]{af},adelay={round(c["at"]*1000)}:all=1[sa{i}]');audios.append(f'[sa{i}]')
        # Stickers composite above every video row and below burned-in captions.
        for i,(c,out,big) in enumerate(sticker_boxes):
            idx=len(files)+1+len(sounds)+i;args+=['-i',str(out)]
            at=c['start'];end=c['end']
            x=round(c['x']*width-big/2);y=round(c['y']*height-big/2)
            filters.append(f'[{idx}:v]setpts=PTS-STARTPTS+{at}/TB[stk{i}]')
            filters.append(f"[{base}][stk{i}]overlay=x={x}:y={y}:eof_action=pass:repeatlast=0:enable='gte(t,{at})*lt(t,{end})'[slayer{i}]");base=f'slayer{i}'
        if audios:filters.append(''.join(audios)+f'amix=inputs={len(audios)}:normalize=0,apad[mix]')
        else:filters.append('anullsrc=r=48000:cl=stereo[mix]')
        if data['captions']:
            write_ass(folder/'captions.ass',data['captions'],width,height);filters.append(f'[{base}]ass=captions.ass:fontsdir=subtitle-fonts[outv]');base='outv'
        mix='mix'
        if ranged:
            filters.append(f'[{base}]trim=start={cut_start}:end={cut_end},setpts=PTS-STARTPTS[rangev]');base='rangev'
            filters.append(f'[mix]atrim=start={cut_start}:end={cut_end},asetpts=PTS-STARTPTS,apad[rangea]');mix='rangea'
        args+=['-filter_complex',';'.join(filters),'-map',f'[{base}]' if base!='0:v' else '0:v','-map',f'[{mix}]','-t',str(out_total),'-r',str(EXPORT_FPS),'-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-threads','2','-movflags','+faststart','finished.mp4']
        run_final_encode(run,args,cwd=folder)
        actual,streams=probe(folder/'finished.mp4')
        if abs(actual-out_total)>.15:raise ValueError('导出时长校验失败')
        os.replace(folder/'finished.mp4',editor.root/(job_id+'.mp4'))
