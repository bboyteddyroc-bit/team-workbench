"""Isolated GET-only renderer verification of data-first states; not production data."""
from pathlib import Path
import json
from video_case_fields import projection
from video_case_commercial import projection as commercial
from video_case_data_status import projection as status
from video_case_presentation import metric_projection
root=Path(__file__).resolve().parent
old=(root/'build_cases_offline_harness.py').read_text(encoding='utf-8');prefix=old.split('data=json.dumps(items')[0]
namespace={};exec(compile(prefix,str(root/'build_cases_offline_harness.py'),'exec'),{'__file__':str(root/'build_cases_offline_harness.py')},namespace)
items=namespace['items'];styles=namespace['styles']
first=items[0];first['source']['kalodata']={'endpoint':'/video/detail','provider':'Kalodata','title':'隔离示例 · 平台数据已返回，AI仍在后台','handle':first['handle'],'period_start':'2026-10-18','period_end':'2026-11-16','currency':'USD','region':'US','period_views':0,'gmv':125.5,'units':6,'gpm':12.5,'duration':18.9,'product_count':1,'extra_metrics':{'ads_views':0,'ads_roas':1.5,'ad_view_ratio':.25,'ad_revenue_ratio':0,'revenue_growth_rate':-.5,'ads_period':3,'ad_cpa':2.25},'provider_flags':{'ad':0,'ai_video':1},'publish_date':'2026/11/01 18:30:00','creator_id':'987654321','collected':1794888000}
first['jobs']=[{'id':'fixture-analysis','kind':'analysis','state':'running','error':'','updated':1794888000,'stage':'AI后台分析 · 不阻塞平台指标'},{'id':'fixture-kalo','kind':'kalodata','state':'ready','error':'','updated':1794888000}]
items[1]['source']={};items[1]['jobs']=[{'id':'fixture-loading','kind':'kalodata','state':'running','error':'','updated':1794888000}]
items[2]['source']={};items[2]['jobs']=[{'id':'fixture-notfound','kind':'kalodata','state':'attention','error':'供应商返回 video not found；当前条件下未收录，未自动重试','updated':1794888000}]
for row in items:
    row['fields']=projection(row);row['commercial']=commercial(row);row['data_status']=status(row);row['metrics']=metric_projection(row);row['latest_jobs']=row['jobs']
data=json.dumps(items,ensure_ascii=False).replace('</','<\\/')
script=(root/'static/video-cases.js').read_text(encoding='utf-8')
body='<!doctype html><html lang="zh-CN" data-theme="obsidian"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Seedance · 数据先返回隔离验收</title><style>'+''.join(styles)+'</style><body><section id="intelligence"><h1>Seedance · 视频案例库</h1><p>静态隔离验收：示例指标，非真实视频表现。写入与付费调用已禁用。</p><div id="harness-host"></div></section><script>window.fixture='+data+';window.fetch=async(url,options={})=>{if(options.method)return new Response(JSON.stringify({detail:"隔离验收禁止写入"}),{status:403});const u=new URL(url,location.href),id=u.pathname.split("/").pop();let result;if(id!=="cases")result=fixture.find(x=>x.id===id);else {let rows=fixture.filter(x=>!u.searchParams.get("q")||JSON.stringify(x).includes(u.searchParams.get("q")));const start=Number(u.searchParams.get("offset")||0),size=Number(u.searchParams.get("limit")||48);result={items:rows.slice(start,start+size),total:rows.length};}return new Response(JSON.stringify(result),{status:200,headers:{"Content-Type":"application/json"}});};</script><script>'+script+'</script><script>window.hubVideoCases.open(document.getElementById("harness-host"));</script></body></html>'
path=root/'verification/cases-fast-data-harness-20261117.html'
with path.open('x',encoding='utf-8') as f:f.write(body)
print(path)
