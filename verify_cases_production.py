"""Read-only case-library production smoke; no login/session creation or paid calls."""
from pathlib import Path
from datetime import datetime
import json,sqlite3,httpx,psutil
root=Path(__file__).resolve().parent
summary={'checked_at':datetime.now().isoformat(timespec='seconds'),'http':[],'listeners':[]}
for origin in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    with httpx.Client(verify=str(root/'seedance-hub-ca.crt'),trust_env=False,timeout=15) as client:
        home=client.get(origin+'/');assert home.status_code==200
        assert '/static/video-cases.js?v=1' in home.text
        js=client.get(origin+'/static/video-cases.js?v=1');assert js.status_code==200 and 'detailSerial' in js.text
        css=client.get(origin+'/static/video-cases.css?v=1');assert css.status_code==200 and 'top:44px' in css.text
        api=client.get(origin+'/api/intelligence/cases');assert api.status_code==401,api.status_code
        missing=client.get(origin+'/api/intelligence/nonexistent-cases-probe');assert missing.status_code==404,missing.status_code
        summary['http'].append({'origin':origin,'home':home.status_code,'latest_case_js':js.status_code,'latest_case_css':css.status_code,'registered_api_anonymous':api.status_code,'nonexistent_api':missing.status_code,'cache':js.headers.get('cache-control')})
with sqlite3.connect('file:'+str(root/'state/hub.sqlite3').replace('\\','/')+'?mode=ro',uri=True) as db:
    required=('video_cases','video_case_members','video_case_ideas','video_case_jobs','video_case_task_links')
    assert all(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone() for t in required)
    assert 'auto_enrichment_excluded' in [r[1] for r in db.execute('PRAGMA table_info(script_library)')]
    checks={'tasks':"state IN ('queued','submitting','running')",'voice_jobs':"state IN ('queued','running')",'edit_exports':"state IN ('queued','rendering')",'libtv_jobs':"state IN ('queued','running','importing')",'asset_classification':"status='running'",'ai_turns':"status='pending'",'feishu_uploads':"state IN ('queued','uploading')",'kalodata_jobs':"state IN ('queued','running')",'grouped_runs':"state IN ('queued','submitting','running')",'apify_runs':"state IN ('queued','submitting','running')",'video_enrichment_jobs':"state='running'",'script_creative_tasks':"state='generating'",'script_enrichment':"state='running'",'script_transcriptions':"state='running'",'ai_edit_jobs':"state IN ('queued','running','planning','rendering')",'video_case_jobs':"state IN ('queued','submitting','running')"}
    summary['active_counts']={t:db.execute('SELECT COUNT(*) FROM '+t+' WHERE '+condition).fetchone()[0] for t,condition in checks.items() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()}
    summary['case_counts']={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in required}
latest_backend=(root/'video_cases.py').stat().st_mtime
for connection in psutil.net_connections(kind='tcp'):
    if connection.status=='LISTEN' and connection.laddr.port in (8765,8443):
        process=psutil.Process(connection.pid)
        assert Path(process.cwd()).resolve()==root
        assert any(Path(arg).name=='run_service.py' for arg in process.cmdline())
        summary['listeners'].append({'port':connection.laddr.port,'pid':process.pid,'started':datetime.fromtimestamp(process.create_time()).isoformat(timespec='seconds'),'latest_backend_loaded_by_start_time':process.create_time()>=latest_backend})
print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
