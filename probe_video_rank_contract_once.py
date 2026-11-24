"""One bounded provider contract verification for user's requested video/rank.
Receipt is claimed BEFORE each POST; existing/uncertain calls are never replayed.
No secrets, signatures, raw creator contacts or media URLs are written/printed.
"""
from pathlib import Path
from datetime import datetime,timezone
import json,os,sys
from app import create_app
from kalodata_integration import QueryError
from video_case_kalodata import period
root=Path(__file__).resolve().parent
os.environ['HUB_ORIGIN']='http://127.0.0.1:8765'
app=create_app(root/'state',worker=False);svc=app.state.kalodata
receipt=root/'verification/video-rank-contract-20261117.json'
if receipt.exists():
    print('Existing receipt; no provider request repeated.');print(receipt.read_text(encoding='utf-8'));raise SystemExit(0)
with app.state.hub.db() as db:
    case=db.execute("SELECT id,video,handle FROM video_cases WHERE video='7693645068875418901'").fetchone()
    assert case
    assert not db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND state IN ('queued','running','submitting','waiting')",(case['id'],)).fetchone()
assert svc.secret(),'Configured Kalodata credential required; no query sent'
p=period();common={'region':'US','language':'en-US','currency':'USD','date_range':p['period_start']+'~'+p['period_end']}
report={'created':datetime.now(timezone.utc).isoformat(),'video':case['video'],'calls':[]}
with receipt.open('x',encoding='utf-8') as f:json.dump(report,f)
def save():receipt.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
calls=[('/video/detail',{**common,'video_id':case['video'],'need_extra':True}),('/video/rank',{**common,'sort_field':{'field':'views','type':'DESC'},'page_size':100,'page_number':1,'keyword':case['video']})]
for endpoint,payload in calls:
    call={'endpoint':endpoint,'request':payload,'state':'submitted_no_replay'};report['calls'].append(call);save()
    try:
        data=svc.post(endpoint,payload)
        call['state']='response_received';call['data_type']=type(data).__name__
        rows=data if isinstance(data,list) else data.get('data',[]) if isinstance(data,dict) and isinstance(data.get('data'),list) else [data] if isinstance(data,dict) else []
        call['row_count']=len(rows);exact=[r for r in rows if isinstance(r,dict) and str(r.get('video_id'))==case['video']]
        call['exact_match_count']=len(exact)
        if exact:
            call['actual_fields']=list(exact[0])
            allowed=('video_id','video_region','video_title','belonged_creator_id','belonged_creator_handle','views','revenue','digg_count','share_count','comment_count','ad','ai_video','ads_roas','ad_revenue_ratio','ad_view_ratio','creator_debut','publish_date','product_number','duration')
            call['exact_data']={k:exact[0][k] for k in allowed if k in exact[0]}
    except QueryError as exc:call.update(state='known_failure_or_unknown_no_replay',error=str(exc),code=exc.code)
    except Exception as exc:call.update(state='outcome_unknown_no_replay',error_type=type(exc).__name__)
    save()
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
