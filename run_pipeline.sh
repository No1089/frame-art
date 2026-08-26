#!/usr/bin/env bash
# Chains every stage. Exits non-zero on the first failure so a systemd timer
# or cron entry surfaces the problem instead of silently continuing.
set -euo pipefail

cd "$(dirname "$0")"

# Call the interpreter directly rather than activating the venv, so this
# behaves the same under systemd, which has no shell profile.
PY=./.venv/bin/python

echo "== fetch =="
# No arguments: the core roster plus whichever theme this month calls for.
$PY -u fetch_art.py

echo "== prepare =="
$PY -u prepare_images.py

echo "== push =="
# PRUNE_REMOTE is on, so this also retires last month's theme from the TV.
$PY -u push_to_frame.py

# Both of the following are optional and skip themselves when the media
# share is not mounted, so this is safe on a machine that has neither.
echo "== stills =="
$PY -u export_stills.py

echo "== render =="
$PY -u make_slideshow.py
