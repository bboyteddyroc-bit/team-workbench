# Dot-source only; never chooses a PATH or unrelated Python installation.
$ProjectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $ProjectPython -PathType Leaf)) {
    throw '项目 Python 环境不存在；请先恢复本项目 .venv，不使用系统 Python 回退。'
}
& $ProjectPython -B -c 'import fastapi,uvicorn,cryptography,PIL'
if ($LASTEXITCODE -ne 0) { throw '项目 Python 依赖检查失败，未启动服务。' }
