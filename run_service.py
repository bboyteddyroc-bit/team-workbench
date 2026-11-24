"""Stable Hub entry point. LAN process also owns the token-only phone HTTP listener."""
import argparse
import os
from pathlib import Path

def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('local','lan'))
    args=parser.parse_args();lan=args.mode=='lan'
    os.chdir(root)
    local_ffmpeg=root/'tools/ffmpeg-7.1.1/ffmpeg-7.1.1-essentials_build/bin'
    if (local_ffmpeg/'ffmpeg.exe').is_file() and (local_ffmpeg/'ffprobe.exe').is_file():
        os.environ['PATH']=str(local_ffmpeg)+os.pathsep+os.environ.get('PATH','')
    os.environ['HUB_STATE']=str(root/'state')
    # Installation-local rollout switch; an explicit environment override wins.
    os.environ.setdefault('HUB_PREVIEW_PROXY','1' if (root/'state/preview-proxy.enabled').is_file() else '0')
    os.environ['HUB_ORIGIN']='https://192.168.100.10:8443' if lan else 'http://127.0.0.1:8765'
    from app import create_app
    from mobile_http import create_phone_app,mobile_origin
    import uvicorn
    import threading
    from urllib.parse import urlsplit
    hub_app=create_app(worker=lan)
    print('Preview proxy enabled: '+str(hub_app.state.editor.proxies.enabled),flush=True)
    phone_server=None;phone_thread=None
    # The existing desktop launcher always starts LAN. Phone HTTP lives and exits with that process.
    if lan and urlsplit(mobile_origin()).scheme=='http':
        origin=urlsplit(mobile_origin())
        phone_app=create_phone_app(hub_app)
        phone_server=uvicorn.Server(uvicorn.Config(phone_app,host=origin.hostname,port=origin.port or 80,proxy_headers=False,access_log=False,server_header=False))
        # Bind synchronously: a conflicting old EXE must fail visibly, not silently lose phone HTTP.
        phone_socket=phone_server.config.bind_socket()
        phone_thread=threading.Thread(target=lambda:phone_server.run(sockets=[phone_socket]),name='hub-mobile-http',daemon=True)
        phone_thread.start()
        print('Phone transfer HTTP enabled on '+mobile_origin()+' (LAN only, unencrypted, no login routes)',flush=True)
    options=dict(ssl_keyfile=str(root/'state/tls/server.key'),ssl_certfile=str(root/'state/tls/server.crt')) if lan else {}
    try:
        uvicorn.run(hub_app,host='192.168.100.10' if lan else '127.0.0.1',port=8443 if lan else 8765,proxy_headers=False,access_log=False,**options)
    finally:
        if phone_server:phone_server.should_exit=True
        if phone_thread:phone_thread.join(timeout=5)

if __name__=='__main__':main()
