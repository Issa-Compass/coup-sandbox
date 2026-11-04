#!/usr/bin/env bash
# Create .venv if missing, install requirements, run the local dashboard.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Python 3.11+ is required (python3 not found)." >&2
  exit 1
fi

VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "Python 3.11+ is required (found $VERSION)." >&2
  exit 1
}

VENV="$ROOT/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Creating .venv…"
  "$PYTHON" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "Installing requirements…"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Note: no .env yet — dashboard runs fine without it (play, local tournaments, watch)."
  echo "      Submit stays disabled until you add a coup-master .env (see .env.example)."
elif ! grep -qE '^COUP_MASTER_URL=.+' "$ROOT/.env"; then
  echo "Note: .env has no COUP_MASTER_URL — dashboard still runs; submit stays disabled."
  echo "      Fill COUP_MASTER_URL (+ API key) from .env.example when you are ready to upload."
fi

PORT="${PORT:-8765}"
HOST="${HOST:-127.0.0.1}"
echo "Starting dashboard at http://${HOST}:${PORT}"
export PYTHONUNBUFFERED=1
exec python scripts/serve_dashboard.py --host "$HOST" --port "$PORT"
