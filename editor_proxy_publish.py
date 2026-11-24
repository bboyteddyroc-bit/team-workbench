"""Fail-closed proxy staging. Experimental; not wired to application.

The caller owns authorization, scheduling, media transformation and probe functions.
A successful metadata check is not proof of frame-accurate synchronization.
"""
import os
import sys
import uuid
from pathlib import Path
from editor_proxy_policy import validate_proxy


def produce(source, target, *, transform, probe, fingerprint):
    source=Path(source).resolve();target=Path(target).resolve()
    if source==target:raise ValueError('source and proxy must differ')
    if target.exists():raise FileExistsError('refusing to replace existing proxy')
    if not target.parent.is_dir():raise ValueError('proxy directory unavailable')
    before=fingerprint(source);source_duration,source_streams=probe(source)
    temp=target.with_name('.'+target.stem+'.'+uuid.uuid4().hex+'.part.mp4')
    try:
        result=transform(source,temp)
        if result!='complete':return result
        if not temp.is_file() or not temp.stat().st_size:raise ValueError('empty proxy')
        duration,streams=probe(temp)
        ok,reason=validate_proxy(source_duration,source_streams,duration,streams)
        if not ok:raise ValueError('proxy rejected: '+reason)
        if fingerprint(source)!=before:raise ValueError('source changed during conversion')
        # Hard-link publication is exclusive: a concurrent publisher cannot be overwritten.
        os.link(temp,target)
        return 'validated_metadata_only'
    finally:
        active=sys.exc_info()[1]
        try:
            temp.unlink(missing_ok=True)
        except OSError as cleanup_error:
            # Never mask an unconfirmed child exit with a cleanup error: callers
            # use the original exception to decide whether releasing is safe.
            if active is None:raise
            if hasattr(active,'add_note'):
                active.add_note('Proxy temporary file could not be removed: '+str(cleanup_error))
