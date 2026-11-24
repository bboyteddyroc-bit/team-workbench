"""Read-only LibTV auth diagnostics. Never emit raw account or token output."""
import json,subprocess,shutil,re
from pathlib import Path
exe=shutil.which('libtv')
for args in (['model','lib-image-2.5-f'],['node','图片','-p','399e1dae4ba6401585a9490281c202df']):
    result=subprocess.run([exe,*args],cwd=Path(__file__).resolve().parent,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',errors='replace')
    text=result.stdout+'\n'+result.stderr
    print(json.dumps({'operation':args[0],'returncode':result.returncode,'unauthorized':bool(re.search(r'用户未授权|未登录|unauthorized',text,re.I)),'code10001':bool(re.search(r'\b10001\b',text)),'quota_hint':bool(re.search(r'余额不足|积分不足|额度不足',text))},ensure_ascii=True),flush=True)
