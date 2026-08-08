$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $repoRoot "src"
python -m unittest discover -s (Join-Path $repoRoot "tests") -p "test_*.py" -v
