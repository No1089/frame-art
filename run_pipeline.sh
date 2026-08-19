#!/usr/bin/env bash
# Chains all three stages. Exits non-zero on the first failure so a systemd
# timer or cron entry surfaces the problem instead of silently continuing.
set -euo pipefail

cd "$(dirname "$0")"

# No venv activation: call the interpreter directly so this behaves the same
# under systemd, which has no shell profile.
PY=./.venv/bin/python

echo "== fetch =="
# No arguments: the core roster plus whichever theme this month calls for.
$PY -u fetch_art.py

echo "== prepare =="
$PY -u prepare_images.py

echo "== push =="
# PRUNE_REMOTE is on, so this also retires last month's theme from the TV.
$PY -u push_to_frame.py
