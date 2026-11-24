# Library project operating rules

新口播的前三秒必须连续完成“先点明具体目标用户身份 → 再说该产品对这类用户的最强已证实卖点，或这类用户的最大具体痛点”，执行细则见 `outputs/stable_script_generation_contract_v1.md` 第4节。仅环境声片段不强加口播；用户要求逐字保留的原稿按其明确要求处理。

本项目统一工作入口为Library。开始工作先按用户意图区分ASSET_MODE与PRODUCTION_MODE。
正式运行规则见 `outputs/library_operating_model.md`；生产包结构见 `outputs/production_package.schema.json`。
已选创意的带货脚本还须按 `outputs/hispc_script_framework_v1.md` 做开头承诺、Beat 证据、CTA 闭环审核，并按 `outputs/stable_script_generation_contract_v1.md` 固定Hook证据等级、口播滑梯、角色契约和脚本交付格式；两者都是 Beat Sheet 的审核与生成合同，不是新的节奏来源。
商业镜头节奏按 `outputs/commerce_camera_rhythm_contract_v1.md` 执行：每个镜头最长3秒，切镜跟随口播信息点和动作完成点；关键Demo保持动作因果清楚，镜头细分不得改变Beat、产品事实或操作顺序。开头动作直接推进，不设无信息的等待。
直接视频提示词按 `outputs/direct_video_prompt_contract_v1.md` 执行。用户已明确将其设为默认生产路径：提供人物与产品参考图后，跳过空间首帧和Storyboard，把空间、景别、环境、光线、动作、产品状态、声音和跨段衔接完整写入每段视频提示词。今后默认每段最多17秒，末段按剩余时长；已保存的15秒历史版本不重切。

- 默认ASSET_MODE：人工Research/Scenario Lab解析、原子化、去重、聚类、ID、标签、关联、Canonical Assets、Creative Matrix。最高输出Creative Matrix；不生成完整脚本、Storyboard或Seedance Prompt。不主动市场调研。
- 只有用户明确要求使用某Creative_ID制作视频，或明确选定Creative Concept，才进入PRODUCTION_MODE。展示/查询创意或更新工作规则本身不触发生产。已有明确选择可复用，不重复询问。
- 生产前创建不可覆盖的Production Package，快照事实、关联ID、Approved Claims、限制、来源版本和审核状态；不得把review候选当已批准事实。
- 默认顺序：Creative Matrix → Commerce Beat Sheet → TikTok Creator Spoken Script → Detailed Video Prompt。空间首帧和Storyboard默认跳过，只有用户明确要求时才恢复；Prompt直接读取同一Beat Sheet和口播，不重新解释节奏。
- 优先级：Product Ground Truth > Approved Claims > Demo/Safety > Commerce Beat Sheet > Spoken Script > Detailed Video Prompt > decoration。冲突修订所属上游。45秒默认17+17+11秒，共享整片销售链；本项目当前包口播不提售价。
- Canonical Assets不能因生产自动改变。临时对白、人物动作、场景、Hook变体、视觉设计与完整脚本默认是Production Output。
- 写回只能通过显式命名的PROMOTE_TO_LIBRARY，且满足用户要求入库、人工复用审核、多次生产重复验证或真实表现证据之一。合格不等于已入库；执行时仍需去重、证据与事实边界检查和入库记录。视频表现不证明产品事实。
- 每Creative_ID允许多Production Version；不得覆盖历史版本。变更Beat Sheet使依赖旧hash的Script/Storyboard/Prompt失效，只在新版本重建或经检查引用未变内容。
- 参考图由用户提供，默认按人物（含宠物）、产品外观（展开与收起形态）、产品细节分工；空间首帧与Storyboard不再作为默认门槛。缺少故事板时，Prompt必须显式补齐空间几何、机位、动作因果、产品状态和连续性约束。每条脚本至少两次人物正对镜头同期说话；口播尽量覆盖当前时长内可证明的主要卖点，不能靠超快语速或未经批准的主张凑数量。
- `outputs/library_console.py`只读Canonical数据并创建生产包、保存生产产物；不自动调研、生成媒体或写回Canonical库。
