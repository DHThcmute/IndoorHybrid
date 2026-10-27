#!/bin/sh
set -e
cd "$(dirname "$0")"
sudo apt-get update
sudo apt-get install -y python3-venv python3-tk iw
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
printf '\nXong. Chay: ./run_master.sh\n'
