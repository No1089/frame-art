#!/usr/bin/env python3
"""Web slideshow over the museum library, for iPads and browsers.

Serves the raw artwork rather than the TV renders. Those are 1920x1080 with
black bars and a caption burned in at a size chosen for a 32 inch panel seen
from across a room; a browser can lay the caption out itself and let the
artwork fill whatever shape the screen happens to be.

Derivatives are generated on first request and cached, so the first pass over
a new library is slow and every pass after it is not.
"""

import json
import sys
from pathlib import Path

from flask import Flask, abort, jsonify, send_file, send_from_directory
from PIL import Image, ImageOps

sys.path.insert(0, "/opt/frame-art")
import config  # noqa: E402

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


@app.route("/healthz")
def healthz():
    return jsonify({"works": len(load_catalogue())})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
