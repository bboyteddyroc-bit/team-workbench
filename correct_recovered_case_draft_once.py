"""Local evidence-only correction after inspecting all nine saved frames. No model/API replay.
Preserves original AI JSON in an audit table, human overrides and provider facts untouched.
"""
import sqlite3,json,time
from pathlib import Path
root=Path(__file__).resolve().parent;cid='2d9151c8a5844d73905644031f330ee7';version='recovery-9frame-check-v1'
with sqlite3.connect(root/'state/hub.sqlite3',timeout=15) as db:
    db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE')
    db.execute('CREATE TABLE IF NOT EXISTS video_case_draft_corrections(case_id TEXT NOT NULL,version TEXT NOT NULL,original_ai TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(case_id,version))')
    if db.execute('SELECT 1 FROM video_case_draft_corrections WHERE case_id=? AND version=?',(cid,version)).fetchone():
        print('Existing correction retained; no change');raise SystemExit(0)
    row=db.execute('SELECT ai,human FROM video_cases WHERE id=?',(cid,)).fetchone();packed=json.loads(row['ai'])
    assert packed.get('generated_at')==1794887669.297281,'New draft exists; do not overwrite'
    assert len(list((root/'state/case-analysis'/cid).glob('frame-*.jpg')))==9
    fields=packed['fields'];fields.update(
        summary='车尾圆形显示标切换绿色图形、BMW图案及加载样式；穿插手机界面操作展示。',
        product_category='汽车外观配件（具体商品名称、技术与适配车型待核实）',
        content_type='实物效果与手机操作交替展示',
        replicability='可借鉴“实物效果→手机操作→实物反馈”的演示结构；需有可操作实物及适配安装条件，不据采样画面承诺通用兼容或低成本。',
        replication_actions='改写建议：先展示实物变化，再拍操作入口及实际反馈；保留自己的真实使用限制。手机拍摄、配乐与字幕属于制作建议，不代表已证实原片配置。',
        prerequisites='需实际可演示的产品、安装与使用授权，并核实适配、安全及当地车辆改装规定；画面不能证明价格、耐用性或合法上路条件。',
        production_threshold='需实物、安装条件与能清楚拍摄屏幕和效果的设备；实际成本及拍摄设备未知。',
        opening='首个采样帧（0秒）是白色车辆车尾特写，圆形位置呈绿色图形；不将采样帧当作完整开头动作。',
        audience_scenario='可供汽车外观配件演示参考；画面为户外车辆，BMW图样可见，但目标客群与适配车型仍属推断，待核实。',
        expression='采样中交替出现车尾显示效果与手持手机操作画面；未取得ASR，不判断是否无口播。',
        ending='末个采样帧约18.833秒为车尾圆形加载样式；不能据此推断最后转场、CTA或完整结尾。',
        notes='本地媒体探测18.933秒，共9帧，采样约0/2.354/4.708/7.063/9.417/11.771/14.125/16.479/18.833秒；仅采样审核，不是连续视频理解。未取得ASR。手机界面与车标可见，技术、品牌授权、价格、适配及商家信息未证实。纠正初稿“6帧/约12秒/原厂开头/推测结尾”等无依据描述。')
    fields['tags']=['汽车外观配件','车尾显示','手机操作演示','图案切换']
    fields['tag_groups']={'product':['汽车外观配件'],'format':['实物演示','操作与效果切换'],'appeal':['动态图形变化'],'scene':['户外车辆'],'production':['手部出镜','近景展示']}
    for key in ('hook_example','transcript_en','transcript_zh'):fields[key]=''
    packed['evidence']={key:'本地已保存9帧 + ffprobe时长；分析/复刻建议仍待人工回看，非Kalodata字段' for key,value in fields.items() if value and isinstance(value,str)}
    packed['uncertainties']=['未取得ASR，逐字稿、翻译与Hook原句留空；不表示无口播。','已核实媒体18.933秒、9帧；采样无法证明完整动作顺序或内容连续性。','产品技术、商家、价格、车型兼容、改装合规与品牌授权未知。','Kalodata详情尚未返回指标；下载成功不代表已取得指标。']
    packed['visual_correction']={'version':version,'checked_frames':list(range(9)),'duration_seconds':18.933333,'review_status':'待人工审核','external_calls':0}
    db.execute('INSERT INTO video_case_draft_corrections(case_id,version,original_ai,created) VALUES(?,?,?,?)',(cid,version,row['ai'],time.time()))
    now=time.time();packed['generated_at']=now
    db.execute('UPDATE video_cases SET ai=?,updated=? WHERE id=?',(json.dumps(packed,ensure_ascii=False),now,cid))
print('Corrected AI draft against nine frames; human/provider unchanged, original retained, still pending review.')
