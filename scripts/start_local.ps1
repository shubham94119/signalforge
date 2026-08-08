$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $repoRoot "src"
$env:APP_ENV = if ($env:APP_ENV) { $env:APP_ENV } else { "development" }
$env:DEMO_SEED = if ($env:DEMO_SEED) { $env:DEMO_SEED } else { "1" }

if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process python.exe -ArgumentList "-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $repoRoot -WindowStyle Hidden
}
if (-not (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process python.exe -ArgumentList "-m", "http.server", "5173", "--bind", "127.0.0.1", "--directory", (Join-Path $repoRoot "apps\web") -WorkingDirectory $repoRoot -WindowStyle Hidden
}
Write-Output "UI: http://127.0.0.1:5173"
Write-Output "API: http://127.0.0.1:8000/docs"
