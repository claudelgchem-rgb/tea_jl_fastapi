#!/usr/bin/env bash
# Launch the TEA FastAPI app. Requires Python 3.12+ (thermosteam needs it).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3.12}
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  .venv/bin/pip install -U pip setuptools wheel
  .venv/bin/pip install -r requirements.txt
  .venv/bin/pip install biosteam thermosteam
fi
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
