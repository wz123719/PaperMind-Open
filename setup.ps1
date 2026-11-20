[CmdletBinding()]
param([switch]$WithDocling)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
foreach ($tool in 'python','node','pnpm') {
    if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing $tool. See README.md for setup requirements." }
}
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed' }
}
$lock = if ($WithDocling) { 'backend\requirements.lock.txt' } else { 'backend\requirements-core.lock.txt' }
& '.\.venv\Scripts\python.exe' -m pip install --timeout 60 -r $lock
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
Push-Location frontend
try {
    pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
    pnpm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
