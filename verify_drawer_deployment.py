"""Read-only release smoke: served asset bytes, unauth API boundary, real case metric projections.
No credentials, login sessions, provider calls or production DB writes.
"""
from pathlib import Path
import json,hashlib,sqlite3,httpx
from video_case_presentation import metric_projection,tag_projection
root=Path(__file__).resolve().parent
report={'release':'case-gallery-drawer-20261117','servers':[],'real_cases':[]}
for origin in ('http://127.0.0.1:8765','https://192.168.100.10:8443'):
    with httpx.Client(verify=False,timeout=20,trust_env=False) as c:
        home=c.get(origin+'/');assert 'video-cases.js?v=gallery-drawer-20261117' in home.text and 'video-cases.css?v=gallery-drawer-20261117' in home.text
        row={'origin':origin,'root_status':home.status_code,'cache_version':'gallery-drawer-20261117','assets':[]}
        for asset in ('video-cases.js','video-cases.css'):
            r=c.get(origin+'/static/'+asset);digest=hashlib.sha256(r.content).hexdigest();local=hashlib.sha256((root/'static'/asset).read_bytes()).hexdigest()
            assert r.status_code==200 and digest==local,(origin,asset,r.status_code)
            row['assets'].append({'name':asset,'bytes':len(r.content),'matches_release':digest==local,'sha256':digest})
        r=c.get(origin+'/api/intelligence/cases');row['unauthenticated_cases_status']=r.status_code;assert r.status_code in (401,403)
        assert row['root_status']==200
        report['servers'].append(row)
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    report['production_fixture_count']=db.execute("SELECT COUNT(*) FROM video_cases WHERE id LIKE 'gallery-proof-%'").fetchone()[0];assert report['production_fixture_count']==0
    for r in db.execute("SELECT id,source,human,ai FROM video_cases WHERE video IN ('7704642505480129822','7708328890967608590')"):
        row={k:json.loads(r[k]) for k in ('source','human','ai')}
        report['real_cases'].append({'id':r['id'],'metrics':metric_projection(row),'tagging':tag_projection(row),'human_untouched':row['human']=={}})
assert len(report['real_cases'])==2
(root/'verification/cases-drawer-deployment-20261117.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2),flush=True)
