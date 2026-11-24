"""Owned subprocess lifecycle for preview work; no worker is started on import.

Not wired to production: caller must ensure atomic cross-process coordination,
source authorization and isolated temporary paths before using this helper.
"""
import subprocess
import time


class ProxyProcessError(RuntimeError):
    pass


class ProxyStopUnconfirmed(ProxyProcessError):
    """The owned child could not be confirmed stopped; do not release claim."""
    pass


def run_owned(args, should_yield, *, timeout=1800, interval=0.25, low_priority=False, protected=False):
    """Run one child; on yield return only after child is verified stopped.

    Returns 'complete' or 'yielded'. Failure/timeout raises ProxyProcessError.
    Do not publish output until independent file and timing validation succeeds.
    """
    if timeout<=0 or interval<=0:raise ValueError('invalid timeout or interval')
    if protected:
        return run_protected(args, should_yield, timeout, interval, protected if isinstance(protected,str) else None)

    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    if low_priority:
        flags |= getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
    proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL,creationflags=flags)
    try:
        # From the moment Popen succeeds every exception must pass through
        # the cleanup below; even clock failures cannot leak a child.
        start=time.monotonic()
        while True:
            try:
                code=proc.wait(timeout=interval)
                if code:raise ProxyProcessError('proxy process failed')
                return 'complete'
            except subprocess.TimeoutExpired:
                if should_yield():
                    proc.terminate()
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill();proc.wait(timeout=5)
                    return 'yielded'
                if time.monotonic()-start>timeout:raise ProxyProcessError('proxy process timed out')
    finally:
        try:
            if proc.poll() is None:
                proc.kill();proc.wait(timeout=5)
        except Exception as exc:
            raise ProxyStopUnconfirmed('owned proxy process stop could not be verified') from exc


def run_protected(args, should_yield, timeout, interval, token):
    from editor_proxy_winjob import OwnedJob, drain, recover_job
    if should_yield():return 'yielded'
    try:
        job=OwnedJob(args,token)
    except Exception:
        if token:
            try:recover_job(token)
            except Exception as exc:raise ProxyStopUnconfirmed('proxy startup cleanup unconfirmed') from exc
        raise
    with job:
        try:
            deadline=time.monotonic()+timeout
            while True:
                code=job.wait(max(1,int(interval*1000)))
                if code is not None:
                    if code:raise ProxyProcessError('proxy process failed')
                    return 'complete'
                if should_yield():return 'yielded'
                if time.monotonic()>=deadline:raise ProxyProcessError('proxy process timed out')
        finally:
            try:drain(job.job)
            except Exception as exc:raise ProxyStopUnconfirmed('proxy Job Object did not drain') from exc
