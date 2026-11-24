"""One-shot same-object API diagnosis. No case creation, media, AI, retries or replay.
Claim an audit receipt before each POST, return only allowlisted fields. Existing receipt stops all calls.
"""
from pathlib import Path
from datetime import datetime,timezone
import os,json,re
import httpx
from app import create_app
from kalodata_integration import BASE_URL
from video_case_skill import headers
root=Path(__file__).resolve().parent
receipt=root/'verification/kalodata-known-video-7707267947466607885-20261117.json'
if receipt.exists():
    print('Existing receipt; NO provider request repeated.',flush=True)
    print(receipt.read_text(encoding='utf-8'),flush=True)
    raise SystemExit(0)
os.environ['HUB_ORIGIN']='http://127.0.0.1:8765'
app=create_app(root/'state',worker=False);svc=app.state.kalodata
secret=svc.secret()
assert secret,'Kalodata not configured; no request sent'
report={'created':datetime.now(timezone.utc).isoformat(),'video_id':'7707267947466607885','creator_id_from_public_detail':'6868879889312351237','web_handle':'mydlvz1','web_logged_in':False,'web_metrics_are_demo':True,'calls':[],'case_writes':0,'media_calls':0,'ai_calls':0}
with receipt.open('x',encoding='utf-8') as f:json.dump(report,f)
def save():receipt.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
allowed=('video_id','video_region','video_title','belonged_creator_id','belonged_creator_handle','product_number','revenue','sales_volumn','views','video_gpm','ads_views','ads_roas','ads_period','digg_count','share_count','comment_count','collect_count','collects','ad_cpa','revenue_trend','ad','ad_view_ratio','ad_revenue_ratio','ad_spend','ads_spend','ads_cost','ad_cost','ads_revenue','ads_gmv','ad_revenue','duration','ai_video','creator_debut','publish_date','revenue_growth_rate')
def safe_message(data):
    text=str(data.get('message',''))
    # Only known business categories, never arbitrary server text/URLs/credentials.
    if text.strip().lower() in ('video not found','video not found.'):return 'video not found'
    return 'not provided' if not text else 'unrecognized provider message (not echoed)'
def invoke(endpoint,payload):
    call={'endpoint':endpoint,'request':payload,'state':'submitted_no_replay','started':datetime.now(timezone.utc).isoformat()}
    report['calls'].append(call);save()
    try:
        with httpx.Client(timeout=30,trust_env=False,follow_redirects=False) as c:
            response=c.post(BASE_URL+endpoint,json=payload,headers={'secret-key':secret,**headers()})
        call['http_status']=response.status_code
        data=response.json()
        call['state']='response_received';call['finished']=datetime.now(timezone.utc).isoformat()
        if not isinstance(data,dict):
            call['body_type']=type(data).__name__;save();return False
        call['envelope_fields']=list(data);call['success']=data.get('success') if type(data.get('success')) is bool else None
        code=str(data.get('code',''));call['code']=code if re.fullmatch(r'[A-Za-z0-9_-]{0,40}',code) else 'redacted'
        call['message']=safe_message(data);call['cached']=data.get('cached') if type(data.get('cached')) is bool else None
        business=data.get('data');call['data_type']=type(business).__name__
        rows=business if isinstance(business,list) else [business] if isinstance(business,dict) else []
        call['row_count']=len(rows)
        exact=[r for r in rows if isinstance(r,dict) and str(r.get('video_id'))==report['video_id']]
        call['exact_match_count']=len(exact)
        if exact:
            call['actual_field_names']=list(exact[0]);call['exact_data']={k:exact[0][k] for k in allowed if k in exact[0]}
        elif isinstance(business,dict):call['data_field_names']=list(business)
        save()
        return response.status_code==200 and data.get('success') is False and call['message']=='video not found'
    except Exception as exc:
        call['state']='outcome_unknown_no_replay';call['error_type']=type(exc).__name__;save();return False
common={'region':'US','language':'zh-CN','currency':'USD','date_range':'2026-10-17~2026-11-15'}
not_found=invoke('/video/detail',{**common,'video_id':report['video_id'],'need_extra':True})
if not_found:
    invoke('/video/rank',{**common,'creator_id':report['creator_id_from_public_detail'],'sort_field':{'field':'revenue','type':'DESC'},'page_size':100,'page_number':1})
else:report['rank_not_sent']='No explicit known detail not-found; no fallback on unknown or success';save()
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
