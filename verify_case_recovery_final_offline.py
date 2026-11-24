"""Final local verification when runtime's managed-start barrier prevents relaunch.
Reads the real case and listener state; never starts a service or calls any provider.
"""
import sqlite3,json,hashlib,ast
from pathlib import Path
import psutil
from video_case_fields import projection
from video_case_presentation import metric_projection
root=Path(__file__).resolve().parent
for name in ('video_cases.py','video_case_analysis.py','video_case_fields.py','video_case_recovery.py','video_case_skill.py','kalodata_integration.py','video_case_kalodata.py'):
    ast.parse((root/name).read_text(encoding='utf-8'))
report={'python_syntax':'passed','listeners':[],'regression':{},'case':{}}
for c in psutil.net_connections(kind='tcp'):
    if c.status=='LISTEN' and c.laddr.port in (8765,8443,8000):report['listeners'].append({'port':c.laddr.port,'pid':c.pid})
log=(root/'verification/cases-recovery-acceptance-regression-20261117.log').read_text(encoding='utf-8',errors='replace')
assert 'Ran 68 tests' in log and log.rstrip().endswith('OK')
report['regression']={'tests':68,'passed':True,'duration_seconds':76.206}
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    row=dict(db.execute("SELECT * FROM video_cases WHERE id='2d9151c8a5844d73905644031f330ee7'").fetchone())
    for key in ('source','human','ai'):row[key]=json.loads(row[key])
    fields=projection(row);job=dict(db.execute("SELECT id,state,wait_count,error,error_code,next_attempt FROM video_case_jobs WHERE id='a57bca742d2c436fa8a6747bb4be1f39'").fetchone())
    assert job['state']=='ready' and job['next_attempt'] is None and not job['error']
    assert row['human']=={} and row['ai'].get('visual_correction',{}).get('checked_frames')==list(range(9))
    assert fields['merchant_visible']['missing']
    assert not row['ai']['fields']['hook_example'] and not row['transcript']
    metrics=metric_projection(row);assert all(m['missing'] for m in metrics)
    assert db.execute('SELECT COUNT(*) FROM video_case_recovery_repairs WHERE job=?',(job['id'],)).fetchone()[0]==1
    assert db.execute('SELECT COUNT(*) FROM video_case_draft_corrections WHERE case_id=?',(row['id'],)).fetchone()[0]==1
    report['case']={'video':row['video'],'job':job,'human_unchanged':True,'review':'待人工审核','nine_frames_checked':True,'original_draft_retained':True,'metrics_available':False,'transcript_chars':0}
    report['production_fixture_count']=db.execute("SELECT COUNT(*) FROM video_cases WHERE id LIKE 'gallery-proof-%'").fetchone()[0];assert report['production_fixture_count']==0
report['artifacts']={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ('static/video-cases.js','static/video-cases.css')}
report['deployment_blocker']='CONTINUATION_ALREADY_COMPLETED: managed service relaunch denied after verified idle stop; service must be restarted through existing user launcher. No bypass attempted.'
path=root/'verification/cases-recovery-final-state-20261117.json'
with path.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
