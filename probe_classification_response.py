"""One real image recognition probe. Read-only DB, no queue mutation or retries.
Prints response structure and bounded classification answer, never request headers/image/key.
"""
import contextlib
import io
import json
import sqlite3
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.fernet import Fernet
import asset_classification

root = Path(__file__).resolve().parent
state = root / 'state'

@contextlib.contextmanager
def database():
    db = sqlite3.connect((state / 'hub.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()

with database() as db:
    asset = db.execute("SELECT a.id FROM assets a LEFT JOIN asset_classification c ON c.asset_id=a.id WHERE a.mime LIKE 'image/%' AND COALESCE(c.source,'')<>'manual' ORDER BY a.created DESC LIMIT 1").fetchone()
if not asset:
    raise SystemExit('No eligible image')
hub = SimpleNamespace(db=database, assets=state / 'assets', cipher=Fernet((state / 'vault.key').read_bytes()))
original = urllib.request.build_opener
report = {'requests': 0, 'database_mode': 'read-only'}

def describe(value):
    if isinstance(value, dict):
        return {str(k): describe(v) if k in ('choices','message','content','finish_reason','text','type','error') else type(v).__name__ for k,v in value.items()}
    if isinstance(value, list):
        return [describe(v) for v in value[:2]]
    if isinstance(value, str):
        return value[:600]
    return value

class Capture:
    def __init__(self, opener):
        self.opener = opener
    def open(self, request, **kwargs):
        report['requests'] += 1
        try:
            with self.opener.open(request, **kwargs) as response:
                data = response.read(2 * 1024 * 1024)
                report['http_status'] = response.status
                report['content_type'] = response.headers.get('Content-Type')
        except urllib.error.HTTPError as exc:
            report['http_status'] = exc.code
            report['error_body_bytes'] = len(exc.read(8192))
            raise
        try:
            result = json.loads(data)
            report['response_shape_and_answer'] = describe(result)
        except Exception:
            report['response_not_json'] = True
        return io.BytesIO(data)

try:
    with patch('urllib.request.build_opener', side_effect=lambda *args: Capture(original(*args))):
        report['parsed_category'] = asset_classification.recognize(hub, hub.assets / asset['id'])
except ValueError as exc:
    report['parser_error'] = str(exc)
except Exception as exc:
    report['failure_type'] = type(exc).__name__
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
