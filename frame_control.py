#!/usr/bin/env python3
"""Choosing and showing one work, shared by the CLI and the web gallery.

The TV cannot rotate its own art here. Its slideshow settings live behind a
Samsung account, the TV is deliberately blocked from the internet, and so
every set_slideshow_status write is acknowledged and then silently
discarded. Driving it from outside is the only route, not a workaround.

That means select_image with show=True, which forces art mode. Fired
blindly it drops the HDMI signal and sleeps whatever is plugged into the
Frame, so the timer checks art mode first and acts only when the TV is
already showing art, where there is nothing to switch away from.

State lives in one small JSON file so the check can be frequent without the
picture changing that often, and so entering art mode can change the
picture immediately rather than after a whole interval of Art Store.
"""

import json
import random
import time
from pathlib import Path

import config

USER_CATEGORY = "MY-C0002"
STATE_FILE = "./library/rotate-state.json"


def load_manifest():
    try:
        return json.loads(Path(config.UPLOAD_MANIFEST_FILE).read_text())
    except (OSError, ValueError):
        return {}


def _state():
    try:
        return json.loads(Path(STATE_FILE).read_text())
    except (OSError, ValueError):
        return {}


def _save_state(**changes):
    state = _state()
    state.update(changes)
    try:
        path = Path(STATE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2))
    except OSError:
        pass


def pick(manifest=None):
    """A work that is not the one already up, so consecutive changes differ."""
    manifest = manifest if manifest is not None else load_manifest()
    entries = [(e["content_id"], e) for e in manifest.values()
               if e.get("content_id")]
    if not entries:
        return None, {}
    last = _state().get("last_content_id")
    pool = [pair for pair in entries if pair[0] != last] or entries
    return random.choice(pool)


def due(min_interval_minutes):
    """Has enough time passed since the picture last changed?"""
    last = _state().get("last_rotate_at", 0)
    return (time.time() - last) >= min_interval_minutes * 60


def entering_artmode(artmode_on):
    """True on the transition into art mode, so we can act at once.

    Without this, pressing power shows whatever the TV had current, which is
    an Art Store piece, until the interval happens to come round.
    """
    was_on = _state().get("artmode_on", False)
    _save_state(artmode_on=bool(artmode_on))
    return bool(artmode_on) and not was_on


async def show(tv, content_id):
    await tv.select_image(content_id, category=USER_CATEGORY, show=True)
    _save_state(last_content_id=content_id, last_rotate_at=time.time())


async def show_next(tv):
    """Pick one and display it. Returns the manifest entry, or None."""
    content_id, entry = pick()
    if not content_id:
        return None
    await show(tv, content_id)
    return {"content_id": content_id,
            "artist": (entry.get("artist") or "").split(" (")[0],
            "title": entry.get("title")}
