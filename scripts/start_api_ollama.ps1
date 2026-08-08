$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $PSScriptRoot "..\src"
$env:DEMO_SEED = "1"
$env:MODEL_ENDPOINT = "http://127.0.0.1:11434/v1/chat/completions"
$env:MODEL_API_KEY = "ollama"
$env:MODEL_NAME = "llama3.2:3b"
$env:MODEL_TIMEOUT_SECONDS = "180"
Start-Process python.exe -ArgumentList "-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "8000" -WindowStyle Hidden
Write-Output "Started Incident Intelligence API with Ollama model $env:MODEL_NAME"
