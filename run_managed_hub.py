"""Managed local/LAN launcher using this project's pinned environment."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
python=ROOT/'.venv'/'Scripts'/'python.exe'
if Path(sys.executable).resolve()!=python.resolve():
    raise SystemExit(subprocess.call([str(python),'-B',str(Path(__file__).resolve()),*sys.argv[1:]],cwd=str(ROOT)))
p=argparse.ArgumentParser()
p.add_argument('mode',choices=('local','lan'))
p.add_argument('--host',default='192.168.100.10')
a=p.parse_args()
os.chdir(ROOT)
os.environ['HUB_STATE']=str(ROOT/'state')
os.environ['HUB_ORIGIN']='http://127.0.0.1:8765' if a.mode=='local' else f'https://{a.host}:8443'
from app import create_app
import uvicorn
options={}
if a.mode=='lan':
    options=dict(ssl_keyfile=str(ROOT/'state'/'tls'/'server.key'),ssl_certfile=str(ROOT/'state'/'tls'/'server.crt'))
print(f'Starting {a.mode} hub: {os.environ["HUB_ORIGIN"]}; worker={a.mode=="lan"}',flush=True)
uvicorn.run(create_app(worker=a.mode=='lan'),host='127.0.0.1' if a.mode=='local' else a.host,port=8765 if a.mode=='local' else 8443,proxy_headers=False,access_log=False,**options)
