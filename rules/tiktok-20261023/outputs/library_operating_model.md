# One Library, Two Modes, One Production Pipeline

版本：1.0。此文件是本项目模式、生产包、版本与写回规则的当前入口。此前“Library只管理资产”的职责范围扩展为统一控制台；资产处理逻辑及产品事实边界继续保留。

实施状态：已写入项目AGENTS.md；Production Package JSON Schema与只读取数/版本保存工具已落地。26项隔离、版本、顺序、分段与哈希检查通过，结果在`library_operating_model_validation.json`。尚未执行任何PROMOTE_TO_LIBRARY。

## 模式判定

| 请求 | 模式 | 允许最高输出 |
|---|---|---|
| 接收人工Research、Scenario Lab；提取、标准化、去重、Cluster、ID、标签、关联 | ASSET_MODE | Creative Matrix |
| 查询/比较候选创意 | ASSET_MODE | 创意候选与推荐，不自动制作视频 |
| 明确“用CR_x制作视频”或选定具体Creative Concept | PRODUCTION_MODE | 按阶段到Seedance Video Prompt |
| 更新本工作规则 | 管理操作 | 修改规则，不自动开始生产 |

已在上下文明确选择的创意可以复用。没有Creative_ID但用户已选概念时，先映射到已有Creative或创建明确关联的Creative记录；不能猜测产品事实。新产品Research与Scenario Lab均来自外部上游，Library不主动补充调研。

## ASSET_MODE

负责Product Ground Truth、Pain、Scenario、Character、Relationship、Hook、Demo、Script Pattern和Creative Matrix的解析、原子化、去重、聚类、ID、标签与关联。
禁止完整脚本、完整Storyboard和Seedance Prompt；禁止为了某条视频临时改Product Ground Truth。

## PRODUCTION_MODE

1. 检查用户明确选择，读取选定Creative及关联资产。
2. 建立Production Package并保存来源快照、ID、revision/hash和待审核项。源库仍为review时只生成待审草案，不自动投放。
3. 调用`tiktok-commerce-rhythm-director`生成并校验Commerce Beat Sheet。
4. 调用`tiktok-daihuo-script-writing`生成英文逐拍口播、Clean Read与简短Delivery Notes。
5. 默认直接生成Detailed Video Prompt：用户提供人物与产品参考图，Prompt写全环境、空间、机位、动作、产品状态、声音和跨段衔接。空间首帧与Storyboard只在用户明确要求时制作。
6. 生成真实媒体/发布不由这些文本交付自动授权。

**顺序执行，共用节奏表。** Script与Prompt始终直接引用同一Beat Sheet版本/hash。默认Prompt直接引用具体口播；若用户主动制作Storyboard，Prompt再增加Storyboard依赖。下游不得增加铺垫、拖后Demo/产品/CTA或变更卖点顺序。

脚本转化检查采用[`hispc_script_framework_v1.md`](hispc_script_framework_v1.md)：以H-I-S-P-C审核整条视频的停留、相关性、解决方案、证据与CTA，逐项建立开头承诺到Beat证据的映射。稳定脚本的输入、Hook证据等级、口播滑梯、固定销售链和交付格式同时遵循[`stable_script_generation_contract_v1.md`](stable_script_generation_contract_v1.md)，机器输入使用[`stable_script_input.schema.json`](stable_script_input.schema.json)，人工交付使用[`stable_script_output_template_v1.md`](stable_script_output_template_v1.md)。这些规则不把45秒切成独立章节，也不覆盖Beat Sheet时长；45秒以后默认分为17+17+11秒的一条销售链。机器侧可使用[`hispc_beat_overlay.schema.json`](hispc_beat_overlay.schema.json)记录审核结果；覆盖层属于Production Output，不能由此自动写回Canonical资产。用户提供的外部话术模板只作候选，价格、效果、亲测、库存、对比均需按Product Ground Truth与Approved Claims核实。

## Production Package

机器字段采用snake_case，对应用户指定字段如下。完整可验证定义在`production_package.schema.json`。

| 用户字段 | 机器字段 / 规则 |
|---|---|
| Creative_ID / Product_ID | creative_id / product_id；必填稳定ID |
| Pain_ID / Scenario_ID | pain_id / scenario_id；必填引用 |
| Character_A_ID / Character_B_ID | character_a_id / character_b_id；B可null，不伪造第二人 |
| Relationship_ID | relationship_id；映射现有relationship_type_id，可null |
| Hook_ID / Demo_ID / Pattern_ID | hook_id / demo_id / pattern_id |
| Primary_Selling_Point | primary_selling_point；绑定当前已批准Claim，不凭场景补功能 |
| Secondary_Selling_Point | secondary_selling_point；未选时null |
| Product_Ground_Truth | product_ground_truth；只读快照 |
| Approved_Claims | approved_claims；仅status=approved，不把所有候选Claim改名视为批准 |
| Product_Limitations | product_limitations；来自真实usage_constraints |
| Recommended_Video_Mode | recommended_video_mode；Commerce枚举，属于生产建议 |
| Target_Duration | target_duration_sec；用户指定优先，以17秒为分段上限，45秒拆成17+17+11秒 |
| CTA_Mode | cta_mode；product_link/profile/save/none，按真实去向 |
| AI_Difficulty | ai_difficulty；level=unknown/low/medium/high + rationale，未知不打伪精确评分 |

额外保留：operating_mode、package_version、production_version、created_at、selection_evidence、price_mode、segments、source_packet、source_hashes、review_gate。selection_evidence记用户选择原文或可定位消息，不由系统虚构授权。
准备包使用冻结快照；若Canonical资料后来变更，旧版本继续保持原快照，新版本重新取数并复核受影响内容。

## 生产存储与依赖

```text
outputs/productions/<Creative_ID>/
  Production_V001/
    Production_Package.json
    BeatSheet_V001.json
    BeatSheet_V001.receipt.json
    Script_V001.md
    Script_V001.receipt.json
    # Storyboard_V001.md及receipt仅在用户明确要求时存在
    SeedancePrompt_V001.md
    SeedancePrompt_V001.receipt.json
  Production_V002/
    ...
```

每次修订创建新Production Version，历史文件不覆盖。V002可复用经检查未变的上游产物，但必须在本版本保存确切副本并记录哈希，不能把旧Script误挂到新Beat Sheet。
每个receipt记录当前文件hash、beat_sheet_sha256、直接上游文件hash。存在文件时工具拒绝覆盖。目录不会把“已保存”标为“人已确认”；human approval与文件存在独立管理。
工具保存的receipt只证明来源与保存次序；B时间/内容的一致性还需按Beat Sheet及Skill校验，不代表语义已审核。

## Canonical Asset Protection

Product Ground Truth、Pain、Scenario、Character、Relationship、Hook、Demo、Script Pattern是Canonical资产。Creative Matrix属于资产侧组合记录，生产时同样只读。
口播、临时对白、人物动作、场景细节、Hook变体、视觉设计、节奏表和Prompt留在Production Output。生产工具不写Canonical文件。

## PROMOTE_TO_LIBRARY

满足以下至少一项可以发起：

1. 用户明确要求入库，记录请求；
2. 人工确认可复用，记录审核人、范围及结论；
3. 多次生产重复验证，引用不同Production Version及具体复用结果；仅复制多次不算验证；
4. 有真实表现数据，记录视频、统计时间窗、指标及可支持的结论；不把相关性当因果。

采用显式动作记录：`action=PROMOTE_TO_LIBRARY`、production_output_ref及hash、target_library、eligibility_basis、evidence_refs、dedupe_result、proposed_asset、source_lineage、result_asset_id、status。
状态建议candidate → eligible → promoted/rejected。达到条件不会后台自动写回；执行升级时才按ASSET_MODE入库步骤原子化、去重、赋ID、建立证据及关联，并保存操作结果。
如果用户已明确要求入库，不为同一范围重复索取许可；如果证据不够，先保留候选并说明具体缺项。
真实产品事实仍只能由人工产品调研/用户事实确认支持。创意表现好、观众点赞、AI演示成功，都不能作为新功能/容量/安全结论的证明。产品事实更正独立于创意资产升级。

## 调用

```powershell
# ASSET_MODE：查询候选
python -X utf8 .\outputs\library_console.py asset --limit 10

# 用户明确选定后：生成不可覆盖的新Production Package
python -X utf8 .\outputs\library_console.py prepare --creative CR_01M38BCG00D4EVGNPTSSQJABAH --selection-evidence "用户已选择去奶奶家带玩具的概念" --duration 45 --cta save --video-mode MICRO_STORY_COMMERCE

# 默认顺序保存：BeatSheet、Script、SeedancePrompt；Storyboard为可选阶段
python -X utf8 .\outputs\library_console.py store --package-dir <Production_Vxxx路径> --stage BeatSheet --file <本次BeatSheet文件>
```

命令示例不是自动开工指令。本次Operating Model更新不生成新的视频脚本、分镜或Prompt。原有SL-007选择继续保留，后续恢复该视频时可直接沿用。
