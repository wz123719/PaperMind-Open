[CmdletBinding()]
param([switch]$CoreOnly, [switch]$WithDocling)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($CoreOnly -and $WithDocling) { throw 'Choose either -CoreOnly or -WithDocling.' }

function Find-Python312 {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { return $cmd.Source }
    foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Python312\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\ProgramData\anaconda3\python.exe",
        "$env:USERPROFILE\miniconda3\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw 'Missing Python 3.12. Install Python 3.12 first.'
}

$sysPython = Find-Python312
if (!(Get-Command node -ErrorAction SilentlyContinue)) { throw 'Missing node. See README.md for setup requirements.' }
$pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
if (!$pnpmCmd) {
    Write-Host 'Installing pnpm via npm...'
    npm install --global pnpm@11.25.0
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install pnpm' }
}

if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $sysPython -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed' }
}
$lock = if ($CoreOnly) { 'backend\requirements-core.lock.txt' } else { 'backend\requirements.lock.txt' }
if ($CoreOnly) {
    Write-Host 'Installing basic PDF reading dependencies.'
} else {
    Write-Host 'Installing PaperMind, Docling and PyTorch. The first download can take a while.'
}
& '.\.venv\Scripts\python.exe' -m pip install --timeout 120 --retries 5 -r $lock
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
Push-Location frontend
try {
    pnpm install
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
    pnpm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
if (!(Test-Path -LiteralPath '.env')) {
    [IO.File]::Copy((Join-Path $PSScriptRoot '.env.example'),(Join-Path $PSScriptRoot '.env'))
}
Write-Host 'Setup complete! Double-click PaperMind.vbs or run .\start-desktop.ps1 to launch PaperMind Desktop.'
