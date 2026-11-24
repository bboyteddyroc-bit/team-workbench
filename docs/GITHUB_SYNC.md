# GitHub 源码同步

远程仓库：https://github.com/bboyteddyroc-bit/team-workbench （私有）。
当前执行机的项目目录即仓库工作目录，修改后在这里提交，不另维护一份源码副本。

## 每次更新
1. 检查 git status 与修改差异，只提交本次已验证的改动，不能混入其他智能体未完成的修改。
2. 检查没有加入凭据、真实请求、团队数据库、聊天记忆、日志或业务素材。
3. 运行与改动相关的检查；更新功能说明时执行 sync_ai_readme.py。
4. git add 指定文件，然后 git commit，再 git push origin main。
5. 核验远程提交。推送失败应明确报告，不将本地提交当成已同步。

GitHub 保存代码版本，不备份生产数据，不自动部署或重启服务器。后续功能完成后应同步提交；正在编写的未完成修改不自动上传。

## 新机器恢复
使用 git clone --recurse-submodules 获取源码及 Kalodata 依赖。创建 Python 环境并安装 requirements.txt。按部署说明另外安装 FFmpeg、LibTV CLI 等本机依赖；tools 中的二进制未上传。
配置密钥、账号授权与运行数据需要安全迁移，不能从此源码仓库恢复。首次上传不含桌面客户端的独立工程或安装包。

## 上传范围
默认纳入根目录 Python/CJS 源码、前端 static、依赖清单、README、选定设计与功能说明、规则文件。其余目录默认排除。新目录需审核后明确加入 .gitignore 白名单。扫描不能替代代码审查。
