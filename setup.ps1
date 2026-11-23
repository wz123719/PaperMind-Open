[CmdletBinding()]
param([switch]$CoreOnly, [switch]$WithDocling)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($CoreOnly -and $WithDocling) { throw 'Choose either -CoreOnly or -WithDocling.' }
foreach ($tool in 'python','node','pnpm') {
    if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing $tool. See README.md for setup requirements." }
}
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
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
    pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
    pnpm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
