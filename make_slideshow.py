#!/usr/bin/env python3
"""Render the library as a video file for TVs with no art mode.

Deliberately a file rather than a live stream. A live HLS or RTSP feed needs
an encoder running continuously, and this host has a history of hard locking
under hardware accelerated video, so a pre-rendered file that every client
direct plays is both cheaper and safer.

Encoded as H.264 High in yuv420p with a silent AAC track, which is what an
Apple TV plays natively through Swiftfin or Infuse. That matters: if Jellyfin
has to transcode, the work lands back on the very decode path worth avoiding.
The prepared JPEGs are already 1920x1080 with the caption burned in, so this
is a straight concatenation with no rescaling.

Usage:
    python make_slideshow.py                 # default hold, shuffled
    python make_slideshow.py --hold 30
    python make_slideshow.py --out /mnt/media/Gallery/Gallery.mp4
"""

import argparse
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import config

DEFAULT_OUT = "/mnt/media/Gallery/Frame Art Gallery.mp4"


def prepared_images():
    catalogue = json.loads(Path(config.METADATA_FILE).read_text())
    paths = []
    for record in catalogue:
        prepared = record.get("prepared_path")
        if not prepared:
            continue
        path = Path(prepared)
        if path.exists():
            paths.append(path.resolve())
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold", type=float, default=20.0,
                        help="seconds each work stays on screen")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--no-shuffle", action="store_true")
    args = parser.parse_args()

    images = prepared_images()
    if not images:
        raise SystemExit("no prepared images; run prepare_images.py first")
    if not args.no_shuffle:
        random.shuffle(images)

    minutes = len(images) * args.hold / 60
    print(f"{len(images)} works at {args.hold:g}s each -> {minutes:.0f} minutes")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as manifest:
        for path in images:
            # The concat demuxer takes single quoted paths; escape any quote.
            safe = str(path).replace("'", r"'\''")
            manifest.write(f"file '{safe}'\nduration {args.hold}\n")
        # The demuxer ignores the final duration unless the last file repeats.
        safe = str(images[-1]).replace("'", r"'\''")
        manifest.write(f"file '{safe}'\n")
        list_path = manifest.name

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_suffix(".partial.mp4")

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats",
        "-f", "concat", "-safe", "0", "-i", list_path,
        # A silent track: some clients are unhappy with video-only files.
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-tune", "stillimage", "-preset", "veryfast", "-crf", str(args.crf),
        # Two second keyframe interval so seeking is not miserable.
        "-r", "24", "-g", "48",
        "-c:a", "aac", "-b:a", "64k", "-shortest",
        "-movflags", "+faststart",
        str(tmp_out),
    ]
    print("encoding...")
    result = subprocess.run(cmd)
    Path(list_path).unlink(missing_ok=True)
    if result.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        raise SystemExit(f"ffmpeg failed with {result.returncode}")

    # Swap in atomically so Jellyfin never indexes a half written file.
    tmp_out.replace(out)
    size_mb = out.stat().st_size / 1048576
    print(f"wrote {out} ({size_mb:.0f} MB)")


if __name__ == "__main__":
    main()
