# Seedance Hub 项目补充规则

增加或检查剪辑台功能时，遵守 [EDITOR_SHORTCUTS.md](EDITOR_SHORTCUTS.md) 的键位、焦点处理和回归验证约定。不得宣称尚未实现的功能或未执行的浏览器验收已完成。

## 中台设计基础规则
所有新增或调整的页面、内容、功能、模块和组件，必须遵守 [docs/DESIGN_BASELINE.md](docs/DESIGN_BASELINE.md)。先复用现有组件和样式变量，保持视觉、布局、交互及状态一致；缺失能力渐进补充为公共组件。交付包含功能实现、统一风格检查和相关回归，不擅自换肤或全站重构。

## AI 产品说明同步
新增、删除、重命名功能或改变操作、权限时，必须同步更新 `docs/AI_FEATURES.md`，执行 `python -B sync_ai_readme.py`。`README_AI.md` 是生成文件，不直接修改。接口索引自动提取不替代操作说明，未实现功能不得记为可用；禁止加入 state 数据、成员信息或凭据。

## GitHub 同步
本项目已关联私有仓库 bboyteddyroc-bit/team-workbench。用户要求后续完成的优化同步 GitHub，遵守 docs/GITHUB_SYNC.md：检查本次差异、敏感信息和相关验证后提交并推送；不得混入其他智能体未完成的改动。推送不是部署，禁止因同步自动重启服务。状态数据、凭据、业务素材不纳入版本库。
