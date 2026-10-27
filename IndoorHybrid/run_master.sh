#!/bin/sh
set -e
cd "$(dirname "$0")"
PYTHON=python3
if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; fi
exec "$PYTHON" master_hybrid_gui.py
