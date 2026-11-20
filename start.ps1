[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [ValidateRange(1024,65535)][int]$WebPort = 5173,
    [ValidateRange(1024,65535)][int]$ApiPort = 8765
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$node = Get-Command node.exe -ErrorAction SilentlyContinue
if (!$node -or !(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath 'frontend/node_modules/vite/bin/vite.js')) {
    throw 'Install Python, Node.js and pnpm, then run .\setup.ps1 first.'
}
$options = @('--web-port',$WebPort,'--api-port',$ApiPort,'--node',$node.Source)
if ($NoBrowser) { $options += '--no-browser' }
if ($CheckOnly) { $options += '--check-only' }
& $python -m backend.launcher @options
exit $LASTEXITCODE
