import subprocess,shutil,time,tempfile,json
from pathlib import Path
ff=shutil.which('ffmpeg');probe=shutil.which('ffprobe')
with tempfile.TemporaryDirectory(prefix='seedance-benchmark-') as d:
 for name,opts in [('cpu2',['-c:v','libx264','-preset','veryfast','-crf','21','-threads','2']),('cpu4',['-c:v','libx264','-preset','veryfast','-crf','21','-threads','4']),('nvenc',['-c:v','h264_nvenc','-preset','p4','-rc','vbr','-cq','21','-b:v','0'])]:
  out=Path(d)/(name+'.mp4');cmd=[ff,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=1080x1920:rate=24:duration=4',*opts,'-pix_fmt','yuv420p',str(out)]
  start=time.monotonic();p=subprocess.run(cmd,capture_output=True,text=True,timeout=180);elapsed=time.monotonic()-start
  print(json.dumps({'encoder':name,'seconds':round(elapsed,2),'ok':p.returncode==0,'bytes':out.stat().st_size if out.exists() else 0,'error':p.stderr[-600:]},ensure_ascii=False),flush=True)
