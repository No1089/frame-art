#!/usr/bin/env bash
# Chains all three stages. Exits non-zero on the first failure so a systemd
# timer or cron entry surfaces the problem instead of silently continuing.
set -euo pipefail

cd "$(dirname "$0")"
source .venv/bin/activate

echo "== fetch =="
python fetch_art.py

echo "== prepare =="
python prepare_images.py

echo "== push =="
python push_to_frame.py
