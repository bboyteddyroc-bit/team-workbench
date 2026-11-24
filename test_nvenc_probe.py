import subprocess,tempfile,time,json
from pathlib import Path
root=Path(__file__).resolve().parent
ff=root/'tools/ffmpeg-7.1.1/ffmpeg-7.1.1-essentials_build/bin/ffmpeg.exe'
probe=ff.with_name('ffprobe.exe')
with tempfile.TemporaryDirectory() as tmp:
 for name,opts in [('cpu',['-c:v','libx264','-preset','veryfast','-crf','21','-threads','2']),('gpu',['-c:v','h264_nvenc','-preset','p4','-rc','vbr','-cq','21','-b:v','0'])]:
  p=Path(tmp)/(name+'.mp4');start=time.monotonic()
  cmd=[str(ff),'-v','error','-y','-f','lavfi','-i','testsrc2=size=1080x1920:rate=24:duration=4','-f','lavfi','-i','sine=frequency=440:duration=4',*opts,'-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(p)]
  result=subprocess.run(cmd,capture_output=True,text=True,timeout=120);elapsed=time.monotonic()-start
  if result.returncode:raise RuntimeError(result.stderr)
  info=json.loads(subprocess.check_output([str(probe),'-v','error','-show_entries','stream=codec_name,codec_type,width,height:format=duration','-of','json',str(p)],text=True))
  check=subprocess.run([str(ff),'-v','error','-i',str(p),'-f','null','-'],capture_output=True,text=True,timeout=60)
  print(json.dumps({'name':name,'seconds':round(elapsed,2),'bytes':p.stat().st_size,'probe':info,'decode_ok':check.returncode==0},ensure_ascii=False),flush=True)
