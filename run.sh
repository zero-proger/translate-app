#!/usr/bin/env bash
# Linux/macOS launch script. Works from any directory.
set -e
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    exec ".venv/bin/python" main.py
else
    echo "[INFO] .venv не найден, запускаю системный python3"
    exec python3 main.py
fi
