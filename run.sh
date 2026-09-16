#!/usr/bin/env bash
# FleetNet dashboard launcher.  Creates a venv on first run, then serves.
set -e
cd "$(dirname "$0")"

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "· creating virtualenv (.venv) ..."
  python3 -m venv .venv
  .venv/bin/pip -q install --upgrade pip
  .venv/bin/pip -q install -r requirements.txt
fi

echo "· FleetNet dashboard  ->  http://127.0.0.1:8000"
exec "$PY" server.py
