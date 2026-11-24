"""Read-only HTTP/TLS, process-version and shared DB release verification. No provider POSTs."""
from pathlib import Path
from datetime import datetime,timezone
import sqlite3,json,hashlib,ssl
import httpx,psutil
root=Path(__file__).resolve().parent
report={'verified':datetime.now(timezone.utc).isoformat(),'servers':[],'provider_calls_sent':0}
for origin in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    tls=ssl.create_default_context(cafile=str(root/'seedance-hub-ca.crt')) if origin.startswith('https') else True
    with httpx.Client(verify=tls,timeout=15,trust_env=False) as client:
        r=client.get(origin+'/');assert r.status_code==200
        assert 'video-cases.js?v=exact-data-lane-20261117' in r.text and 'video-cases.css?v=exact-data-lane-20261117' in r.text
        hashes={}
        for name in ('video-cases.js','video-cases.css'):
            response=client.get(origin+'/static/'+name);assert response.status_code==200
            hashes[name]=hashlib.sha256(response.content).hexdigest();assert hashes[name]==hashlib.sha256((root/'static'/name).read_bytes()).hexdigest()
        status=client.get(origin+'/api/intelligence/cases').status_code;assert status==401
        report['servers'].append({'origin':origin,'index_status':r.status_code,'assets_sha256':hashes,'unauthenticated_cases_status':status,'tls_verified':origin.startswith('https')})
latest=max((root/name).stat().st_mtime for name in ('app.py','video_cases.py','video_case_kalodata.py','kalodata_integration.py','video_case_commercial.py','video_case_data_status.py'))
report['listeners']=[]
for c in psutil.net_connections(kind='tcp'):
    if c.status=='LISTEN' and c.laddr.port in (8765,8443,8000):
        p=psutil.Process(c.pid);assert p.create_time()>latest;assert Path(p.cwd()).resolve()==root
        report['listeners'].append({'port':c.laddr.port,'pid':c.pid,'mode':p.cmdline()[-1],'started_after_backend_changes':True})
assert {x['port'] for x in report['listeners']}=={8765,8443,8000}
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    report['production_fixture_count']=db.execute("SELECT COUNT(*) FROM video_cases WHERE id LIKE 'gallery-proof-%'").fetchone()[0];assert report['production_fixture_count']==0
    report['recovered_media_job_state']=db.execute("SELECT state FROM video_case_jobs WHERE id='a57bca742d2c436fa8a6747bb4be1f39'").fetchone()[0];assert report['recovered_media_job_state']=='ready'
    report['running_case_jobs']=db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE state IN ('queued','submitting','running','waiting')").fetchone()[0]
receipt=json.loads((root/'verification/video-rank-contract-20261117.json').read_text(encoding='utf-8'));report['existing_contract_receipt_call_count']=len(receipt['calls']);assert len(receipt['calls'])==2
output=root/'verification/cases-fast-data-release-20261117.json'
with output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
print(json.dumps(report,ensure_ascii=False,indent=2))
