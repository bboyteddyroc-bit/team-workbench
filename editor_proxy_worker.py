"""Experimental single-job proxy runner; deliberately not started by the hub.

Caller must provide an authorized source resolver and a shared-db context manager.
Do not integrate until process-crash recovery and export coordination are solved.
"""
from pathlib import Path
import editor_proxy_claims as claims
from editor_proxy_publish import produce
from editor_proxy_transcode import transcode
from editor_media_cache import fingerprint
from editor_proxy_process import ProxyStopUnconfirmed


def run_claim(db_context, key, token, source, output, probe, *, protected=False, stopping=lambda:False):
    """Run an existing claim. Caller must authorize and version-check source.

    A non-returning/crashed owner leaves the claim running, intentionally. It
    must never be reclaimed based solely on elapsed time or PID reuse.
    """
    source=Path(source); output=Path(output)
    def should_yield():
        with db_context() as db:
            return stopping() or claims.export_waiting(db,key,token)
    try:
        if should_yield():
            with db_context() as db:
                if not claims.requeue_after_stop(db,key,token):raise RuntimeError('proxy claim lost')
            return 'yielded'
        result=produce(source,output,transform=lambda s,t:transcode(s,t,should_yield,token=token if protected else None),probe=probe,fingerprint=fingerprint)
        if result=='yielded':
            with db_context() as db:
                if not claims.requeue_after_stop(db,key,token):raise RuntimeError('proxy claim lost')
            return result
        if result!='validated_metadata_only':raise RuntimeError('unexpected proxy result')
        with db_context() as db:
            if not claims.finish(db,key,token,'ready'):raise RuntimeError('proxy claim lost')
        return result
    except ProxyStopUnconfirmed:
        # Never release a claim while the encoder may still be running.
        raise
    except Exception:
        # Normal exceptions unwind run_owned only after its child exited, or
        # occurred before it was started. A hard process crash still needs
        # independent recovery and cannot be handled by this block.
        with db_context() as db:
            claims.finish(db,key,token,'failed')
        raise
