"""Safe live metadata check; no Actor invocation."""
import urllib.request,urllib.error,json
from pathlib import Path
import sqlite3
root=Path(__file__).resolve().parent
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for path in ['/static/apify-pool.js?v=1','/static/apify-pool.css?v=1']:
 data=op.open('http://127.0.0.1:8765'+path,timeout=10).read()
 assert data==(root/'static'/path.split('/')[-1].split('?')[0]).read_bytes()
 print('Live asset matches:',path)
try:op.open('http://127.0.0.1:8765/api/intelligence/apify/pool',timeout=10)
except urllib.error.HTTPError as e:
 assert e.code==401;print('Anonymous pool rejected: PASS')
c=sqlite3.connect('file:'+str(root/'state/hub.sqlite3')+'?mode=ro',uri=True)
print('Migrated keys:',c.execute('SELECT COUNT(*) FROM apify_keys').fetchone()[0])
