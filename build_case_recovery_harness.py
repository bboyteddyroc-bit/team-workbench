"""Isolated renderer verification using current production assets. No external requests or writes."""
from pathlib import Path
import json,re
from video_case_fields import projection
root=Path(__file__).resolve().parent
old=(root/'build_cases_offline_harness.py').read_text(encoding='utf-8')
# Reuse the verified fixture reader and CSS bundle, not the previous generated artifact.
prefix=old.split('data=json.dumps(items')[0]
namespace={};exec(compile(prefix,str(root/'build_cases_offline_harness.py'),'exec'),{'__file__':str(root/'build_cases_offline_harness.py')},namespace)
items=namespace['items'];styles=namespace['styles']
for row in items:row['fields']=projection(row)
row=items[0];row['source']['kalodata']={'title':'Kalodata来源标题 · 等待恢复验收示例','handle':row['handle'],'period_start':'2026-10-18','period_end':'2026-11-16'};row['fields']=projection(row)
row['jobs']=[{'id':'isolated-wait','kind':'analysis','state':'waiting','error':'供应商已排队获取视频；等待后自动检查，每次可能消耗API额度','updated':1794906000,'next_attempt':1794906060,'wait_deadline':1794992400,'wait_count':2,'is_owner':True,'stage':'等待供应商视频缓存'}];row['latest_jobs']=row['jobs']
data=json.dumps(items,ensure_ascii=False).replace('</','<\\/')
script=(root/'static/video-cases.js').read_text(encoding='utf-8')
body='<!doctype html><html lang="zh-CN" data-theme="obsidian"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>视频案例库 · 等待恢复与来源优先验收</title><style>'+''.join(styles)+'</style><body><section id="intelligence"><h1>视频案例库 · 隔离验收</h1><p>示例数据，非真实指标；禁止写入及付费请求</p><div id="harness-host"></div></section><script>const fixture='+data+';window.fetch=async(url,options={})=>{if(options.method)return new Response(JSON.stringify({detail:"静态验收禁止写入"}),{status:403});const u=new URL(url,location.href),id=u.pathname.split("/").pop();let result;if(id!=="cases")result=fixture.find(x=>x.id===id);else {let rows=fixture.filter(x=>!u.searchParams.get("q")||JSON.stringify(x).includes(u.searchParams.get("q")));const start=Number(u.searchParams.get("offset")||0),size=Number(u.searchParams.get("limit")||48);result={items:rows.slice(start,start+size),total:rows.length};}return new Response(JSON.stringify(result),{status:200,headers:{"Content-Type":"application/json"}});};</script><script>'+script+'</script><script>window.hubVideoCases.open(document.getElementById("harness-host"));</script></body></html>'
path=root/'verification/cases-recovery-harness-20261117.html';path.write_text(body,encoding='utf-8');print(path)
