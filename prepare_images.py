#!/usr/bin/env python3
"""
Stage 2: condition every raw artwork to the exact panel geometry.

For the 32 inch Frame that is 1920x1080. Uploading larger images works but
the TV rescales with an unknown kernel, so matching exactly is predictable.

Usage:
    python prepare_images.py
    python prepare_images.py --fit blur --preview
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

import config

Image.MAX_IMAGE_PIXELS = None


def load_srgb(path):
    image = Image.open(path)
    image = ImageOps.exif_transpose(image)
    return image.convert("RGB")


def sample_border_colour(image, band_fraction=0.02):
    """Average the outer band of the artwork, then darken it."""
    if config.PAD_COLOUR_OVERRIDE:
        hex_value = config.PAD_COLOUR_OVERRIDE.lstrip("#")
        return tuple(int(hex_value[i:i + 2], 16) for i in (0, 2, 4))

    width, height = image.size
    band_w = max(1, int(width * band_fraction))
    band_h = max(1, int(height * band_fraction))

    regions = [
        image.crop((0, 0, width, band_h)),
        image.crop((0, height - band_h, width, height)),
        image.crop((0, 0, band_w, height)),
        image.crop((width - band_w, 0, width, height)),
    ]

    totals = [0.0, 0.0, 0.0]
    weight_total = 0
    for region in regions:
        weight = region.width * region.height
        channel_means = ImageStat.Stat(region).mean[:3]
        for index, value in enumerate(channel_means):
            totals[index] += value * weight
        weight_total += weight

    mean = [total / weight_total for total in totals]
    return tuple(max(0, min(255, int(channel * config.PAD_COLOUR_DARKEN)))
                 for channel in mean)


def fit_artwork(image, target_w, target_h, margin_fraction):
    """Scale the artwork to sit inside the panel with a margin, keeping ratio."""
    inset = int(target_h * margin_fraction)
    box_w = target_w - inset * 2
    box_h = target_h - inset * 2
    scale = min(box_w / image.width, box_h / image.height)
    new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    return image.resize(new_size, Image.LANCZOS)


def compose_pad(image, target_w, target_h):
    colour = sample_border_colour(image)
    canvas = Image.new("RGB", (target_w, target_h), colour)
    art = fit_artwork(image, target_w, target_h, config.ARTWORK_MARGIN_FRACTION)
    canvas.paste(art, ((target_w - art.width) // 2, (target_h - art.height) // 2))
    return canvas


def compose_blur(image, target_w, target_h):
    scale = max(target_w / image.width, target_h / image.height)
    backdrop = image.resize((int(image.width * scale) + 1,
                             int(image.height * scale) + 1), Image.LANCZOS)
    left = (backdrop.width - target_w) // 2
    top = (backdrop.height - target_h) // 2
    backdrop = backdrop.crop((left, top, left + target_w, top + target_h))
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(config.BLUR_RADIUS_PX))
    backdrop = ImageEnhance.Brightness(backdrop).enhance(config.BLUR_BRIGHTNESS)

    art = fit_artwork(image, target_w, target_h, config.ARTWORK_MARGIN_FRACTION)
    backdrop.paste(art, ((target_w - art.width) // 2,
                         (target_h - art.height) // 2))
    return backdrop


def compose_crop(image, target_w, target_h):
    return ImageOps.fit(image, (target_w, target_h), Image.LANCZOS,
                        centering=(0.5, 0.4))


COMPOSERS = {"pad": compose_pad, "blur": compose_blur, "crop": compose_crop}


def apply_tone(image):
    if config.SATURATION_ADJUST != 1.0:
        image = ImageEnhance.Color(image).enhance(config.SATURATION_ADJUST)
    if config.GAMMA_ADJUST != 1.0:
        inverse = 1.0 / config.GAMMA_ADJUST
        table = [min(255, int((value / 255.0) ** inverse * 255)) for value in range(256)]
        image = image.point(table * 3)
    return image


def save(image, path):
    params = {"quality": config.JPEG_QUALITY, "subsampling": 0, "optimize": True}
    if not config.STRIP_METADATA:
        params["exif"] = image.info.get("exif", b"")
    image.save(path, config.OUTPUT_FORMAT, **params)

    quality = config.JPEG_QUALITY
    while path.stat().st_size > config.MAX_UPLOAD_BYTES and quality > 60:
        quality -= 6
        image.save(path, config.OUTPUT_FORMAT, quality=quality, optimize=True)
    return path.stat().st_size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", choices=list(COMPOSERS), default=config.FIT_MODE)
    parser.add_argument("--force", action="store_true",
                        help="reprocess files that already exist")
    args = parser.parse_args()

    catalogue_path = Path(config.METADATA_FILE)
    if not catalogue_path.exists():
        raise SystemExit(f"{catalogue_path} not found. Run fetch_art.py first.")
    catalogue = json.loads(catalogue_path.read_text())

    prepared_dir = Path(config.PREPARED_DIR)
    prepared_dir.mkdir(parents=True, exist_ok=True)
    composer = COMPOSERS[args.fit]

    processed = 0
    skipped = 0
    for record in catalogue:
        raw_path = Path(record.get("raw_path", ""))
        if not raw_path.exists():
            continue

        out_path = prepared_dir / (raw_path.stem + ".jpg")
        if out_path.exists() and not args.force:
            record["prepared_path"] = str(out_path)
            continue

        try:
            image = load_srgb(raw_path)
        except OSError as error:
            print(f"skip unreadable {raw_path.name}: {error}")
            skipped += 1
            continue

        if max(image.size) < config.MIN_SOURCE_LONG_EDGE_PX:
            print(f"skip low res {raw_path.name} at {image.size[0]}x{image.size[1]}")
            skipped += 1
            continue

        canvas = apply_tone(composer(image, config.TARGET_WIDTH_PX,
                                     config.TARGET_HEIGHT_PX))
        size_bytes = save(canvas, out_path)
        record["prepared_path"] = str(out_path)
        record["prepared_bytes"] = size_bytes
        processed += 1
        print(f"{out_path.name}  {size_bytes // 1024} KB")

    catalogue_path.write_text(json.dumps(catalogue, indent=2, ensure_ascii=False))
    print(f"\nprepared {processed}, skipped {skipped}, "
          f"target {config.TARGET_WIDTH_PX}x{config.TARGET_HEIGHT_PX}, fit {args.fit}")


if __name__ == "__main__":
    main()
