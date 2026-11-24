"""Bounded offline checks; never initializes the real application state."""
from pathlib import Path
import subprocess
import sys
import unittest

root = Path(__file__).resolve().parent
project_python = root / '.venv' / 'Scripts' / 'python.exe'
if Path(sys.executable).resolve() != project_python.resolve():
    raise SystemExit(subprocess.call([str(project_python), '-B', str(root / 'verify_classification_fix.py')]))
for name in ('app.py', 'asset_classification.py', 'assistant_chat.py', 'workspace.py', 'test_asset_classification.py'):
    compile((root / name).read_text(encoding='utf-8'), str(root / name), 'exec')
print('Python syntax: 5 files OK', flush=True)
for name in ('static/materials.js', 'static/assistant-chat.js'):
    subprocess.run([r'D:\共卓\CO-DROP-AI\resources\dsh\runtime\node.exe', '--check', str(root / name)], check=True)
print('JavaScript syntax: 2 files OK', flush=True)
suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in ('test_asset_classification', 'test_hub'))
result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
