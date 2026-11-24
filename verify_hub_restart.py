"""Verify both real entrypoints without logging in or creating tasks."""
import json
import ssl
import sqlite3
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ROOT/'seedance-hub-ca.crt'))))
checks=[]
for url in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    with opener.open(url+'/',timeout=15) as response:
        page=response.read()
        checks.append(dict(url=url,status=response.status,html=b'<html' in page.lower(),bytes=len(page),material_manager=b'material-manager.js?v=manage2' in page))
    for asset in ('material-manager.js','material-manager.css','material-ui/main.js','material-ui/main.css'):
        with opener.open(url+'/static/'+asset,timeout=15) as response:
            assert response.status==200 and len(response.read())>100,asset
with sqlite3.connect((ROOT/'state'/'hub.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=10) as db:
    report={'entries':checks,'classification_error_column':any(r[1]=='error' for r in db.execute('PRAGMA table_info(asset_classification)')),
        'classification_counts':[dict(status=r[0],source=r[1],count=r[2]) for r in db.execute('SELECT status,source,count(*) FROM asset_classification GROUP BY status,source')],
        'task_counts':dict(db.execute('SELECT state,count(*) FROM tasks GROUP BY state'))}
print(json.dumps(report,ensure_ascii=False,indent=2))
assert all(c['status']==200 and c['html'] and c['material_manager'] for c in checks)
assert report['classification_error_column']
