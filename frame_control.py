#!/usr/bin/env python3
"""Choosing and showing one work, shared by the CLI and the web gallery.

Kept in one place because both need it and they must not drift: the web
button and `push_to_frame.py --rotate` are the same action triggered two
ways.

Note this uses show=True, which forces the TV into art mode. That is right
for a deliberate press of a button and wrong for a timer: on a timer it
drops the HDMI signal and sleeps whatever is plugged into the Frame, which
is why the rotation timer was removed and the TV's own slideshow does the
unattended rotation instead.
"""

import json
import random
from pathlib import Path

import config

USER_CATEGORY = "MY-C0002"
LAST_SHOWN_FILE = "./library/last-shown.txt"


def load_manifest():
    path = Path(config.UPLOAD_MANIFEST_FILE)
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _last_shown():
    try:
        return Path(LAST_SHOWN_FILE).read_text().strip()
    except OSError:
        return ""


def _remember(content_id):
    try:
        path = Path(LAST_SHOWN_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content_id)
    except OSError:
        pass


def pick(manifest=None):
    """A work that is not the one already up, so consecutive presses differ."""
    manifest = manifest if manifest is not None else load_manifest()
    entries = [(e["content_id"], e) for e in manifest.values()
               if e.get("content_id")]
    if not entries:
        return None, {}
    last = _last_shown()
    pool = [pair for pair in entries if pair[0] != last] or entries
    return random.choice(pool)


async def show(tv, content_id):
    await tv.select_image(content_id, category=USER_CATEGORY, show=True)
    _remember(content_id)


async def show_next(tv):
    """Pick one and display it. Returns the manifest entry, or None."""
    content_id, entry = pick()
    if not content_id:
        return None
    await show(tv, content_id)
    return {"content_id": content_id,
            "artist": (entry.get("artist") or "").split(" (")[0],
            "title": entry.get("title")}
