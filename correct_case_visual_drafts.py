"""Evidence correction of AI drafts after inspecting the cached nine frames. No AI/API calls.
Preserve original AI snapshot and all human fields; leave human approval to the team.
"""
from pathlib import Path
import json,time
from app import create_app
root=Path(__file__).resolve().parent
app=create_app(root/'state',worker=False);hub=app.state.hub
changes={
'430532be99864aae9e0ef6ec35279a85':{
'fields':{
'summary':'在圣诞树背景前，用手持近景展示 FROSTBUDDY 杯具的多种颜色、杯盖与可拆卸高脚底座。',
'event':'圣诞送礼场景（画面有圣诞树，屏幕文字明确提到 Christmas Gift；不代表实际发布时间）',
'product_category':'家居 / 饮具 / 便携杯具',
'content_type':'多色实物展示 + 底座拆装演示 + 节日送礼字幕',
'replicability':'拍摄门槛较低：手机、真实产品与简洁背景即可。复刻需产品确实具备可拆底座等结构，不能照搬未经验证的保温、制冷等功能表述。',
'replication_actions':'1. 准备确有可拆底座的产品及可用颜色。\n2. 固定背景与构图，手持近景先展示杯体和底座。\n3. 依次拍摄装上底座、打开杯盖、拆下底座等真实操作。\n4. 用同构图展示多种颜色，最后给产品标识一个近景。\n5. 结合真实用途写送礼开头，不承诺未经验证的效果。',
'hook_example':'',
'hook_template':'改写建议：「今年的[具体节日]礼物，我先帮你挑出一个[真实差异点]。」这是建议文案，不是原口播。',
'suitable_products':'有可演示结构差异的杯具、饮具、家居礼品；不据画面认定其为主动制冷设备。',
'production_threshold':'低：手机近景拍摄、稳定光线、产品实物；分析仅有抽帧，实际转场与节奏需回看原视频。',
'prerequisites':'有真实可操作产品及颜色样品；如使用节日场景，需与推广计划一致。产品品牌、功能和宣传用语以自有资料核实。',
'notes':'品牌可见为 FROSTBUDDY。原AI曾误识品牌并把制冷效果当成产品属性，已按画面撤回。画面可见高脚底座/杯盖/多色，不证明制冷、保温、续航或售价。视频文件实测13.77秒；没有取得ASR口播，不代表原视频无音频。',
'opening':'绿色杯体与高脚底座分离展示；背景为圣诞树。画面字幕提到 Christmas Gift，属于屏幕文字，不是已识别口播。',
'audience_scenario':'推断：寻找节日礼物、关注新颖饮具的浏览者；不是已取得的平台受众画像。',
'expression':'抽帧顺序：绿色杯体与底座 → 粉色高脚形态 → 杯盖近景 → 黑色/酒红色外观 → 杯体与底座分离 → 紫红色杯体与品牌近景。动作顺序可参考，连续剪辑节奏未核实。',
'ending':'最后采样帧为紫红色杯体近景，可见 FROSTBUDDY 标识；未见可核实的口播收尾。',
'merchant_visible':'','transcript_en':'','transcript_zh':'',
 'tags':['圣诞送礼','多色展示','杯具','结构演示','手持近景']},
'uncertainties':['仅核对9张采样帧，不等于连续视频与完整音频审核。','未取得ASR；Hook真实口播与逐字稿保持空白。','品牌已按画面校正；材料、功能、售价、商家与发布时间仍未知。','Kalodata详情接口当前未返回指标；播放、点赞、GMV等不补零、不编造。'],
'evidence_note':'画面校正：第0/4/8帧可见FROSTBUDDY；第0/1帧为圣诞送礼字幕与可拆高脚底座。'},
'8fafffdff2984e2c937aace19a8aba5d':{
'fields':{
'summary':'以给妈妈拆礼物的反应开场，展示趣味针织围巾，再切到户外、服务台、电梯和街头佩戴展示。',
'event':'圣诞拆礼物氛围（家中树饰与礼品包装可见）；不能把“给妈妈的礼物”认定为母亲节，发布时间未知。',
'product_category':'服饰配件 / 围巾 / 趣味礼品',
'content_type':'拆礼物反应 + 趣味产品展示 + 多场景佩戴',
'replicability':'中等：围巾实物、出镜者和多个场景；可缩减为家庭拆礼物+一个户外场景。公共场所拍摄要取得同意，不能编造路人或购买反应。',
'replication_actions':'1. 准备真实围巾礼品，先拍拆包装和收礼人的自然反应。\n2. 给围巾外观、末端装饰和佩戴方式拍近景。\n3. 选1—2个可授权场景展示佩戴效果。\n4. 连接产品近景与人物互动，保留真实反馈，不造假。\n5. 用“送给谁”的字幕提出悬念，再展示礼物本身。',
'hook_example':"Perfect gift for your Mom doesn't exi...",
'hook_template':'改写建议：「送给[具体对象]的有趣礼物不存在？先看完这个。」适合确有趣味外观的商品，不是原口播。',
'suitable_products':'趣味围巾、针织配饰、带可视化设计的礼品；画面中卫衣是搭配，不将其认定为被展示的围巾商品。',
'production_threshold':'中：手机与基础剪辑可拍，难点是自然反应、多场景衔接和拍摄许可；不是复杂特效。',
'prerequisites':'产品外观有明确记忆点；获得出镜与场景同意；成人趣味表达需核对平台和品牌规范；不可把短片反应视为市场效果证明。',
'notes':'原AI把主体误识为“前挂针织袋连帽卫衣”，并误把电梯当开场，已按采样序列改为围巾与家庭拆礼物。实测21.015秒。ASR仅“Oh, you did not!”短句；Hook来自屏幕字幕，不能当口播。家庭包装和圣诞树可见；没有母亲节证据。',
'opening':'家中多人围坐，一位女士从礼品袋拆出奶白色针织围巾，随后展示围巾。屏幕字幕为 Perfect gift for your Mom doesn’t exi...（屏幕文字，非ASR）。',
'audience_scenario':'推断：寻找给妈妈/亲友趣味礼物或观看拆礼物反应的用户；不是平台画像，不能据此断言节日转化。',
'expression':'抽帧顺序：家庭拆礼物与反应 → 围巾末端近景 → 户外佩戴 → 服务台互动 → 电梯合照/互动 → 城市街头双人佩戴。采样显示场景递进，不代表已核对全部台词与转场。',
'ending':'最后采样帧为两位女士在城市街头面向镜头佩戴围巾；未取得可核实的购买号召或完整口播结尾。',
'merchant_visible':'',
 'transcript_en':'Oh, you did not!',
 'transcript_zh':'天哪，你竟然……！（短句意译；语气需回听核实）',
 'tags':['围巾','趣味礼物','拆礼物反应','多场景佩戴','屏幕字幕']},
'uncertainties':['仅核对9张采样帧，不等于连续视频与完整音频审核。','ASR只有一个短句；英文/中文版本不是全片逐字稿。','Hook为屏幕字幕，不是已识别口播；母亲节、准确地点、商家与售价均未证实。','Kalodata详情接口当前未返回指标；发布时间与互动/成交数据保持未知。'],
'evidence_note':'画面校正：第0/1帧家庭拆礼物和针织围巾，第2帧末端近景，第3—8帧为多场景佩戴。'}
}
for cid,fix in changes.items():
    with hub.db() as db:
        row=dict(db.execute('SELECT * FROM video_cases WHERE id=?',(cid,)).fetchone())
    old=json.loads(row['ai']);directory=hub.directory/'case-analysis'/cid
    snapshot=directory/'before-visual-correction-v1.json'
    if not snapshot.exists():snapshot.write_text(row['ai'],encoding='utf-8')
    if old.get('visual_correction',{}).get('version')=='v1':print('Already corrected',cid);continue
    fields={**old.get('fields',{}),**fix['fields']}
    evidence={k:fix['evidence_note']+' 分析建议非平台事实。' for k,v in fields.items() if v and k!='tags'}
    evidence['hook_example']='第0帧屏幕字幕（不是口播）' if fields.get('hook_example') else ''
    for k in ('transcript_en','transcript_zh'):
        if fields.get(k):evidence[k]='已保存的16字符ASR短句；翻译为待审核意译'
    packed={**old,'fields':fields,'evidence':evidence,'uncertainties':fix['uncertainties'],'generated_at':time.time(),'basis':'Kalodata视频9帧采样 + 逐帧证据校正；ASR为已有短稿或缺失','visual_correction':{'version':'v1','by':'assistant-evidence-check','at':time.time(),'note':fix['evidence_note'],'original_retained':True}}
    with hub.db() as db:
        db.execute('BEGIN IMMEDIATE')
        latest=db.execute('SELECT ai,human FROM video_cases WHERE id=?',(cid,)).fetchone()
        if latest['ai']!=row['ai'] or latest['human']!=row['human']:raise RuntimeError('Concurrent edit; no overwrite')
        db.execute('UPDATE video_cases SET ai=?,updated=? WHERE id=?',(json.dumps(packed,ensure_ascii=False),time.time(),cid))
        assert db.execute('SELECT human FROM video_cases WHERE id=?',(cid,)).fetchone()['human']==row['human']
    print(json.dumps({'video':row['video'],'visual_correction':'v1','human_unchanged':True,'review':'pending'},ensure_ascii=True),flush=True)
