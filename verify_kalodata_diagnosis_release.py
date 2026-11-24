"""Read-only release smoke for the CDN/error-mapping fix. No upstream calls."""
import json,sqlite3,httpx,psutil
from pathlib import Path
from datetime import datetime
root=Path(__file__).resolve().parent
latest=max((root/name).stat().st_mtime for name in ('kalodata_integration.py','video_case_analysis.py'))
result={'checked_at':datetime.now().isoformat(timespec='seconds'),'http':[],'listeners':[]}
for origin in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    with httpx.Client(verify=str(root/'seedance-hub-ca.crt'),trust_env=False,timeout=15) as client:
        home=client.get(origin+'/');assert home.status_code==200
        api=client.get(origin+'/api/intelligence/cases');assert api.status_code==401
        js=client.get(origin+'/static/video-cases.js?v=1');assert js.status_code==200
        assert js.content.decode('utf-8')==(root/'static/video-cases.js').read_text(encoding='utf-8')
        result['http'].append({'origin':origin,'home':200,'api_anonymous':401,'current_case_js':True})
for conn in psutil.net_connections(kind='tcp'):
    if conn.status=='LISTEN' and conn.laddr.port in (8765,8443,8000):
        p=psutil.Process(conn.pid);assert Path(p.cwd()).resolve()==root
        assert any(Path(arg).name=='run_service.py' for arg in p.cmdline())
        assert p.create_time()>latest,'Stale backend'
        result['listeners'].append({'port':conn.laddr.port,'pid':p.pid,'fix_loaded_by_process_start_time':True})
assert {r['port'] for r in result['listeners']}=={8765,8443,8000}
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    result['active_case_jobs']=db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE state IN ('queued','submitting','running')").fetchone()[0]
    result['case_jobs_preserved']=db.execute('SELECT COUNT(*) FROM video_case_jobs').fetchone()[0]
print(json.dumps(result,ensure_ascii=True,indent=2),flush=True)
(root/'verification/kalodata-diagnosis-release-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
