"""Read-only production recovery status/asset smoke; never calls Kalodata or AI."""
from pathlib import Path
import sqlite3,json,hashlib,sys
import httpx
root=Path(__file__).resolve().parent
report={'servers':[],'case':{}}
for origin in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    with httpx.Client(verify=False,timeout=15,trust_env=False) as c:
        r=c.get(origin+'/');assert r.status_code==200
        assert 'video-cases.js?v=recovery-source-first-20261117' in r.text
        assert 'video-cases.css?v=recovery-source-first-20261117' in r.text
        assets={}
        for name in ('video-cases.js','video-cases.css'):
            r=c.get(origin+'/static/'+name);assert r.status_code==200
            assets[name]=hashlib.sha256(r.content).hexdigest()==hashlib.sha256((root/'static'/name).read_bytes()).hexdigest();assert assets[name]
        status=c.get(origin+'/api/intelligence/cases').status_code;assert status in (401,403)
        report['servers'].append({'origin':origin,'assets_match':assets,'unauthenticated_api_status':status})
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    row=db.execute("SELECT id,video,source,human,ai,transcript FROM video_cases WHERE id='2d9151c8a5844d73905644031f330ee7'").fetchone()
    columns={r[1] for r in db.execute('PRAGMA table_info(video_case_jobs)')}
    assert {'wait_count','next_attempt','wait_deadline','error_code'}<=columns
    job=db.execute("SELECT id,kind,state,error,error_code,wait_count,next_attempt,wait_deadline,updated FROM video_case_jobs WHERE id='a57bca742d2c436fa8a6747bb4be1f39'").fetchone()
    report['case']={'video':row['video'],'human_unchanged':json.loads(row['human'])=={},'ai_generated':json.loads(row['ai']).get('generated_at'),'transcript_chars':len(row['transcript'] or ''),'source_has_kalodata':bool(json.loads(row['source']).get('kalodata')),'job':dict(job)}
    stage=db.execute('SELECT stage FROM video_case_checkpoints WHERE job=?',(job['id'],)).fetchone();report['case']['stage']=stage[0] if stage else ''
    media=root/'state/case-analysis'/row['id']/'source.mp4';report['case']['video_bytes']=media.stat().st_size if media.exists() else 0
    report['case']['frames']=len(list(media.parent.glob('frame-*.jpg')))
    report['historical_detail_job']=dict(db.execute("SELECT id,state,error FROM video_case_jobs WHERE id='ce7147fe0d9944629e98aa08e2e00d7d'").fetchone())
    report['production_fixture_count']=db.execute("SELECT COUNT(*) FROM video_cases WHERE id LIKE 'gallery-proof-%'").fetchone()[0];assert report['production_fixture_count']==0
text=json.dumps(report,ensure_ascii=False,indent=2)
if len(sys.argv)>1:
    out=root/'verification'/sys.argv[1]
    with out.open('x',encoding='utf-8') as f:f.write(text)
print(text,flush=True)
