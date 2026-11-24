param([string]$LanAddress='192.168.100.10')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING='utf-8'
. (Join-Path $PSScriptRoot 'project-runtime.ps1')
& $ProjectPython -B lan.py --host $LanAddress
exit $LASTEXITCODE
