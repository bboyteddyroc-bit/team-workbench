"""Read-only account checks; print only error categories, no identity or tokens."""
import os,subprocess,json,re,socket,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parent
con=sqlite3.connect('file:'+str(root/'state/hub.sqlite3')+'?mode=ro',uri=True)
print('DB tables:',[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'libtv%'")])
for table in ['libtv_jobs']:
 cols=[r[1] for r in con.execute('PRAGMA table_info('+table+')')]
 print('Job schema:',cols)
 if 'error' in cols:
  for (text,) in con.execute('SELECT error FROM libtv_jobs WHERE error IS NOT NULL ORDER BY updated DESC LIMIT 10'):
   print('Saved failure:',json.dumps({'EACCES':'EACCES' in (text or ''),'fetch_failed':'fetch failed' in (text or ''),'screenshot_id':'d5d5db953464' in (text or '')}))
exe=root/'tools/libtv-1.2.0/libtv.exe'
for directory in (root/'state/libtv-profiles').iterdir():
 if not directory.is_dir() or not (directory/'credentials.json').exists():continue
 env=os.environ.copy();env.pop('LIBTV_TOKEN',None);env['LIBTV_CONFIG_DIR']=str(directory)
 try:
  p=subprocess.run([str(exe),'account','list'],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
  text=(p.stdout+p.stderr).decode('utf-8','replace')
  hosts=re.findall(r'https?://([^/\s\"\x27]+)',text)
  print('Account probe:',json.dumps({'profile':directory.name,'exit':p.returncode,'hosts':list(set(hosts)),'EACCES':'EACCES' in text,'unauthorized':bool(re.search(r'10001|未授权|unauthorized',text,re.I)),'fetch_failed':'fetch failed' in text,'error_codes':list(set(re.findall(r'\bE[A-Z]{3,}\b',text)))}))
 except subprocess.TimeoutExpired:print('Account probe timeout:',directory.name)
