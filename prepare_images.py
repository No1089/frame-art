#!/usr/bin/env python3
"""
Stage 2: condition every raw artwork to the exact panel geometry.

For the 32 inch Frame that is 1920x1080. Uploading larger images works but
the TV rescales with an unknown kernel, so matching exactly is predictable.

Usage:
    python prepare_images.py
    python prepare_images.py --fit blur --force
"""

import argparse
import json
import re
import time
from pathlib import Path

from PIL import (Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont,
                 ImageOps, ImageStat)

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


# ---------------------------------------------------------------------------
# Museum label
# ---------------------------------------------------------------------------

_FONT_CACHE = {}


def load_font(candidates, size):
    """First candidate that exists and loads. Pillow's built-in as a floor."""
    key = (tuple(candidates), size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    for path in candidates:
        try:
            font = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(size=size)
    _FONT_CACHE[key] = font
    return font


def label_strip_height():
    if not config.LABEL_ENABLED or config.LABEL_POSITION != "bottom":
        return 0
    return int(config.TARGET_HEIGHT_PX * config.LABEL_HEIGHT_FRACTION)


def clean_artist(name):
    """Drop the trailing credit parenthetical Cleveland attaches to creators.

    "Gustave Caillebotte (French, 1848-1894)" becomes "Gustave Caillebotte".
    """
    if not config.LABEL_STRIP_ARTIST_PARENTHETICAL:
        return name
    cut = name.find(" (")
    return (name[:cut] if cut > 0 else name).strip()


def fit_text(text, font, max_width):
    """Truncate to fit on one line, with an ellipsis."""
    if font.getlength(text) <= max_width:
        return text
    while text and font.getlength(text + "\u2026") > max_width:
        text = text[:-1]
    return text.rstrip(" ,;:(") + "\u2026"


def wrap_text(text, font, max_width):
    """Greedy word wrap measured against the actual font, not a char count."""
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and font.getlength(candidate) > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def row_height(font):
    return int(font.size * config.LABEL_BLURB_LINE_SPACING)


def measure_rows(rows):
    total = 0
    for text, font, extra in rows:
        total += extra if text is None else row_height(font)
    return total


def draw_rows(canvas, rows, left, top, max_height, centred_width=None):
    """Draw rows top down, dropping any that would overflow the height."""
    draw = ImageDraw.Draw(canvas)
    y = top
    for text, font, extra in rows:
        if text is None:
            y += extra
            continue
        step = row_height(font)
        if y - top + step > max_height:
            break
        if centred_width is None:
            draw.text((left, y), text, font=font, fill=extra, anchor="la")
        else:
            draw.text((left + centred_width // 2, y), text, font=font,
                      fill=extra, anchor="ma")
        y += step
    return y


def _fonts():
    return {
        "artist": load_font(config.LABEL_FONT_CANDIDATES,
                            config.LABEL_ARTIST_SIZE_PX),
        "detail": load_font(config.LABEL_FONT_ITALIC_CANDIDATES
                            or config.LABEL_FONT_CANDIDATES,
                            config.LABEL_DETAIL_SIZE_PX),
        "tomb": load_font(config.LABEL_FONT_CANDIDATES,
                          config.LABEL_TOMBSTONE_SIZE_PX),
        "blurb": load_font(config.LABEL_FONT_CANDIDATES,
                           config.LABEL_BLURB_SIZE_PX),
    }


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def blurb_lines(blurb, font, width, max_height):
    """As many whole sentences as fit the space.

    Cutting a wall label mid clause reads as a bug rather than as an edited
    caption, so prefer to stop at a full stop. Only if not even the first
    sentence fits does this fall back to a hard cut with an ellipsis.
    """
    per_line = row_height(font)
    if max_height < per_line:
        return []
    max_lines = int(max_height // per_line)

    kept = ""
    for sentence in _SENTENCE_RE.split(blurb):
        candidate = f"{kept} {sentence}".strip()
        if len(wrap_text(candidate, font, width)) > max_lines:
            break
        kept = candidate
    if kept:
        return wrap_text(kept, font, width)

    lines = wrap_text(blurb, font, width)[:max_lines]
    if lines:
        lines[-1] = lines[-1].rstrip(" ,;:") + "\u2026"
    return lines


def build_label(record, width, available_height, allow_blurb=True):
    """Caption rows in gallery order, sized to the space actually available."""
    fonts = _fonts()
    rows = []

    artist = clean_artist(record.get("artist") or "")
    for line in wrap_text(artist, fonts["artist"], width):
        rows.append((line, fonts["artist"], config.LABEL_ARTIST_COLOUR))

    title = record.get("title") or ""
    date = (record.get("date") or "").strip()
    detail = f"{title}, {date}" if date else title
    for line in wrap_text(detail, fonts["detail"], width):
        rows.append((line, fonts["detail"], config.LABEL_DETAIL_COLOUR))

    tombstone = ", ".join(part for part in
                          (record.get("medium"), record.get("credit")) if part)
    # Cleveland writes "oil on fabric" where Chicago writes "Oil on canvas".
    if tombstone:
        tombstone = tombstone[0].upper() + tombstone[1:]
        rows.append((None, None, config.LABEL_PARAGRAPH_GAP_PX))
        for line in wrap_text(tombstone, fonts["tomb"], width):
            rows.append((line, fonts["tomb"], config.LABEL_TOMBSTONE_COLOUR))

    blurb = (record.get("blurb") or "").strip()
    if allow_blurb and blurb:
        spare = (available_height - measure_rows(rows)
                 - config.LABEL_PARAGRAPH_GAP_PX)
        # Two lines is the floor worth showing; one orphan line looks accidental.
        if spare >= row_height(fonts["blurb"]) * 2:
            lines = blurb_lines(blurb, fonts["blurb"], width, spare)
            if len(lines) >= 2:
                rows.append((None, None, config.LABEL_PARAGRAPH_GAP_PX))
                for line in lines:
                    rows.append((line, fonts["blurb"], config.LABEL_BLURB_COLOUR))
    return rows


def compose_side(image, record, fit):
    """Artwork left, caption in the column it leaves behind."""
    panel_w, panel_h = config.TARGET_WIDTH_PX, config.TARGET_HEIGHT_PX
    margin = config.LABEL_EDGE_MARGIN_PX
    gap = config.LABEL_GAP_PX

    art_box_w = panel_w - margin * 2 - gap - config.LABEL_MIN_COLUMN_PX
    art_box_h = panel_h - margin * 2
    scale = min(art_box_w / image.width, art_box_h / image.height)
    art = image.resize((max(1, int(image.width * scale)),
                        max(1, int(image.height * scale))), Image.LANCZOS)

    # Whatever the artwork did not use belongs to the caption, clamped to a
    # readable measure. A portrait leaves far more than the minimum, which is
    # what earns it a blurb; a wide landscape leaves exactly the minimum.
    spare = panel_w - margin * 2 - gap - art.width
    column_width = max(config.LABEL_MIN_COLUMN_PX,
                       min(spare, config.LABEL_MAX_COLUMN_PX))
    with_blurb = column_width >= config.LABEL_BLURB_MIN_COLUMN_PX

    # Centre artwork and caption as one composition, so capping the column
    # leaves balanced margins instead of a void on the right.
    group_left = (panel_w - (art.width + gap + column_width)) // 2
    canvas = Image.new("RGB", (panel_w, panel_h), sample_border_colour(image))
    art_x, art_y = group_left, (panel_h - art.height) // 2
    canvas.paste(art, (art_x, art_y))
    column_left = art_x + art.width + gap

    rows = build_label(record, column_width, art_box_h, allow_blurb=with_blurb)
    block = min(measure_rows(rows), art_box_h)
    draw_rows(canvas, rows, column_left, (panel_h - block) // 2, art_box_h)
    return canvas


def compose_landscape(image, record):
    """Artwork full width, caption beneath its right hand end."""
    panel_w, panel_h = config.TARGET_WIDTH_PX, config.TARGET_HEIGHT_PX
    margin = config.LABEL_EDGE_MARGIN_PX
    gap = config.LABEL_CAPTION_GAP_PX

    art_box_w = panel_w - margin * 2
    art_box_h = panel_h - margin * 2 - gap - config.LABEL_MIN_STRIP_PX
    scale = min(art_box_w / image.width, art_box_h / image.height)
    art = image.resize((max(1, int(image.width * scale)),
                        max(1, int(image.height * scale))), Image.LANCZOS)

    # A very wide painting is width limited and leaves height to spare, which
    # is what earns it a blurb. A 4:3 one is height limited and does not.
    strip = panel_h - margin * 2 - gap - art.height
    block_width = min(art.width, config.LABEL_MAX_COLUMN_PX)
    rows = build_label(record, block_width, strip,
                       allow_blurb=strip >= config.LABEL_BLURB_MIN_STRIP_PX)
    block = min(measure_rows(rows), strip)

    canvas = Image.new("RGB", (panel_w, panel_h), sample_border_colour(image))
    top = (panel_h - (art.height + gap + block)) // 2
    art_x = (panel_w - art.width) // 2
    canvas.paste(art, (art_x, top))
    draw_rows(canvas, rows, art_x + art.width - block_width,
              top + art.height + gap, strip)
    return canvas


def compose(image, record, fit):
    if config.LABEL_ENABLED:
        position = config.LABEL_POSITION
        if position == "auto":
            position = "bottom-right" if image.width > image.height else "side"
        if position == "side":
            return compose_side(image, record, fit)
        if position == "bottom-right":
            return compose_landscape(image, record)

    strip = label_strip_height()
    art_canvas = COMPOSERS[fit](image, config.TARGET_WIDTH_PX,
                                config.TARGET_HEIGHT_PX - strip)
    if not strip:
        return art_canvas

    canvas = Image.new("RGB", (config.TARGET_WIDTH_PX, config.TARGET_HEIGHT_PX),
                       sample_border_colour(image))
    canvas.paste(art_canvas, (0, 0))
    width = config.TARGET_WIDTH_PX - config.LABEL_EDGE_MARGIN_PX * 2
    rows = build_label(record, width, strip, allow_blurb=False)
    block = measure_rows(rows)
    draw_rows(canvas, rows, config.LABEL_EDGE_MARGIN_PX,
              config.TARGET_HEIGHT_PX - strip + (strip - block) // 2,
              strip, centred_width=width)
    return canvas


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


def write_json_with_retry(path, payload, attempts=5):
    """Write the catalogue, retrying a transient EPERM.

    macOS intermittently refuses the open with EPERM mid-batch, and losing
    the catalogue write means every prepared_path computed in this run is
    thrown away even though the JPEGs are on disk.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    for attempt in range(attempts):
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(text)
            tmp.replace(path)
            return
        except OSError as error:
            if attempt == attempts - 1:
                raise
            print(f"  catalogue write failed ({error.strerror}), retrying")
            time.sleep(1.5 * (attempt + 1))


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
    processed = 0
    skipped = 0
    failed = 0
    for record in catalogue:
        raw_path = Path(record.get("raw_path", ""))
        if not raw_path.exists():
            continue

        out_path = prepared_dir / (raw_path.stem + ".jpg")
        if out_path.exists() and not args.force:
            record["prepared_path"] = str(out_path)
            continue

        image = None
        for attempt in range(3):
            try:
                image = load_srgb(raw_path)
                break
            except OSError as error:
                last_error = error
                time.sleep(0.75 * (attempt + 1))
        if image is None:
            print(f"skip unreadable {raw_path.name}: {last_error}")
            skipped += 1
            continue

        if max(image.size) < config.MIN_SOURCE_LONG_EDGE_PX:
            print(f"skip low res {raw_path.name} at {image.size[0]}x{image.size[1]}")
            skipped += 1
            continue

        try:
            canvas = apply_tone(compose(image, record, args.fit))
            size_bytes = save(canvas, out_path)
        except OSError as error:
            # One flaky write should not abandon the other forty three. This
            # has been seen as a transient EPERM on macOS mid-batch.
            print(f"failed to write {out_path.name}: {error}")
            failed += 1
            continue
        record["prepared_path"] = str(out_path)
        record["prepared_bytes"] = size_bytes
        processed += 1
        print(f"{out_path.name}  {size_bytes // 1024} KB")

    write_json_with_retry(catalogue_path, catalogue)
    print(f"\nprepared {processed}, skipped {skipped}, failed {failed}, "
          f"target {config.TARGET_WIDTH_PX}x{config.TARGET_HEIGHT_PX}, fit {args.fit}")
    if failed:
        raise SystemExit(f"{failed} image(s) could not be written")


if __name__ == "__main__":
    main()
