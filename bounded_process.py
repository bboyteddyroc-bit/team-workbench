"""Bound subprocess lifetime, including child processes on Windows."""
import os
import signal
import subprocess


def run(args, *, timeout, **kwargs):
    if os.name!='nt':kwargs['start_new_session']=True
    process=subprocess.Popen(args,**kwargs)
    try:
        stdout,stderr=process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name=='nt':
            # Kill while parent still exists, so taskkill can identify descendants.
            try:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except (OSError,subprocess.TimeoutExpired):
                pass
            finally:
                if process.poll() is None:process.kill()
        else:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        process.communicate(timeout=15)
        raise subprocess.TimeoutExpired(args,timeout) from None
    return subprocess.CompletedProcess(args,process.returncode,stdout,stderr)
