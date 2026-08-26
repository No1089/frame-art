#!/usr/bin/env python3
"""Web slideshow over the museum library, for iPads and browsers.

Serves the raw artwork rather than the TV renders. Those are 1920x1080 with
black bars and a caption burned in at a size chosen for a 32 inch panel seen
from across a room; a browser can lay the caption out itself and let the
artwork fill whatever shape the screen happens to be.

Derivatives are generated on first request and cached, so the first pass over
a new library is slow and every pass after it is not.
"""

import asyncio
import json
import sys
from pathlib import Path

from flask import Flask, abort, jsonify, send_file, send_from_directory
from PIL import Image, ImageOps

sys.path.insert(0, "/opt/frame-art")
import config  # noqa: E402
import frame_control  # noqa: E402

ROOT = Path("/opt/frame-art")
WEB_CACHE = ROOT / "library" / "web"
WEB_MAX_PX = 2048
WEB_QUALITY = 88

app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"))


def clean_artist(name):
    """Cleveland appends "(French, 1848-1894)" to every creator string."""
    cut = (name or "").find(" (")
    return ((name or "")[:cut] if cut > 0 else (name or "")).strip()


def load_catalogue():
    path = Path(config.METADATA_FILE)
    if not path.is_absolute():
        path = ROOT / path
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return []


def work_id(record):
    return f"{record.get('source')}-{record.get('source_id')}"


def index_by_id():
    return {work_id(r): r for r in load_catalogue()}


@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/works")
def api_works():
    out = []
    for record in load_catalogue():
        raw = record.get("raw_path")
        if not raw:
            continue
        if not (ROOT / raw if not Path(raw).is_absolute() else Path(raw)).exists():
            continue
        out.append({
            "id": work_id(record),
            "artist": clean_artist(record.get("artist")),
            "title": record.get("title") or "Untitled",
            "date": (record.get("date") or "").strip(),
            "medium": record.get("medium") or "",
            "credit": record.get("credit") or "",
            "blurb": record.get("blurb") or "",
            "source": record.get("source"),
            # Named for the same reason the burned in label names it: AIC's
            # description field is CC-BY and carries an attribution
            # requirement even though the painting itself is public domain.
            "museum": config.MUSEUM_NAMES.get(record.get("source"), ""),
            "selected_by": record.get("selected_by", ""),
        })
    return jsonify(out)


@app.route("/img/<work>")
def img(work):
    record = index_by_id().get(work)
    if not record:
        abort(404)
    raw = Path(record["raw_path"])
    if not raw.is_absolute():
        raw = ROOT / raw
    if not raw.exists():
        abort(404)

    WEB_CACHE.mkdir(parents=True, exist_ok=True)
    cached = WEB_CACHE / f"{work}.jpg"
    if not cached.exists() or cached.stat().st_mtime < raw.stat().st_mtime:
        with Image.open(raw) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((WEB_MAX_PX, WEB_MAX_PX), Image.LANCZOS)
            im.save(cached, "JPEG", quality=WEB_QUALITY, optimize=True)
    return send_file(cached, mimetype="image/jpeg", max_age=86400)


@app.route("/api/next", methods=["POST"])
def api_next():
    """Show the next piece on the Frame, on purpose.

    This forces the TV into art mode, which is right for a deliberate press
    and wrong for a timer: unattended it drops the HDMI signal and sleeps
    whatever is plugged in. The TV's own slideshow does the unattended
    rotation; this is the "change it now" button.

    Anything on the LAN can call this. That is the same exposure as the
    other services behind this Caddy, but it does mean the page can move
    the TV.
    """
    async def run():
        from push_to_frame import connect
        tv = await connect()
        try:
            return await frame_control.show_next(tv)
        finally:
            await tv.close()

    try:
        shown = asyncio.run(run())
    except SystemExit as error:
        # connect() raises SystemExit with a readable line when the TV is off.
        return jsonify({"ok": False, "error": str(error)}), 503
    except Exception as error:
        return jsonify({"ok": False,
                        "error": f"{type(error).__name__}: {error}"}), 502
    if not shown:
        return jsonify({"ok": False, "error": "nothing uploaded yet"}), 409
    return jsonify({"ok": True, **shown})


@app.route("/healthz")
def healthz():
    return jsonify({"works": len(load_catalogue())})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
