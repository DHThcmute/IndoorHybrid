#!/bin/sh
set -e
cd "$(dirname "$0")"
exec python3 anchor_gui.py
