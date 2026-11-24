"""Isolated, worker-disabled UI verification server. Never opens the production database."""
from pathlib import Path
import os
import secrets
import json
import time
import uvicorn
from app import create_app,password_hash
root=Path(__file__).resolve().parent
state=root/'verification'/'cases-preview-state'
os.environ['HUB_ORIGIN']='http://127.0.0.1:8877'
app=create_app(state,worker=False)
hub=app.state.hub
with hub.db() as db:
    db.execute('INSERT OR IGNORE INTO users(id,username,password,role) VALUES(?,?,?,?)',('case-preview','验收账号',password_hash(secrets.token_urlsafe(32)),'admin'))
    # Verification-only public metadata; not copied into production or counted as real performance.
    now=time.time()
    fixtures=[('demo-a','123456789','手持工具的三种使用场景','工具','场景演示',['工具','演示'],'先提出具体问题，再依次展示三个解决方式。'),('demo-b','123456790','桌面收纳前后对比','家居收纳','前后对比',['收纳','对比'],'对比结构很清楚；这是界面验收示例，不是真实分析结论。'),('demo-c','123456791','礼物清单与选择式结尾','礼品','清单推荐',['送礼','清单'],'值得讨论的是结尾选择式互动；适用性需要成员判断。')]
    for index,(cid,vid,title,category,kind,tags,summary) in enumerate(fixtures):
        db.execute('INSERT OR IGNORE INTO video_cases(id,canonical,platform,video,handle,url,source,human,created_by,updated_by,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(cid,'tiktok:'+vid,'TikTok',vid,'verification','https://www.tiktok.com/@verification/video/'+vid,json.dumps({'title':title,'origin':'隔离界面验收示例','collected':now,'cover':'https://invalid.tiktokcdn.com/example.jpg','views':None},ensure_ascii=False),json.dumps({'title':title,'category':category,'content_type':kind,'tags':tags,'summary':summary},ensure_ascii=False),'case-preview','case-preview',now,now-index))
        db.execute('INSERT OR IGNORE INTO video_case_members VALUES(?,?,?)',(cid,'case-preview',now))
    db.execute('INSERT OR IGNORE INTO video_case_ideas VALUES(?,?,?,?,1,?,?)',('idea-preview','demo-a','case-preview',json.dumps({'reason':'示例：关注演示顺序，而不是照搬原视频价格','adaptation':'示例：用自己产品的真实使用条件重新组织演示','hypothesis':'示例：先试一个开头变量，结果待验证'},ensure_ascii=False),now,now))
# Only this isolated fixture auto-selects its seeded account; no login code or session copied from production.
from fastapi import Request
from fastapi.responses import Response
@app.get('/verification-login')
def verification_login(request:Request):
    from fastapi.testclient import TestClient
    # Use a temporary one-time password internally, never printed or exposed in response.
    pw=secrets.token_urlsafe(32)
    with hub.db() as db:db.execute('UPDATE users SET password=? WHERE id=?',(password_hash(pw),'case-preview'))
    with TestClient(app,base_url='http://127.0.0.1:8877') as c:
        r=c.post('/api/login',headers={'X-Hub-Request':'1','Origin':'http://127.0.0.1:8877'},json={'username':'验收账号','password':pw})
        response=Response(status_code=303,headers={'Location':'/'})
        for value in r.headers.get_list('set-cookie'):response.headers.append('set-cookie',value)
        return response
@app.get('/verification-cases')
def case_verification_screen():
    # A stable component harness avoids the unrelated animated home carousel during responsive tests.
    import re
    from fastapi.responses import HTMLResponse
    styles=''.join(re.findall(r'<link[^>]+rel="stylesheet"[^>]*>',(root/'static/index.html').read_text(encoding='utf-8')))
    return HTMLResponse('<!doctype html><html lang="zh-CN" data-theme="obsidian"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>视频案例库 · 隔离验收</title>'+styles+'<body><section id="intelligence"><div class="intel-heading"><h1>Seedance · 视频案例库</h1></div><p style="font-size:12px;color:var(--fg-mute)">隔离验收环境 · 示例指标不代表视频真实表现 · worker已关闭</p><div id="case-test-host"></div></section><script src="/static/video-cases.js"></script><script>window.hubVideoCases.open(document.getElementById("case-test-host"));</script></body></html>')
print('Isolated case gallery verification: http://127.0.0.1:8877/verification-login (worker disabled)',flush=True)
uvicorn.run(app,host='127.0.0.1',port=8877,access_log=False)
