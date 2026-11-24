"""Static component harness of FINAL assets. Only isolated DB fixtures, no prod session or server.
Real API persistence already covered separately. Harness stubs GET only and rejects writes/provider calls.
"""
from pathlib import Path
import sqlite3,json,re,base64
from video_case_presentation import metric_projection,tag_projection,TAG_CATEGORIES
root=Path(__file__).resolve().parent;state=root/'verification/cases-preview-state'
with sqlite3.connect('file:'+(state/'hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row;items=[]
    for r in db.execute("SELECT * FROM video_cases WHERE id LIKE 'gallery-proof-%' ORDER BY created DESC"):
        row=dict(r)
        for k in ('source','human','ai'):row[k]=json.loads(row[k])
        row.update(mine=True,collectors=[{'username':'隔离验收'}],ideas=[],jobs=[],tasks=[],latest_jobs=[],review_status='待审核',case_number='VC-'+row['id'][-3:],metrics=metric_projection(row),tagging=tag_projection(row),tag_categories=TAG_CATEGORIES)
        cover=state/'case-covers'/(row['id']+'.img');row['cover_url']='data:image/jpeg;base64,'+base64.b64encode(cover.read_bytes()).decode() if cover.exists() else None
        items.append(row)
styles=[]
for src in re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"',(root/'static/index.html').read_text(encoding='utf-8')):
    if src.startswith('/static/'):
        path=root/src.lstrip('/').split('?')[0]
        if path.is_file():styles.append(path.read_text(encoding='utf-8'))
data=json.dumps(items,ensure_ascii=False).replace('</','<\\/')
script=(root/'static/video-cases.js').read_text(encoding='utf-8')
body='<!doctype html><html lang="zh-CN" data-theme="obsidian"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>视频案例库 · 最终样式隔离验收</title><style>'+''.join(styles)+'</style><body><section id="intelligence"><div class="intel-heading"><h1>Seedance · 视频案例库</h1></div><p style="font-size:12px;color:var(--fg-mute)">静态隔离验收 · 示例指标非真实表现 · 禁止付费调用与写入</p><div id="harness-host"></div></section><script>const fixture='+data+';window.fetch=async(url,options={})=>{if(options.method)return new Response(JSON.stringify({detail:"静态验收禁止写入"}),{status:403});const u=new URL(url,location.href),id=u.pathname.split("/").pop();let result;if(id!=="cases")result=fixture.find(x=>x.id===id);else {let rows=fixture.filter(x=>!u.searchParams.get("q")||JSON.stringify(x).includes(u.searchParams.get("q")));const start=Number(u.searchParams.get("offset")||0),size=Number(u.searchParams.get("limit")||48);result={items:rows.slice(start,start+size),total:rows.length};}return new Response(JSON.stringify(result),{status:200,headers:{"Content-Type":"application/json"}});};</script><script>'+script+'</script><script>window.hubVideoCases.open(document.getElementById("harness-host"));</script></body></html>'
path=root/'verification/cases-final-static-harness.html';path.write_text(body,encoding='utf-8');print(str(path),flush=True)
