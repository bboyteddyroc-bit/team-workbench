"""Experimental direct-FFmpeg proxy encoder; not connected to application.

Only an authorized caller may supply paths. Preserve source; use temporary output.
"""
import shutil
from editor_proxy_process import run_owned


def transcode(source, output, should_yield, timeout=1800, *, token=None):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise ValueError('FFmpeg unavailable')
    # Limit the longest dimension, preserve aspect, never upscale, and keep audio.
    # Direct execution means the tracked child is ffmpeg, not a wrapper process.
    vf="scale=w='trunc(iw*min(1,1280/max(iw,ih))/2)*2':h='trunc(ih*min(1,1280/max(iw,ih))/2)*2',fps=30"
    args=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-n','-i',str(source),'-map','0:v:0','-map','0:a:0?',
          '-filter_threads','2','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','25','-maxrate','2500k','-bufsize','5000k','-pix_fmt','yuv420p',
          '-c:a','aac','-b:a','128k','-threads','2','-movflags','+faststart',str(output)]
    return run_owned(args,should_yield,timeout=timeout,low_priority=True,protected=token or False)
