"""Conservative canonical identity for an entire generation submission."""
import hashlib
import json
from fastapi import HTTPException


def signature(data):
    # JSON key order and omitted documented defaults do not change meaning.
    # Retain unrecognized fields conservatively: never guess that a changed input
    # is safe to alias to an existing (possibly paid) generation.
    items = data.get('items', [data])
    if not isinstance(items, list) or not items or any(not isinstance(i, dict) for i in items):
        raise HTTPException(400, '创作内容格式有误')
    normalized = []
    for item in items:
        value = {k: v for k, v in item.items() if k != 'request_key'}
        if 'items' not in data:
            value.pop('account_id', None)
            value.pop('project_id', None)
        for key, default in [('duration', 5), ('count', 1), ('model', 'auto'), ('mode', 'omni'), ('assets', [])]:
            value.setdefault(key, default)
        if isinstance(value.get('prompt'), str):
            value['prompt'] = value['prompt'].strip()
        normalized.append(value)
    envelope = {k: v for k, v in data.items() if k not in ('items', 'request_key')}
    if 'items' not in data:
        envelope = {}
    envelope.update(account_id=str(data.get('account_id', 'pool')), project_id=data.get('project_id') or None, items=normalized)
    try:
        raw = json.dumps(envelope, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise HTTPException(400, '创作参数格式有误') from None
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
