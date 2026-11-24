"""Post-reload verification for the automatic two-tab case release; read-only upstream."""
from pathlib import Path
from datetime import datetime
import json,sqlite3,httpx,psutil
root=Path(__file__).resolve().parent
result={'checked_at':datetime.now().isoformat(timespec='seconds'),'http':[],'listeners':[]}
latest=max((root/name).stat().st_mtime for name in ('video_cases.py','video_case_analysis.py','video_case_kalodata.py'))
for origin in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    with httpx.Client(verify=str(root/'seedance-hub-ca.crt'),trust_env=False,timeout=15) as client:
        home=client.get(origin+'/');assert home.status_code==200
        js=client.get(origin+'/static/video-cases.js?v=1');assert js.status_code==200
        assert js.content.decode('utf-8')==(root/'static/video-cases.js').read_text(encoding='utf-8')
        assert '保存并自动分析' in js.text and "['ideas','个人意见']" in js.text
        assert 'if(false)' not in js.text and '添加链接不会自动产生费用' not in js.text
        api=client.get(origin+'/api/intelligence/cases');assert api.status_code==401
        result['http'].append({'origin':origin,'home':home.status_code,'exact_latest_js':True,'api_requires_login':True,'cache':js.headers.get('cache-control')})
for conn in psutil.net_connections(kind='tcp'):
    if conn.status=='LISTEN' and conn.laddr.port in (8765,8443,8000):
        p=psutil.Process(conn.pid)
        assert Path(p.cwd()).resolve()==root
        assert any(Path(arg).name=='run_service.py' for arg in p.cmdline())
        assert p.create_time()>=latest,'Old backend process still running'
        result['listeners'].append({'port':conn.laddr.port,'pid':p.pid,'latest_modules_loaded_by_start_time':True})
assert {x['port'] for x in result['listeners']}=={8765,8443,8000}
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    for table in ('video_case_checkpoints','video_case_reviews'):
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
    row=db.execute("SELECT id,ai FROM video_cases WHERE video='7704642505480129822'").fetchone()
    ai=json.loads(row['ai']);substantive=any(v for k,v in ai.get('fields',{}).items() if k not in ('notes','tags','basis'))
    result['existing_case']={'video':'7704642505480129822','substantive_analysis':substantive,'expected_review_status':'数据不足' if ai.get('generated_at') and not substantive else '待审核','jobs':[dict(j) for j in db.execute('SELECT id,kind,state,error FROM video_case_jobs WHERE case_id=? ORDER BY created',(row['id'],))]}
    result['active_case_jobs']=db.execute("SELECT COUNT(*) FROM video_case_jobs WHERE state IN ('queued','submitting','running')").fetchone()[0]
out=root/'verification/cases-auto-release-smoke.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
