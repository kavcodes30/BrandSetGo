#!/usr/bin/env bash
# BrandSetGo launcher for macOS and Linux.   ./run.sh [reset]
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo "  BrandSetGo  -  brand governance workspace"
echo "============================================================"

if [[ "${1:-}" == "reset" ]]; then
  echo "[i] Removing the demo database..."
  rm -f backend/brandsetgo.db
fi

command -v python3 >/dev/null || { echo "[X] python3 not found. Install Python 3.11+."; exit 1; }

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "[1/3] Creating the Python environment..."
  python3 -m venv backend/.venv
fi

echo "[2/3] Installing dependencies..."
backend/.venv/bin/python -m pip install --quiet --upgrade pip
backend/.venv/bin/python -m pip install --quiet -r backend/requirements.txt

[[ -f backend/.env ]] || cp backend/.env.example backend/.env
if ! grep -Eq '^SARVAM_API_KEY=.+' backend/.env; then
  echo "[3/3] Sarvam AI key (press Enter to skip and run deterministically)"
  read -r -p "      Key: " SK || true
  if [[ -n "${SK:-}" ]]; then
    SARVAM_KEY="$SK" backend/.venv/bin/python scripts/set_key.py
    echo "      Saved to backend/.env (git-ignored)."
  fi
else
  echo "[3/3] Sarvam key already configured."
fi

echo ""
echo "  App  http://localhost:8000"
echo "  API  http://localhost:8000/docs"
echo "  Ctrl+C stops the server."
echo ""

cd backend && exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
