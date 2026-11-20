$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
    throw 'Create .env from .env.example and fill in your model API key first.'
}
# Existing process environment values take precedence. Never print credentials.
& '.\.venv\Scripts\python.exe' -c "from dotenv import load_dotenv; load_dotenv('.env', override=False); import runpy; runpy.run_module('backend.worker', run_name='__main__')"
exit $LASTEXITCODE
