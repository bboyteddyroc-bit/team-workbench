"""Read-only result check for the requested case; never calls upstream."""
from pathlib import Path
import json,sqlite3
root=Path(__file__).resolve().parent
with sqlite3.connect('file:'+str(root/'state/hub.sqlite3').replace('\\','/')+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    case=db.execute("SELECT * FROM video_cases WHERE video='7704642505480129822'").fetchone()
    if not case:raise RuntimeError('case missing')
    source=json.loads(case['source']);ai=json.loads(case['ai'])
    print(json.dumps({'video':case['video'],'kalodata':source.get('kalodata'),'ai_generated':ai.get('generated_at'),'ai_basis':ai.get('basis'),'ai_nonempty_fields':[k for k,v in ai.get('fields',{}).items() if v],'uncertainties':ai.get('uncertainties',[]),'jobs':[dict(r) for r in db.execute('SELECT j.id,j.kind,j.state,j.error,c.stage FROM video_case_jobs j LEFT JOIN video_case_checkpoints c ON c.job=j.id WHERE j.case_id=? ORDER BY j.created DESC',(case['id'],))]},ensure_ascii=False,indent=2),flush=True)
