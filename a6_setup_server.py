"""Temporary, local-only settings-access server; background worker disabled."""
import os
from pathlib import Path
root=Path(__file__).resolve().parent
import sys
runtime=root/'.venv/Scripts/python.exe'
if os.environ.get('A6_SETUP_VENV')!='1':
 os.environ['A6_SETUP_VENV']='1'
 os.execv(str(runtime),[str(runtime),'-B',str(root/'a6_setup_server.py')])
os.chdir(root)
os.environ['HUB_STATE']=str(root/'state')
os.environ['HUB_ORIGIN']='http://127.0.0.1:8766'
from app import create_app
import uvicorn
print('A6 settings: http://127.0.0.1:8766',flush=True)
uvicorn.run(create_app(worker=False),host='127.0.0.1',port=8766,access_log=False,server_header=False)
