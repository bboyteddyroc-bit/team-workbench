$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw '项目虚拟环境不存在，请先在此目录运行 uv venv .venv，然后 uv pip install --python .venv/Scripts/python.exe -r requirements.txt'
}
& $python -B app.py
exit $LASTEXITCODE
