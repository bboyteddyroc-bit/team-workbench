"""Read-only HTTP + production schema verification; no paid upstream requests."""
import json, sqlite3
from pathlib import Path
import httpx
import psutil
root=Path(__file__).resolve().parent
for address in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    with httpx.Client(verify=str(root/'seedance-hub-ca.crt'),trust_env=False,timeout=10) as c:
        r=c.get(address+'/');r.raise_for_status()
        assert 'apify-monitor.js?v=enrichment1' in r.text
        js=c.get(address+'/static/apify-monitor.js?v=enrichment1');js.raise_for_status()
        assert 'data-enrich-form' in js.text
        auth=c.get(address+'/api/intelligence/apify/accounts')
        assert auth.status_code==401,auth.status_code
        print(address,'HTTP=200, new UI served, anonymous API=401')
with sqlite3.connect('file:'+str(root/'state/hub.sqlite3').replace('\\','/')+'?mode=ro',uri=True) as db:
    for name in ('video_enrichment_config','video_enrichment_jobs','video_enrichment_calls','apify_profiles'):
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()
    print('enrichment configured/enabled:',db.execute('SELECT COUNT(*),COALESCE(SUM(enabled),0) FROM video_enrichment_config').fetchone())
    print('paid enrichment calls:',db.execute('SELECT COUNT(*) FROM video_enrichment_calls').fetchone()[0])
    print('Apify snapshots preserved:',db.execute('SELECT COUNT(*) FROM apify_snapshots').fetchone()[0])
for c in psutil.net_connections(kind='tcp'):
    if c.status=='LISTEN' and c.laddr.port in (8765,8443):
        p=psutil.Process(c.pid)
        # Windows venv redirector may spawn the base executable as its child.
        assert any(str(root/'.venv/Scripts/python.exe').lower()==str(Path(q.cmdline()[0])).lower() for q in [p,*p.parents()]),p.cmdline()
        print('listener',c.laddr.port,'project .venv confirmed')
