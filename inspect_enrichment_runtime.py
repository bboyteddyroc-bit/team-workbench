"""Read-only diagnostics; never print credentials or stored query payloads."""
import json, sqlite3
from pathlib import Path
import psutil
root=Path(__file__).resolve().parent
schema=json.loads((root.parents[2]/'kalodata-re/openapi.json').read_text(encoding='utf-8'))
for k,v in schema.get('components',{}).get('schemas',{}).items():
    if 'video' in k.lower() and 'detail' in k.lower():
        print('SCHEMA', k, json.dumps(v,ensure_ascii=False)[:14000])
with sqlite3.connect('file:'+str(root/'state/hub.sqlite3').replace('\\','/')+'?mode=ro',uri=True) as db:
    checks={'tasks':"state IN ('queued','submitting','running')",'voice_jobs':"state IN ('queued','running')",'edit_exports':"state IN ('queued','rendering')",'libtv_jobs':"state IN ('queued','running','importing')",'asset_classification':"status='running'",'ai_turns':"status='pending'",'feishu_uploads':"state IN ('queued','uploading')",'kalodata_jobs':"state IN ('queued','running')",'apify_runs':"state IN ('queued','submitting','running')",'video_enrichment_jobs':"state='running'"}
    for table,condition in checks.items():
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
            print('ACTIVE',table,db.execute('SELECT COUNT(*) FROM '+table+' WHERE '+condition).fetchone()[0])
for c in psutil.net_connections(kind='tcp'):
    if c.status=='LISTEN' and c.laddr.port in (8765,8443):
        p=psutil.Process(c.pid)
        print('LISTENER',c.laddr.port,p.pid,p.exe(),p.cwd(),p.cmdline())
