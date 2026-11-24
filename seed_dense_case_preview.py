"""Seed 73 obviously labelled cases into isolated worker-disabled verification DB only.
Uses existing two source videos' sampled covers; no API, production mutation, secrets or AI calls.
"""
from pathlib import Path
import sqlite3,json,time,shutil
root=Path(__file__).resolve().parent;state=root/'verification/cases-preview-state'
assert state.parent.name=='verification' and (state/'hub.sqlite3').is_file()
items=[('杯具结构与多色展示','饮具','结构演示','新奇设计','圣诞送礼','手部出镜'),('工具三种使用场景','五金工具','使用演示','问题解决','办公','真人出镜'),('围巾拆礼物反应','服饰配件','拆礼物反应','情绪反应','圣诞送礼','多场景'),('桌面收纳前后对比','家居收纳','前后对比','视觉反差','办公','单场景'),('厨房小工具操作教程','厨具','教程','问题解决','厨房','手部出镜'),('出行配件清单推荐','数码','清单推荐','新奇设计','旅行','屏幕字幕')]
sourceids=('430532be99864aae9e0ef6ec35279a85','8fafffdff2984e2c937aace19a8aba5d')
with sqlite3.connect(state/'hub.sqlite3') as db:
    for i in range(73):
        cid='gallery-proof-'+str(i).zfill(3);vid=str(888880000+i);title,product,kind,appeal,scene,production=items[i%len(items)];now=time.time()-i
        tags={'product':[product],'format':[kind],'appeal':[appeal],'scene':[scene],'production':[production]}
        fields={'summary':'[验收示例] '+title+'：先展示真实场景，再近景呈现产品动作。','product_category':product,'content_type':kind,'event':scene,'replicability':'示例：设备为手机，重点在场景与操作顺序；请按产品真实条件复刻。','replication_actions':'[验收示例] 提出问题 → 真实动作演示 → 对比结果，不编造效果。','tag_groups':tags,'tags':[product,kind,scene],'notes':'画廊与指标验收专用，不是真实表现数据。'}
        kd={'period_views':0 if i==0 else 822800+i,'likes':0 if i==0 else 49000+i,'comments':283+i,'shares':8121+i,'gmv':1234.5+i,'currency':'USD','period_start':'2026-10-18','period_end':'2026-11-16','collected':now,'provider':'Kalodata'}
        source={'title':'[验收示例] '+title,'origin':'隔离画廊验收','views':999999,'collects':6647+i,'collected':now,'kalodata':kd}
        ai={'fields':fields,'evidence':{'summary':'隔离验收文本，非模型调用'},'generated_at':now,'basis':'隔离数据，仅验证排版与映射','uncertainties':['样例指标不是这条视频真实数据']}
        db.execute('INSERT OR REPLACE INTO video_cases(id,canonical,platform,video,handle,url,source,human,ai,created_by,updated_by,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,'tiktok:'+vid,'TikTok',vid,'gallery_fixture','https://www.tiktok.com/@gallery_fixture/video/'+vid,json.dumps(source,ensure_ascii=False),'{}',json.dumps(ai,ensure_ascii=False),'case-preview','case-preview',now,now))
        db.execute('INSERT OR IGNORE INTO video_case_members VALUES(?,?,?)',(cid,'case-preview',now))
        frame=root/'state/case-analysis'/sourceids[i%2]/('frame-'+str(i%9)+'.jpg')
        cover=state/'case-covers'/(cid+'.img');cover.parent.mkdir(exist_ok=True);shutil.copyfile(frame,cover)
print('73 isolated gallery fixtures seeded; no production changes or paid calls',flush=True)
