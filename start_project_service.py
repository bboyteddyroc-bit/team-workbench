"""Managed-job shim: select this repository's existing Python environment."""
import os
import sys
from pathlib import Path
root=Path(__file__).resolve().parent
runtime=root/'.venv/Scripts/python.exe'
if not runtime.is_file():
    raise RuntimeError('Recover the project .venv before starting services')
os.chdir(root)
os.execv(str(runtime),[str(runtime),'-B',str(root/'run_service.py'),*sys.argv[1:]])
