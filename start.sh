#!/usr/bin/env bash
# Start both servers for local development.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$ROOT/backend/ventureiq.db" ]; then
  echo "No database found — running bootstrap first (~80s)…"
  (cd "$ROOT/backend" && .venv/bin/python scripts/bootstrap.py)
fi

echo "Starting API on :8000 and UI on :5173…"
(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --reload --port 8000) &
API_PID=$!
(cd "$ROOT/frontend" && npm run dev) &
UI_PID=$!

trap 'kill $API_PID $UI_PID 2>/dev/null' EXIT INT TERM
wait
