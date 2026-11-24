"""On-demand scene thumbnails for a local case preview."""
import base64
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException


@lru_cache(maxsize=24)
def detect(path: Path, modified_ns: int):
    with TemporaryDirectory() as temp:
        output = Path(temp)
        # Select at source frame rate. showinfo and the thumbnails use the same selected frames.
        filters = "scale=160:-2,setpts=PTS-STARTPTS,select='eq(n,0)+gt(scene,0.27)',showinfo"
        try:
            run = subprocess.run(
                ['ffmpeg', '-nostdin', '-hide_banner', '-protocol_whitelist', 'file,pipe',
                 '-f', 'mov', '-i', str(path), '-map', '0:v:0', '-an', '-vf', filters,
                 '-fps_mode', 'vfr', '-frames:v', '80', '-threads', '1', '-q:v', '5',
                 str(output / '%03d.jpg')],
                capture_output=True, timeout=90, check=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise HTTPException(503, '镜头读取失败，可继续播放原片或稍后重试') from None
        times = re.findall(rb'Parsed_showinfo[^\n]*?\bn:\s*\d+\s+pts:\s*\d+\s+pts_time:([\d.eE+-]+)', run.stderr)
        frames = sorted(output.glob('*.jpg'))
        if not frames or len(times) < len(frames):
            raise HTTPException(422, '未能读取视频时间点')
        return [{'start': float(t), 'thumbnail': base64.b64encode(frame.read_bytes()).decode('ascii')}
                for t, frame in zip(times, frames)]


@lru_cache(maxsize=128)
def still(path: Path, modified_ns: int, milliseconds: int):
    try:
        data = subprocess.check_output([
            'ffmpeg', '-nostdin', '-v', 'error', '-ss', f'{milliseconds / 1000:.3f}',
            '-protocol_whitelist', 'file,pipe', '-f', 'mov', '-i', str(path),
            '-map', '0:v:0', '-frames:v', '1', '-vf',
            'scale=480:480:force_original_aspect_ratio=decrease', '-threads', '1',
            '-q:v', '4', '-f', 'image2pipe', '-c:v', 'mjpeg', 'pipe:1'
        ], timeout=15)
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(503, '暂时无法读取原片截图') from None
    if not data:
        raise HTTPException(404, '该时间点没有画面')
    return data
