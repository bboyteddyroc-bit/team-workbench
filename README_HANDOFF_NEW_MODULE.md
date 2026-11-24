# Seedance 团队中台：新板块开发交接 README

更新日期：2026-11-03。用途：交给新的开发对话，理解现有系统并开发一个新板块。本文是代码与近期工作状态的快照，不包含生产数据、密码、Cookie、API Key、App Secret 或私钥。

## 1. 给接手智能体的任务说明

你将负责在现有中台新增一个独立的大板块。具体业务需求由用户在新对话中补充，本文不授权你自行决定新板块的业务范围。先阅读本文件与项目 AGENTS.md，再检查相关代码和工作区差异，提出最小接入方案。复用登录、权限、素材、任务与 UI 基础设施，避免另做一套互不连通的应用。不要因接手而重写制作台、剪辑台或替换整个前端框架。

可能有其他智能体同时修改剪辑台或其他模块。开始前明确负责的文件，检查已有改动，不回滚、覆盖或批量格式化他人的内容。涉及公共入口时做小范围增量修改。历史聊天中的“希望实现”不代表已实现，文档中的功能也需要按本次相关范围核对代码。

## 2. 产品定位与体验原则

这是面向团队 TikTok 内容制作的内网中台，兼容 AI 生成与实拍。用户的核心概念是“像水一样流动”：素材、制作、剪辑、导出、归档应连续承接，减少重复选择、重复上传和跨页面操作。

主流程：素材入库 → 制作台生成（实拍可跳过）→ 剪辑台 → 独立命名导出 → 飞书个人目录按日归档。

设计偏好：黑白和中性深灰为基底，青色用于重点与选中状态，已有主强调色参考 #23A9BD；用户明确不喜欢大面积深蓝色背景。界面简洁、功能分层、减少说明文字和过大的按钮；媒体预览应有足够空间。默认视频工作流为 9:16。保留加载、失败、计费等必要反馈。复用现有主题变量与交互，不另起配色。历史上借鉴过 BeUI、GSAP 和 CapCut，但当前工程不是标准 shadcn/React 工程，不能盲目执行组件安装命令改造整体架构。

## 3. 工程位置与技术栈

项目根目录：
`C:\Users\111\Documents\Codex\2026-10-19\neng\outputs\seedance-hub`

工作区上级：`C:\Users\111\Documents\Codex\2026-10-19\neng`

- 后端：Python、FastAPI、Uvicorn；本地 Python 在 `.venv\Scripts\python.exe`。
- 前端：`static/index.html` + 多份原生 JavaScript/CSS，存在脚本顺序和全局对象依赖。
- 持久化：`state/hub.sqlite3` 与文件目录；不是每个成员一个独立数据库文件。隔离靠后端身份、owner 查询和媒体访问校验实现。
- 媒体处理：FFmpeg/FFprobe，部分语音识别用 faster-whisper。实际路径和 GPU 可用性应现场检查。
- requirements.txt 当前列出 FastAPI、Uvicorn、cryptography、httpx、Pillow、faster-whisper；并不保证所有运维脚本的额外依赖均列在其中，保留现有虚拟环境。
- LibTV：官方 CLI，项目包含 `tools/libtv-1.2.0`；应遵循本机 libtv-cli Skill，不自行仿造接口。
- 访问：本机 `http://127.0.0.1:8765/`；团队 `https://192.168.100.10:8443/`。内网地址不是公网入口。

## 4. 模块与主要代码地图

| 模块 | 后端入口 | 前端入口/相关文件 |
| --- | --- | --- |
| 登录、成员、公司账号池、基础任务 | app.py、provider.py | app.js、index.html、login-water.js、login-tilt.js |
| 首页、自动收起侧栏、主题 | app.py | home.js、sidebar-auto.js、tokens.css、brand-theme.css、monochrome.css |
| 素材库、分类、上传、接力 | workspace.py、asset_classification.py、media_upload.py、image_upload.py、media_tools.py | workspace.js、materials.js、material-manager.js、composer-folders.css |
| 制作台 | app.py、provider.py、libtv_gateway.py | composer.js、libtv.js、libtv-profiles.js |
| 剪辑、多轨、预览、导出 | editor.py、multitrack.py、editor_media_cache.py | editor.js、timeline-model.js、timeline-layout.js、multitrack-view.js、multitrack-preview.js、editor-shell.js |
| 配音、音色、音频 | voice.py、voice_catalog.py、voice_completion.py、fishaudio.py | voice.js、editor-audio-library.js、audio-note.js |
| 字幕识别、音效 | asr.py、sfx.py | 剪辑台相关脚本、editor-sfx.js |
| AI 对话、记忆、生图、规则 | assistant_chat.py、assistant_images.py、assistant_rules.py | assistant-chat.js、assistant-layout.js、assistant-streaming-response.js |
| 飞书登录与归档 | feishu_integration.py | feishu.js、feishu.css |
| 存储状态与报告 | storage_report.py、app.py | storage-status.js、storage-report.js |
| 服务启动与重启 | run_service.py、desktop_start.py、restart_timeline_update.py | 非页面模块 |
| AI 产品知识同步 | sync_ai_readme.py、docs/AI_FEATURES.md | 生成 README_AI.md |

这是入口地图，不是所有文件的穷举；具体方法、路由、DOM ID 和脚本加载位置应以源码为准。

## 5. 账号、数据与外部服务边界

中台成员账号与上游生成账号不是同一概念。用户描述的部署规模是：TikTok 公司账号池三个子账号、LibTV 两个账号；这是运营配置，不要硬编码数量，也不要仅据本文宣称当前全部可用。

- TikTok 公司池与 LibTV 是两个独立通道，各有任务与凭据处理，不能混用任务 ID、额度或连接状态。
- LibTV 多账号隔离主要见 libtv_isolation.py 与 gateway；用户个人任务可使用公司共享上游账号，但中台数据归属不能因此变成共享。
- 不承诺 LibTV 余额不足会自动切换第二个账号；先查实际调度实现。
- AI 对话、个人记忆、生成记录和媒体访问必须按当前登录用户校验。前端筛选不能替代后端授权。
- 飞书每人授权自己的身份，并绑定固定主文件夹；导出后在其中按北京时间创建 YYMMDD 子文件夹。2026-11-03 对应 261103。
- `state/` 包含生产数据库、媒体、凭据相关文件、密钥和 TLS 私钥，禁止提交到代码仓库或打包给新对话。必要备份应连同数据库配套密钥并妥善保管。
- 不输出真实素材文案、完整 CLI 参数、cURL、会话令牌或其他成员聊天记录。只查询本次排障所需字段。

## 6. AI 规则与文档的真实机制

`assistant_rules.py` 当前从 `rules/tiktok-20261023/manifest.json` 及其列出的文件加载团队写作规则，再通过 `sync_ai_readme.build()` 附加产品知识。

这些规则是知识上下文，不会自动赋予 AI 操作中台、创建任务或跨账号读取数据的权限。个人记忆与团队规则分开。外部“母版源目录修改”不等于该 rules 目录已自动同步，接手时若涉及同步必须检查真实实现。

维护规则：修改功能、操作或权限 → 更新 `docs/AI_FEATURES.md` → 运行 `python -B sync_ai_readme.py`。不要直接手改生成的 README_AI.md。项目 AGENTS.md 是具体维护约束。剪辑台功能还需遵守 EDITOR_SHORTCUTS.md。

## 7. 最近已完成的修复与验证边界

### 配音试听

- voice.js 的 API 请求增加 30 秒超时，试听轮询等待上限 4 分钟。
- 同一页面、同文案/音色/速度的待处理试听保留 request key 和 job ID；再次点击查询原任务，提交复用幂等标识。
- 这不是跨刷新持久化保证；刷新后的行为不能据此承诺不重复提交。
- voice.py 区分音频保存 PermissionError，未知异常至少显示异常类别。
- 重启脚本加入 voice/audio 与 voice/samples 写入检查。
- 4 项 test_voice_workflow 测试通过；没有为此次修复执行真实付费试听，实际用户播放验收未记录完成。

### LibTV 诊断

- libtv_gateway.py 对非零 CLI 返回记录阶段、退出码、接口码、任务目录名、时间、脱敏错误摘录及 diagnostic_id。
- 记录写入该工作目录的 cli-diagnostics.jsonl；失败时转服务错误日志。
- 用户错误消息附排查编号与摘要；不保存完整调用参数或完整原始输出。
- 18 项 test_libtv_errors、test_libtv_submission、test_libtv_isolation 测试通过，均为模拟/隔离验证，未付费生成。
- 最近两条失败发生在 node --run，exit_code=1；旧日志丢弃了原始原因，无法追溯确定具体平台故障。诊断增强不是已修复该上游生成故障。
- 只读账号检查有有限网络重试；不要扩展为生成自动重试。下载恢复与重新生成必须严格分开。

最近部署后 HTTP/HTTPS 首页均返回正常。该健康检查不代表所有业务端到端已通过。

## 8. 运行、部署和排障

所有命令在项目根目录运行。当前 run_service.py 的 local 模式仅提供 API/UI，lan 模式拥有后台 worker。两者共享 state，必须只保留一个后台 worker；禁止直接另起多个 app.py/Uvicorn worker 与正式服务竞争。

```powershell
# 查看项目规则、改动后再操作，不覆盖他人内容
Get-Content AGENTS.md
# 正常启动入口：只补启动缺失服务，并打开页面
.\.venv\Scripts\python.exe -B desktop_start.py
# 修复部署：检查活跃任务与目录写入权限后才停止服务并重启
.\.venv\Scripts\python.exe -B restart_timeline_update.py
# 同步产品知识
.\.venv\Scripts\python.exe -B sync_ai_readme.py
```

不要绕过重启脚本的活跃任务检查。若它拒绝重启，应查看具体原因，保护正在生成、渲染、配音或上传的工作。脚本可能因当前工具沙箱对具体目录无写权限而失败；这与 Windows ACL、生产服务身份权限是不同层面，不要一概诊断成业务目录永久损坏，更不要给全盘 Everyone 权限。

常用日志：`state/restart-local.err.log`、`state/restart-lan.err.log`；桌面启动对应 `state/desktop-local.err.log`、`state/desktop-lan.err.log`。应先确认当前进程由哪种入口启动再看对应日志。LibTV 任务诊断在其工作目录的 cli-diagnostics.jsonl。

更新静态文件时检查 index.html 的版本查询参数，必要时增量更新以避免同事缓存旧代码。后端改动须安全重启后生效。

## 9. 新板块的建议接入顺序

1. 向用户明确新板块目的、输入输出，以及与素材库/制作台/剪辑台的连接点。
2. 检查现有入口、会话鉴权、任务与媒体权限模式；新建独立后端模块和独立 JS/CSS，尽量只小改 app.py 与 index.html。
3. 若有后台长任务，持久化状态并使用唯一 worker 执行；HTTP 请求返回任务编号，前端可恢复查询。状态需区分排队、处理中、完成、失败/需核对。
4. 若调用付费接口，先做 mock 测试；明确成功、失败与结果不明的边界，提供幂等提交，不因超时盲目重发。
5. 对数据新增做兼容迁移，保留现有资料；文件写入限制在本模块约定目录，媒体访问复用鉴权。
6. 测试当前用户、其他成员、管理员的可见性与操作边界；检查旧模块回归，不接入真实额度做默认自动测试。
7. 更新功能说明、执行相关测试、做浏览器验收，再安全部署。汇报已实现、已验证和未验证的部分。

可按改动范围选用测试：
```powershell
.\.venv\Scripts\python.exe -B -m unittest test_libtv_errors test_libtv_submission test_libtv_isolation -q
.\.venv\Scripts\python.exe -B -m unittest test_voice_workflow -q
node --check static/voice.js
```
其他测试按模块查看 test_hub.py、test_workspace.py、test_assistant_chat.py、test_feishu_integration.py、test_editor.py 以及 test_*.cjs。不要默认所有测试都已通过或全套测试无成本；先读测试内容。

## 10. 不能当作已有能力的规划

对话直接自动操作制作台、50–200 条批量成片流水线、按口播语义自动匹配画面、完整商业合规检测、保证防查重/防限流、平台最优流量预设，均不能仅凭历史讨论写成已完成能力。新板块名称和业务范围也尚未确定。

旧 README.md 包含早期限制、旧启动命令和阶段记录，与当前代码可能不一致；当前代码、项目 AGENTS.md、docs/AI_FEATURES.md 与相关测试优先。下面附当前生成的产品说明全文，包括快捷键和接口索引，便于单文件交接。接口索引可能包含辅助预览脚本路由，不代表正式 app 已注册该路由。

---

# 附录：当前产品功能、快捷键与接口索引

# Seedance 中台使用说明

本文是团队共享的产品知识，不赋予 AI 操作权限。AI 只依据实际提供的数据回答；不能因为知道入口就声称已点击、查询素材、提交任务或完成导出。用户账号的记忆、对话、素材权限由后端决定，不能跨账号推断。

## 整体工作流
素材管理 → 制作台生成或直接导入实拍 → 剪辑台编辑 → 命名导出 MP4 → 可选飞书归档。实拍不需要先经过 AI 生成。首页用于进入各模块，侧栏可自动收起。功能可用性取决于当前成员权限、连接配置和服务状态。

## 素材管理
按人物、产品、场景、视频、音频、其他六类组织素材。支持本地文件选择、拖入上传、名称搜索、类型及日期筛选、预览、重命名与分类调整、下载和选择用于生成。素材选择窗口先选文件夹，再选素材，右下角确认或取消；确认后与本地上传参考一起显示缩略图。
自动分类是独立的识别流程：视频和音频按媒体类型分类，图片识别产品、人物、场景或其他；人工分类优先。分类结果不是商品事实证明，错误分类可人工纠正。不要声称文字助理可以自行浏览整个素材库。

## 制作台
生成渠道按当前中台账号在本浏览器记住；没有已保存选择时必须明确选择公司账号池或 LibTV。LibTV 账号列表尚未加载或未选中有效账号时阻止提交，不静默使用默认账号。公司池与 LibTV 的任务记录分别对应各自平台。
选择 TikTok 公司账号池或 LibTV 通道；填写提示词并选择参考素材、时长、条数及该通道提供的模型参数。普通生成支持文字及参考素材；首尾帧模式用首帧和可选尾帧控制画面。接力生成从已有视频提取参考帧或原声，并继续编写下一段提示词、勾选继承参考或添加其他参考。
多组提示词各有参数，任务与结果区域显示排队、生成、完成或失败状态。完成后可以播放、下载 MP4、接力生成、加入剪辑、查看参数、提取帧和原声。提交会消耗对应服务额度。状态未知不等于失败，不能建议反复提交以免重复计费。
TikTok 公司连接与 LibTV 账号配置分开。LibTV 多账号凭据按配置隔离；不能承诺余额不足自动切换账号。模型、分辨率及上传限制以当前通道实际选项和校验为准，不沿用旧 README 的早期限制。

## 剪辑台
左侧为素材与音频，右侧为配音、字幕、文本、动画、变速、版本、导出等面板，中间为画面预览，下方是多轨时间轴。视频、图片、字幕与音频可在时间轴组合制作，支持独立位置、拖动、裁剪、分割、删除、撤销重做、组合与复合片段。原声跟随视频，分离后作为独立音频轨编辑。复合片段可展开；不要承诺未实现的嵌套或整个复合块裁切。
播放头上限为最后有效帧；预览轴悬停预览不移动实际播放头，移出恢复。支持磁吸、缩放、框选以及已实现的快捷键。输入文字时保留输入行为，不能拦截操作系统未传给网页的快捷键。
可保存剪辑和恢复版本。字幕支持编辑与样式设置、语音识别等现有面板操作；具体动画、变速与导出参数以界面为准。不要把规划中的批量成片、自动匹配口播画面、平台防限流等当作已实现功能。

## 配音与音频
右侧配音制作使用手动文案，音色库支持名称及语言筛选、试听当前文案、选择与收藏音色。试听文案及正式生成可能消耗 API 额度；平台余额与 API 余额可能独立。完整配音生成 MP3，长文案可能由后台分段处理再合成。生成音频自动进入音频素材，可用于时间轴编辑，上传音频也可使用；生成素材与时间轴音轨不是同一对象。

## 导出与飞书
导出前命名视频，导出记录按日期组织，可查看状态、预览成片、下载 MP4。每次导出名字独立于工程名，范围导出以实际选中范围为准。飞书上传是导出之后的独立阶段，等待上传不代表视频已渲染完成。
成员绑定自己的飞书身份与固定云盘主文件夹，启用自动上传后，系统在主文件夹按北京时间创建 YYMMDD 日期子文件夹，例如 2026-11-03 为 261103。设置影响之后提交的导出。失败时先查看归档设置中的具体状态，可重试上传已有成片；不需要因为上传失败重新生成视频。应用可用范围、授权、目录访问权限、网络和本地导出文件都影响结果。

## AI 助理
全局浮动入口，可拖动、调整大小、展开和还原。支持历史对话、新对话、删除对话、文本及图片附件、拖拽文件，并可在输入框直接粘贴剪贴板图片。文字回答显示等待状态和流式呈现效果，完成后可以复制并标记是否有帮助。对话与生图分开；生图走 LibTV Image 2.5 Fast，比例与清晰度从画面设置选择。生成图片可以下载或用作参考；这不代表文字对话具有自动操作制作台的工具权限。
个人记忆由成员在个人记忆入口保存，按账号隔离；团队母版写作规则是共享上下文，仅用于相关创作任务。文档自动更新不等于母版源文件已自动同步。管理员连接设置不对普通成员开放。

## 管理与排障
公司账号池维护平台连接；团队成员管理维护中台账号及密码重置，不能查看原密码；操作记录辅助排查。管理员与普通成员权限不同。任务错误先区分上传、提交、平台生成、下载、渲染、飞书上传阶段；请求失败不必然意味着额度未扣除。没有日志证据时说明不确定，不猜测具体上游原因。
中台服务运行在执行电脑，关闭服务会影响团队访问。网络超时、凭据失效、磁盘写入失败、空间不足和上游额度不足是不同问题。禁止在说明或对话中暴露密钥、Cookie、数据库记录及其他成员资料。

## 文档维护约定
本文件维护人工确认的操作语义。新增、删除、重命名功能或更改权限时，开发者必须更新相关章节，再执行 python -B sync_ai_readme.py。生成的 README_AI.md 包含当前代码入口与快捷键清单，每次文字对话也检查源文件变化并重新生成。自动提取只能发现代码入口，不能自动证明新功能已经可用；新入口未补充操作说明时，AI 应谨慎说明而非推测。

配音试听请求有 30 秒网络超时、4 分钟状态等待上限。等待超时后，同一页面内再次点击同一文案与音色会查询原任务，提交请求复用幂等标识，不会自动重复生成。音频目录写入失败会明确提示权限问题。

LibTV 失败会记录操作阶段、任务编号、退出码、接口错误码、脱敏错误摘要及排查编号。页面展示排查编号与错误摘要；任务目录 cli-diagnostics.jsonl 保存诊断，写入失败则转存服务错误日志。诊断增强不会自动重试生成；历史已丢弃的原始错误无法恢复。

## 自动同步的界面标题
存储管理、每一步创作，都在、这里、。、素材管理、项目总览、制作台、剪辑台、公司账号池、团队成员、操作记录、修改密码

## 当前快捷键与编辑限制
# 剪辑台快捷键与验收约定

后续增加或检查剪辑功能时，同步检查快捷键、按钮提示和输入焦点。优先采用团队使用的 CapCut Windows 默认键位，团队自定义键位另行记录。CapCut 当前快捷键面板为最终核对依据，不把未核实键位宣称为官方事实。

现有映射：Ctrl+A 时间轴全选；Ctrl+G 组合；Ctrl+Shift+G 取消组合；Alt+G 创建复合片段；Alt+Shift+G 解除复合片段；Ctrl+B 分割；Q 波纹裁剪入点；W 波纹裁剪出点；Ctrl+Shift+S 分离音频；Delete/Backspace 删除；Ctrl+Z 撤销；Ctrl+Shift+Z / Ctrl+Y 重做；Space 播放/暂停；左右方向键逐帧；Ctrl+/ 快捷键设置；Ctrl+S 保存；Ctrl+E 导出；Ctrl+= / Ctrl+- 缩放时间轴；Ctrl+滚轮 以鼠标位置为锚点缩放。

剪辑页使用 capture 阶段处理已实现命令，阻止浏览器默认行为。输入框、可编辑文本、输入法合成和模态对话框保留输入行为。操作系统未派发给网页的快捷键无法抢占。

检查按钮和快捷键调用同一逻辑、其他页面不触发、长按不重复执行破坏性操作。对应脚本：test_editor_shortcuts.cjs、test_editor_ripple.cjs、test_editor_bundles.cjs、test_editor_insertion.cjs、test_editor_trim.cjs、test_editor_audio_drag.cjs、test_editor.py。

波纹裁剪（Q/W）：Q 把片段入点裁到播放头，W 把出点裁到播放头，播放头必须落在片段内部，裁剪后至少保留 0.1 秒；主轨磁吸开启时其后片段自动前移补位，磁吸关闭时保留空隙。优先当前单选片段，播放头在别的片段上时用播放头所在片段。复用已有 trim 与布局补齐，因此支持 Ctrl+Z 撤销，沿着播放头连续按可逐段收窄。只作用于视频片段（含分离后的原声由音频面板处理），复合片段需先双击展开。

滚轮缩放：Ctrl/⌘ + 滚轮在时间轴区域按鼠标所在时间缩放 12–80 px/s，缩放后把该时间点固定在鼠标下，右侧缩放滑块同步；未按 Ctrl 时滚轮保持原有滚动。时间轴短于窗口宽度时没有可滚动余量，只在左边缘重新排布。

快捷键面板把 Q/W 归到「剪辑」组（CapCut 标记），「Ctrl+滚轮」是固定条目：只做说明，不参与录制改写，也不参与键盘事件解析，避免与 Ctrl+= / Ctrl+- 冲突。

当前为多轨时间轴：视频、字幕和音频有独立时间位置，可跨轨移动，普通删除保留其他片段位置。组合/复合片段元数据随项目保存，预览和导出保留原始片段。复合片段在单独显示行收起，双击展开编辑内部片段；不支持嵌套或直接裁剪、分割整个复合块。锁定音轨阻止整组移动和删除。

官方基础操作参考：https://www.capcut.com/resource/pc-professional-video-editor （分割、播放、逐帧）。

多轨验收：test_multitrack_model.cjs、test_multitrack_preview.cjs，以及 test_editor.py 的拼接边界/叠轨像素测试。播放头和预览时间上限是最后有效帧；帧率当前统一 24 fps。原声属于视频片段，只有分离后单列音轨。

预览轴：时间轴工具栏开关，悬停逐帧预览但不移动播放头；移出、滚动、开始拖动时恢复。播放中禁用悬停预览。本次未新增快捷键：既有观察记录没有预览轴键位证据，待团队 CapCut 快捷键面板核实后再绑定。


## 自动提取的代码接口索引
这是代码存在性索引，不代表 AI 有调用权限、功能已验收或平台连接可用。
- `GET /`（app.py）
- `GET /api/accounts`（app.py）
- `GET /api/admin/storage-report`（app.py）
- `GET /api/assets/{asset_id}`（app.py）
- `GET /api/audit`（app.py）
- `GET /api/capabilities`（app.py）
- `GET /api/compositions`（app.py）
- `GET /api/me`（app.py）
- `GET /api/status`（app.py）
- `GET /api/storage-status`（app.py）
- `GET /api/tasks`（app.py）
- `GET /api/tasks/{task_id}/video`（app.py）
- `GET /api/users`（app.py）
- `POST /api/accounts`（app.py）
- `POST /api/accounts/{account_id}/sync-subaccounts`（app.py）
- `POST /api/accounts/{account_id}/toggle`（app.py）
- `POST /api/assets`（app.py）
- `POST /api/compositions`（app.py）
- `POST /api/login`（app.py）
- `POST /api/logout`（app.py）
- `POST /api/password`（app.py）
- `POST /api/setup`（app.py）
- `POST /api/tasks`（app.py）
- `POST /api/tasks/{task_id}/action`（app.py）
- `POST /api/users`（app.py）
- `POST /api/users/{uid}`（app.py）
- `POST /api/users/{uid}/reset-password`（app.py）
- `GET /api/assistant/memory`（assistant_chat.py）
- `GET /api/assistant/status`（assistant_chat.py）
- `GET /api/assistant/threads`（assistant_chat.py）
- `GET /api/assistant/threads/{tid}`（assistant_chat.py）
- `POST /api/assistant/memory`（assistant_chat.py）
- `POST /api/assistant/settings`（assistant_chat.py）
- `POST /api/assistant/threads`（assistant_chat.py）
- `POST /api/assistant/threads/{tid}/delete`（assistant_chat.py）
- `POST /api/assistant/threads/{tid}/send`（assistant_chat.py）
- `POST /api/assistant/threads/{tid}/turns/{turn}/recover`（assistant_chat.py）
- `GET /api/editor/asr`（editor.py）
- `GET /api/editor/exports`（editor.py）
- `GET /api/editor/exports/{eid}/video`（editor.py）
- `GET /api/editor/library`（editor.py）
- `GET /api/editor/projects`（editor.py）
- `GET /api/editor/projects/{pid}/versions`（editor.py）
- `GET /api/editor/selection-export-capability`（editor.py）
- `GET /api/editor/thumbnail/{task_id}`（editor.py）
- `GET /api/editor/waveform/{task_id}`（editor.py）
- `POST /api/editor/asr/recognize`（editor.py）
- `POST /api/editor/footage`（editor.py）
- `POST /api/editor/projects`（editor.py）
- `POST /api/editor/projects/{pid}/export`（editor.py）
- `POST /api/editor/projects/{pid}/restore`（editor.py）
- `GET /api/feishu/public`（feishu_integration.py）
- `GET /api/feishu/start`（feishu_integration.py）
- `GET /api/feishu/status`（feishu_integration.py）
- `GET /api/feishu/uploads`（feishu_integration.py）
- `POST /api/feishu/config`（feishu_integration.py）
- `POST /api/feishu/preferences`（feishu_integration.py）
- `POST /api/feishu/uploads/{eid}/retry`（feishu_integration.py）
- `GET /api/libtv/jobs`（libtv_gateway.py）
- `GET /api/libtv/profiles`（libtv_gateway.py）
- `GET /api/libtv/profiles/{pid}/setup`（libtv_gateway.py）
- `GET /api/libtv/status`（libtv_gateway.py）
- `POST /api/libtv/connect`（libtv_gateway.py）
- `POST /api/libtv/jobs`（libtv_gateway.py）
- `POST /api/libtv/jobs/{jid}/recover`（libtv_gateway.py）
- `POST /api/libtv/profiles`（libtv_gateway.py）
- `POST /api/libtv/profiles/{pid}/verify`（libtv_gateway.py）
- `GET /api/media/source/{tid}`（media_tools.py）
- `POST /api/media/extract`（media_tools.py）
- `POST /api/media/vocals`（media_tools.py）
- `GET /__fixture`（preview_material_manager.py）
- `GET /api/editor/sfx`（sfx.py）
- `GET /api/editor/sfx/{sfx_id}/audio`（sfx.py）
- `POST /api/editor/sfx/{sfx_id}/adopt`（sfx.py）
- `POST /api/editor/sfx/{sfx_id}/favorite`（sfx.py）
- `DELETE /api/voice/voices/{vid}`（voice.py）
- `GET /api/voice/catalog`（voice.py）
- `GET /api/voice/config`（voice.py）
- `GET /api/voice/jobs`（voice.py）
- `GET /api/voice/jobs/{jid}`（voice.py）
- `GET /api/voice/jobs/{jid}/audio`（voice.py）
- `GET /api/voice/voices`（voice.py）
- `GET /api/voice/voices/{vid}/sample`（voice.py）
- `POST /api/voice/config`（voice.py）
- `POST /api/voice/jobs`（voice.py）
- `POST /api/voice/jobs/{jid}/asset`（voice.py）
- `POST /api/voice/voices`（voice.py）
- `POST /api/voice/voices/{vid}/favorite`（voice.py）
- `POST /api/voice/voices/{vid}/sample`（voice.py）
- `PUT /api/voice/voices/{vid}`（voice.py）
- `GET /api/workspace/continuation`（workspace.py）
- `GET /api/workspace/links`（workspace.py）
- `GET /api/workspace/materials`（workspace.py）
- `GET /api/workspace/overview`（workspace.py）
- `POST /api/workspace/continuation`（workspace.py）
- `POST /api/workspace/link`（workspace.py）
- `POST /api/workspace/materials/{aid}`（workspace.py）
- `POST /api/workspace/materials/{aid}/classify`（workspace.py）
- `POST /api/workspace/materials/{aid}/delete`（workspace.py）

源内容指纹：`18f85930e003ef12d450e7f34f5fdc9d46afb7cdd1d8c0fbd4d8b573ef67e955`

