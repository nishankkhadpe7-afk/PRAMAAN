# Starts Pramaan's API against the same local data directory used by credential issuance.
# Run from the Pramaan directory after stopping any older API on port 8000.
$ErrorActionPreference = 'Stop'
# Tracked portable shim (works for any checkout folder name and on case-sensitive file systems).
$env:PYTHONPATH = Join-Path $PWD.Path 'launcher'
$env:PRAMAAN_DATA = Join-Path $PWD.Path '.demo/runtime'

if (-not (Test-Path -LiteralPath $env:PRAMAAN_DATA)) {
    throw "Demo data is missing. Run: py -m Pramaan.backend.demo reset"
}

$python = if (Test-Path '.venv-p4/Scripts/python.exe') { '.venv-p4/Scripts/python.exe' } elseif (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
& $python -m uvicorn Pramaan.backend.app:app --host 127.0.0.1 --port 8000 --no-access-log
