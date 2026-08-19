#!/usr/bin/env python3
"""
Stage 3: upload prepared images to The Frame over the network and set the
matte to none at upload time, so no per image fiddling in the TV interface.

Requires the NickWaterton fork, which is the one carrying 2024 LS03D support:
    pip install git+https://github.com/NickWaterton/samsung-tv-ws-api.git

First run only: the TV shows an allow prompt. Accept it with the remote.
A token is then written to config.TV_TOKEN_FILE and reused.

Usage:
    python push_to_frame.py --check      # connectivity and capability probe
    python push_to_frame.py              # upload everything not yet uploaded
    python push_to_frame.py --fix-mattes # force matte none on existing uploads
    python push_to_frame.py --prune      # delete remote items no longer local
"""

import argparse
import asyncio
import json
from pathlib import Path

from samsungtvws.async_art import SamsungTVAsyncArt

import config


def load_manifest():
    path = Path(config.UPLOAD_MANIFEST_FILE)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_manifest(manifest):
    path = Path(config.UPLOAD_MANIFEST_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


async def connect():
    tv = SamsungTVAsyncArt(host=config.TV_HOST,
                           port=config.TV_PORT,
                           token_file=config.TV_TOKEN_FILE,
                           name="frame-art-pipeline")
    await tv.start_listening()
    return tv


async def cmd_check(tv):
    print("art mode supported:", await tv.supported())
    print("art mode active:", await tv.get_artmode())
    print("api version:", await tv.get_api_version())
    print("current piece:", await tv.get_current())
    available = await tv.available("MY-C0002")
    print(f"user uploaded items on device: {len(available)}")


async def cmd_upload(tv, force_all=False):
    catalogue = json.loads(Path(config.METADATA_FILE).read_text())
    manifest = load_manifest()

    for record in catalogue:
        prepared = record.get("prepared_path")
        if not prepared or not Path(prepared).exists():
            continue
        if prepared in manifest and not force_all:
            continue

        data = Path(prepared).read_bytes()
        try:
            content_id = await tv.upload(
                data,
                file_type="JPEG",
                matte=config.MATTE,
                portrait_matte=config.PORTRAIT_MATTE,
            )
        except Exception as error:
            print(f"upload failed for {Path(prepared).name}: {error}")
            continue

        manifest[prepared] = {
            "content_id": content_id,
            "title": record.get("title"),
            "artist": record.get("artist"),
            "source": record.get("source"),
        }
        save_manifest(manifest)
        print(f"uploaded {content_id}  {record.get('title')}")
        await asyncio.sleep(1.0)

    print(f"\n{len(manifest)} items tracked in {config.UPLOAD_MANIFEST_FILE}")


async def cmd_fix_mattes(tv):
    """Re-assert matte none on everything already on the device."""
    manifest = load_manifest()
    for prepared, entry in manifest.items():
        content_id = entry["content_id"]
        try:
            await tv.change_matte(content_id, matte_id=config.MATTE)
            print(f"matte cleared on {content_id}")
        except Exception as error:
            print(f"matte change failed on {content_id}: {error}")
        await asyncio.sleep(0.5)


async def cmd_prune(tv):
    manifest = load_manifest()
    keep = {entry["content_id"] for entry in manifest.values()}
    remote = await tv.available("MY-C0002")
    stale = [item["content_id"] for item in remote
             if item.get("content_id") not in keep]
    if not stale:
        print("nothing to prune")
        return
    print(f"deleting {len(stale)} items")
    await tv.delete_list(stale)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--fix-mattes", action="store_true")
    parser.add_argument("--prune", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="re-upload items already in the manifest")
    args = parser.parse_args()

    tv = await connect()
    try:
        if args.check:
            await cmd_check(tv)
        elif args.fix_mattes:
            await cmd_fix_mattes(tv)
        elif args.prune:
            await cmd_prune(tv)
        else:
            await cmd_upload(tv, force_all=args.force)
            if config.PRUNE_REMOTE:
                await cmd_prune(tv)
    finally:
        await tv.close()


if __name__ == "__main__":
    asyncio.run(main())
