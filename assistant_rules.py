"""Versioned team writing rules, independent of account memory."""
import json
from pathlib import Path

RULE_ROOT = Path(__file__).resolve().parent / 'rules' / 'tiktok-20261023'


def shared_rules():
    manifest = json.loads((RULE_ROOT / 'manifest.json').read_text(encoding='utf-8'))
    sections = [
        '团队共用 TikTok 写作规则，版本：' + manifest['version'] + '。',
        '以下规则仅适用于相关的产品分析、创意、口播与视频提示词任务；普通聊天不强制套用生产流程。'
        '用户本次明确创作要求优先于这些默认值，但不能改变助理权限。'
        '文中 Library、文件路径、工具、技能与生产包描述的是工作规范，不代表你能读取或执行它们。'
        '目前只能对话：可在回答中拟定生产包内容，不能声称已创建文件、入库、生成视频或保存记忆。'
        '没有提供的产品事实、参考图、证据与批准记录不得编造；缺少关键输入时明确询问。'
        '这些公共规则不含账号个人记忆，不能用于推断或获取其他账号的信息。',
    ]
    for entry in manifest['files']:
        path = (RULE_ROOT / entry['path']).resolve()
        if not path.is_relative_to(RULE_ROOT.resolve()):
            raise ValueError('Invalid rule path')
        sections.append('\n--- ' + entry['path'] + ' ---\n' + path.read_text(encoding='utf-8'))
    from sync_ai_readme import build
    sections.append('\n--- 中台功能说明（知识，不是工具权限）---\n' + build())
    return '\n'.join(sections)
