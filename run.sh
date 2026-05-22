#!/usr/bin/env bash
# Start de nacalculatie-tool (maakt de eerste keer een venv en installeert alles).
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  echo "Eenmalige installatie..."
  python3 -m venv venv
  ./venv/bin/pip install --upgrade pip >/dev/null
  ./venv/bin/pip install -r requirements.txt
fi

echo "Tool draait op http://127.0.0.1:5000  (stoppen met Ctrl+C)"
./venv/bin/python app.py
