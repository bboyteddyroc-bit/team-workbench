"""Conservative preview-proxy eligibility; does not change or transcode media."""
import math
from fractions import Fraction


def _rate(value):
    try:
        n=float(Fraction(str(value)))
        return n if math.isfinite(n) and n>0 else None
    except (ValueError, ZeroDivisionError, TypeError, OverflowError):
        return None


def inspect(duration, streams):
    """Return evidence for an authorized caller; unknown is never treated as safe."""
    video=next((s for s in streams if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')),None)
    if not video:return {'eligible':False,'reason':'no_video'}
    try:
        width,height=int(video.get('width',0)),int(video.get('height',0))
    except (TypeError,ValueError,OverflowError):
        width=height=0
    if width<=0 or height<=0:return {'eligible':False,'reason':'unknown_dimensions'}
    fps=_rate(video.get('avg_frame_rate'));nominal=_rate(video.get('r_frame_rate'))
    # A difference is a useful warning, not a definitive VFR test.
    timing_uncertain=not fps or not nominal or abs(fps-nominal)>0.05
    try:dur=float(duration)
    except (TypeError,ValueError,OverflowError):dur=0
    if not math.isfinite(dur) or dur<=0:return {'eligible':False,'reason':'unknown_duration'}
    return {'eligible':max(width,height)>1920 or width*height>1920*1080 or bool(fps and fps>30.5),
            'width':width,'height':height,'fps':fps,'nominal_fps':nominal,
            'codec':str(video.get('codec_name') or ''),'duration':dur,'timing_uncertain':timing_uncertain}


def validate_proxy(source_duration, source_streams, proxy_duration, proxy_streams):
    """Reject obviously misaligned proxy media; passing is not proof of sync/VFR safety."""
    def stream(streams, kind):
        return next ( (s for s in streams if s.get('codec_type')==kind and not s.get('disposition',{}).get('attached_pic')),None)
    def number(value):
        try:
            n=float(value)
            return n if math.isfinite(n) else None
        except (TypeError,ValueError,OverflowError):return None
    a=inspect(source_duration,source_streams);b=inspect(proxy_duration,proxy_streams)
    if 'duration' not in a or 'duration' not in b:return False,'invalid_video'
    original_video=stream(source_streams,'video')
    # Until display-matrix and color-managed conversion are independently verified,
    # preserve correctness by refusing these cases instead of guessing.
    rotation=original_video.get('tags',{}).get('rotate')
    if rotation not in (None,'0',0,'0.0'):return False,'unsupported_rotation'
    if any(x.get('rotation') not in (None,0,0.0) or x.get('side_data_type')=='Display Matrix' for x in original_video.get('side_data_list',[])):
        return False,'unsupported_display_matrix'
    sar=original_video.get('sample_aspect_ratio')
    if sar not in (None,'1:1'):return False,'unsupported_pixel_aspect'
    if original_video.get('color_transfer') in ('smpte2084','arib-std-b67') or original_video.get('color_primaries')=='bt2020':
        return False,'unsupported_hdr'
    if abs(a['duration']-b['duration'])>0.1:return False,'duration_mismatch'
    if b['codec']!='h264' or not b['fps'] or abs(b['fps']-30)>0.05:return False,'unexpected_encoding'
    if max(b['width'],b['height'])>1920:return False,'proxy_too_large'
    if abs(a['width']/a['height']-b['width']/b['height'])>0.01:return False,'aspect_mismatch'
    for kind in ('video','audio'):
        original=stream(source_streams,kind);derived=stream(proxy_streams,kind)
        if bool(original)!=bool(derived):return False,'stream_mismatch'
        if original:
            first,second=number(original.get('start_time')),number(derived.get('start_time'))
            if first is None or second is None:return False,'unknown_start_time'
            if abs(first-second)>0.05:return False,'start_mismatch'
    if a['timing_uncertain']:return False,'source_timing_uncertain'
    return True,'metadata_consistent_only'
