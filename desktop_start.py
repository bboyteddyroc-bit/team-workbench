import socket,ssl,subprocess,time,urllib.request,webbrowser,ctypes
from pathlib import Path
root=Path(__file__).resolve().parent

def alive(host,port):
 try:
  with socket.create_connection((host,port),timeout=1):return True
 except OSError:return False

def main():
 import msvcrt
 with (root/'state'/'desktop-start.lock').open('a+b') as lock:
  lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
  try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
  except OSError:return
  for mode,host,port in [('local','127.0.0.1',8765),('lan','192.168.100.10',8443)]:
   if alive(host,port):continue
   with (root/'state'/('desktop-'+mode+'.out.log')).open('ab') as out,(root/'state'/('desktop-'+mode+'.err.log')).open('ab') as err:
    subprocess.Popen([str(root/'.venv/Scripts/python.exe'),'-B','run_service.py',mode],cwd=root,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
  op=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(root/'seedance-hub-ca.crt'))))
  pending=['http://127.0.0.1:8765/api/status','https://192.168.100.10:8443/api/status']
  from mobile_http import mobile_origin
  if mobile_origin().startswith('http:'):pending.append(mobile_origin()+'/health')
  for _ in range(15):
   for url in pending[:]:
    try:
     with op.open(url,timeout=2) as r:
      if r.status==200:pending.remove(url)
    except OSError:pass
   if not pending:break
   time.sleep(1)
  if pending:ctypes.windll.user32.MessageBoxW(0,'以下服务未就绪：\n'+'\n'.join(pending)+'\n请检查中台 state 目录的 desktop 日志。','中台启动提示',48)
  else:webbrowser.open('https://192.168.100.10:8443/')

if __name__=='__main__':
 try:main()
 except Exception as e:ctypes.windll.user32.MessageBoxW(0,str(e),'中台启动失败',16)
