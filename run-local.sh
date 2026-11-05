#!/usr/bin/env sh
# B8/T6: macOS/Linux equivalent of START_PRAMAAN.bat (API + web UI on 127.0.0.1).
# Usage: ./run-local.sh            (first run: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt)
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PRAMAAN_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3
export PYTHONPATH="$ROOT/launcher" PRAMAAN_DATA="${PRAMAAN_DATA:-$ROOT/.demo/runtime}"
if [ ! -f "$PRAMAAN_DATA/demo-state.json" ]; then
  echo "Creating synthetic demo data in $PRAMAAN_DATA"
  "$PYTHON" -m Pramaan.backend.demo reset --name runtime
fi
"$PYTHON" -m uvicorn Pramaan.backend.app:app --host 127.0.0.1 --port 8000 --no-access-log &
API=$!
trap 'kill $API 2>/dev/null' EXIT INT TERM
(cd "$ROOT/web" && { [ -d node_modules ] || npm ci; } && npm run dev)
