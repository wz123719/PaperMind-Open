[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$NoWindow,
    [ValidateRange(1024,65535)][int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    throw '请先运行 .\setup.ps1 完成首次环境准备。'
}
$options = @('--port', $Port)
if ($CheckOnly) { $options += '--check-only' }
if ($NoWindow) { $options += '--no-window' }
& $python -m backend.desktop @options
exit $LASTEXITCODE
