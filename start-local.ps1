# Starts Pramaan's API against the same local data directory used by credential issuance.
# Run from the Pramaan directory after stopping any older API on port 8000.
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Split-Path -Parent $PWD.Path
$env:PRAMAAN_DATA = Join-Path $PWD.Path '.demo/runtime'

if (-not (Test-Path -LiteralPath $env:PRAMAAN_DATA)) {
    throw "Demo data is missing. Run: py -m Pramaan.backend.demo reset"
}

py -m uvicorn Pramaan.backend.app:app --host 127.0.0.1 --port 8000 --no-access-log
