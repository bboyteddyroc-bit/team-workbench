"""Build public AI product knowledge from explicit documentation and source only."""
import ast
import hashlib
import os
from pathlib import Path
from threading import RLock
from html.parser import HTMLParser
ROOT = Path(__file__).resolve().parent
LOCK = RLock()
_cached = None
class Navigation(HTMLParser):
    def __init__(self):
        super().__init__(); self.items = []; self.active = False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'h1': self.active = True
    def handle_endtag(self, tag):
        if tag == 'h1': self.active = False
    def handle_data(self, data):
        if self.active and data.strip(): self.items.append(data.strip())
def build():
    global _cached
    with LOCK:
        sources = [ROOT/'docs/AI_FEATURES.md', ROOT/'EDITOR_SHORTCUTS.md', ROOT/'static/index.html']
        sources += sorted(p for p in ROOT.glob('*.py') if not p.name.startswith(('test_', '.', 'probe_', 'diagnose_', 'inspect_')))
        blobs = [(p, p.read_bytes()) for p in sources]
        digest = hashlib.sha256(b''.join(p.name.encode()+b for p,b in blobs)).hexdigest()
        if _cached and _cached[0] == digest: return _cached[1]
        nav = Navigation(); nav.feed((ROOT/'static/index.html').read_text(encoding='utf-8-sig'))
        routes = set()
        for p,b in blobs:
            if p.suffix != '.py': continue
            tree = ast.parse(b.decode('utf-8-sig'))
            for n in ast.walk(tree):
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
                for d in n.decorator_list:
                    if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr in ('get','post','put','delete','patch') and d.args and isinstance(d.args[0],ast.Constant) and isinstance(d.args[0].value,str):
                        routes.add((p.name,d.func.attr.upper(),d.args[0].value))
        text = (ROOT/'docs/AI_FEATURES.md').read_text(encoding='utf-8')
        text += '\n## 自动同步的界面标题\n' + '、'.join(dict.fromkeys(nav.items))
        text += '\n\n## 当前快捷键与编辑限制\n' + (ROOT/'EDITOR_SHORTCUTS.md').read_text(encoding='utf-8')
        text += '\n\n## 自动提取的代码接口索引\n这是代码存在性索引，不代表 AI 有调用权限、功能已验收或平台连接可用。\n'
        text += '\n'.join('- `%s %s`（%s）' % (method,path,file) for file,method,path in sorted(routes))
        text += '\n\n源内容指纹：`' + digest + '`\n'
        out = ROOT/'README_AI.md'
        if not out.exists() or out.read_text(encoding='utf-8') != text:
            import tempfile
            fd,name = tempfile.mkstemp(prefix='.ai-readme-',suffix='.tmp',dir=ROOT)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f: f.write(text)
                os.replace(name,out)
            finally:
                Path(name).unlink(missing_ok=True)
        _cached = (digest,text)
        return text
if __name__ == '__main__':
    build()
    print('README_AI.md updated')
