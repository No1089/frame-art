#!/usr/bin/env python3
"""Publish the library as stills on the media share, for the second TV.

That TV has no art mode, so its Apple TV shows the collection as a
screensaver instead. The screensaver reads from an iCloud album, and these
files are the source: browse the Media SMB share from an iPad, add them to a
Shared Album, and point the Apple TV at it.

Mirrors rather than accumulates. A work dropped from the catalogue when the
monthly theme turns over has its still deleted, so the folder is always the
current library rather than everything ever fetched.

The exported files are the same 1920x1080 renders the Frame gets, caption
and all, so both TVs show the same thing. If the screensaver's pan crops the
caption, the alternative is the web derivatives in library/web, which are
full bleed artwork with no caption.

Usage:
    python export_stills.py
    python export_stills.py --dest /some/other/place
"""

import argparse
import json
import re
import shutil
from pathlib import Path

import config

DEFAULT_DEST = config.STILLS_DIR
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def load_catalogue():
    """Read the catalogue, or say plainly what to run first.

    A stack trace here is a poor welcome: the only thing that has gone wrong
    is that the pipeline has not been run yet.
    """
    path = Path(config.METADATA_FILE)
    if not path.exists():
        raise SystemExit(f"{path} not found. Run fetch_art.py first.")
    return json.loads(path.read_text())


def readable_name(record, taken):
    """A name worth reading in the Files app, not the internal slug."""
    artist = (record.get("artist") or "Unknown").split(" (")[0].strip()
    title = (record.get("title") or "Untitled").strip()
    stem = _UNSAFE.sub("", f"{artist} - {title}").strip(" .")[:120] or "Untitled"
    name = f"{stem}.jpg"
    if name in taken:
        # Two museums can hold works of the same name by the same painter.
        name = f"{stem} [{record.get('source')}-{record.get('source_id')}].jpg"
    return name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=DEFAULT_DEST)
    args = parser.parse_args()

    dest = Path(args.dest)
    if not dest.parent.exists():
        # Optional step: a clone with no media share should not fail here.
        print(f"{dest.parent} is not there, skipping the stills export")
        return
    dest.mkdir(parents=True, exist_ok=True)

    catalogue = load_catalogue()
    wanted = {}
    for record in catalogue:
        prepared = record.get("prepared_path")
        if not prepared or not Path(prepared).exists():
            continue
        wanted[readable_name(record, wanted)] = Path(prepared)

    copied = skipped = 0
    for name, source in wanted.items():
        target = dest / name
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime \
                and target.stat().st_size == source.stat().st_size:
            skipped += 1
            continue
        shutil.copy2(source, target)
        copied += 1

    removed = 0
    for existing in dest.glob("*.jpg"):
        if existing.name not in wanted:
            existing.unlink()
            removed += 1

    print(f"stills in {dest}: {len(wanted)} works "
          f"({copied} written, {skipped} unchanged, {removed} removed)")


if __name__ == "__main__":
    main()
