"""File-versioned metadata and thumbnail cache; authorization stays at callers."""
import hashlib,json,os,threading,uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'state'/'media-cache'
LOCKS=[threading.Lock() for _ in range(32)]
DECODE=threading.Semaphore(2)

def fingerprint(path,extra=''):
    p=Path(path).resolve();s=p.stat()
    return hashlib.sha256(f'{p}|{s.st_size}|{s.st_mtime_ns}|{s.st_ctime_ns}|{extra}'.encode()).hexdigest()

def metadata(path,loader):
    key=fingerprint(path,'probe-v1');ROOT.mkdir(parents=True,exist_ok=True)
    target=ROOT/(key+'.json')
    with LOCKS[int(key[:4],16)%len(LOCKS)]:
        try:
            data=json.loads(target.read_text(encoding='utf-8'))
            return data[0],data[1]
        except (OSError,ValueError,IndexError,TypeError):pass
        result=loader(path)
        temp=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_text(json.dumps(result),encoding='utf-8');os.replace(temp,target)
        finally:temp.unlink(missing_ok=True)
        return result

def waveform(path,loader):
    """Cache authorized callers' waveform results by file version; fail open on cache IO."""
    key=fingerprint(path,'waveform-v1:mono:8000:600:1200')
    target=ROOT/(key+'.wave.json')
    def read_cache():
        try:
            if target.stat().st_size>65536:return None
            data=json.loads(target.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or not isinstance(data.get('duration'),(int,float)) or not isinstance(data.get('peaks'),list) or len(data['peaks'])>1200:return None
            if not all(isinstance(v,(int,float)) and 0<=v<=1 for v in data['peaks']):return None
            return data
        except (OSError,ValueError,TypeError):return None
    with LOCKS[int(key[:4],16)%len(LOCKS)]:
        result=read_cache()
        if result is not None:return result
        with DECODE:result=loader()
        try:
            if fingerprint(path,'waveform-v1:mono:8000:600:1200')!=key:return result
            ROOT.mkdir(parents=True,exist_ok=True)
            temp=target.with_name(key+'.'+uuid.uuid4().hex+'.tmp')
            try:
                temp.write_text(json.dumps(result),encoding='utf-8');os.replace(temp,target)
            finally:temp.unlink(missing_ok=True)
        except OSError:pass
        return result


def frame_time(path,at):
    """Clamp image sampling to a decodable video frame, not the longer audio/container."""
    import math
    from fractions import Fraction
    from editor import probe
    duration,streams=probe(path)
    video=next((s for s in streams if s.get('codec_type')=='video'),None)
    if not video:raise ValueError('素材没有可抽取的视频轨')
    def positive(value):
        try:
            v=float(value)
            return v if math.isfinite(v) and v>0 else None
        except (ValueError,TypeError):return None
    video_duration=positive(video.get('duration'))
    if video_duration is None:
        try:video_duration=positive(float(video['duration_ts'])*float(Fraction(video['time_base'])))
        except (KeyError,ValueError,TypeError,ZeroDivisionError):pass
    end=min(duration,video_duration) if video_duration else duration
    fps=None
    for key in ('avg_frame_rate','r_frame_rate'):
        try:fps=positive(float(Fraction(video.get(key,'0/1'))))
        except (ValueError,TypeError,ZeroDivisionError):pass
        if fps:break
    # Leave a whole frame inside the video; unknown stream duration gets a conservative margin.
    margin=max(1/(fps or 24),.001) if video_duration else max(1/(fps or 24),.1)
    return round(max(0,min(float(at),max(0,end-margin))),6)


def thumbnail(path,at,run,ffmpeg,width=240,height=136):
    at=frame_time(path,at)
    key=fingerprint(path,f'thumb-v2:{width}x{height}:{at:.6f}');ROOT.mkdir(parents=True,exist_ok=True)
    target=ROOT/(key+'.jpg')
    with LOCKS[int(key[:4],16)%len(LOCKS)]:
        if target.is_file() and target.stat().st_size:return target
        temp=target.with_name(key+'.'+uuid.uuid4().hex+'.jpg')
        try:
            with DECODE:
                run([ffmpeg,'-v','error','-ss',str(at),'-i',str(path),'-frames:v','1','-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,format=yuvj420p','-threads','1','-q:v','5','-y',str(temp)],timeout=30)
            if not temp.is_file() or not temp.stat().st_size:raise ValueError('无法读取缩略图')
            os.replace(temp,target)
        finally:temp.unlink(missing_ok=True)
    return target
