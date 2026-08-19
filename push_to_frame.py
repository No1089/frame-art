#!/usr/bin/env python3
"""
Stage 3: upload prepared images to The Frame over the network and set the
matte to none at upload time, so no per image fiddling in the TV interface.

Requires the NickWaterton fork, which is the one carrying LS03C and LS03D
support:
    pip install git+https://github.com/NickWaterton/samsung-tv-ws-api.git

First run only: the TV shows an allow prompt. Accept it with the remote.
A token is then written to config.TV_TOKEN_FILE and reused.

Usage:
    python push_to_frame.py --check             # connectivity and capability probe
    python push_to_frame.py                     # upload everything not yet uploaded
    python push_to_frame.py --limit 1 --select  # upload one, put it on the wall
    python push_to_frame.py --fix-mattes        # force matte none on existing uploads
    python push_to_frame.py --prune             # delete remote items no longer local
"""

import argparse
import asyncio
import json
from pathlib import Path

from samsungtvws.async_art import SamsungTVAsyncArt

import config

# The TV's own category id for user uploaded pictures.
# MY-C0004 is favourites, MY-C0008 is the store.
USER_CATEGORY = "MY-C0002"

# The fork's upload() waits for an image_added event and returns None if it
# does not arrive in time. Its ten second default is tight for a megabyte
# over wifi, and a None return here is worse than a slow one.
UPLOAD_TIMEOUT_S = 30


def load_manifest():
    path = Path(config.UPLOAD_MANIFEST_FILE)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_manifest(manifest):
    path = Path(config.UPLOAD_MANIFEST_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


OFFLINE_HINT = (
    "The Frame leaves the network completely when it is powered down, rather "
    "than staying reachable the way standby and art mode do, and wake on LAN "
    "cannot rouse it because the wifi radio is off as well. Switch the TV on "
    "and run this again."
)


async def connect():
    # Constructing SamsungTVAsyncArt already performs a REST call, so an
    # unreachable TV raises here rather than at start_listening. Both are
    # turned into one actionable line: a weekly timer firing at a switched
    # off TV should not be sixty lines of urllib3 traceback in the journal.
    try:
        tv = SamsungTVAsyncArt(host=config.TV_HOST,
                               port=config.TV_PORT,
                               token_file=config.TV_TOKEN_FILE,
                               name="frame-art-pipeline")
        await tv.start_listening()
    except Exception as error:
        raise SystemExit(
            f"cannot reach the TV at {config.TV_HOST}:{config.TV_PORT}: "
            f"{type(error).__name__}: {error}\n{OFFLINE_HINT}")
    return tv


async def remote_content_ids(tv):
    """Content ids currently sitting in the TV's user picture category."""
    try:
        items = await tv.available(USER_CATEGORY)
    except Exception as error:
        print(f"could not list remote content: {error}")
        return set()
    return {item.get("content_id") for item in items if item.get("content_id")}


async def cmd_check(tv):
    async def probe(label, method):
        try:
            print(f"{label}: {await method()}")
        except Exception as error:
            print(f"{label}: FAILED {error!r}")

    await probe("art mode supported", tv.supported)
    await probe("tv powered on", tv.on)
    await probe("art mode active", tv.get_artmode)
    await probe("api version", tv.get_api_version)
    await probe("current piece", tv.get_current)

    # config.MATTE is only meaningful if this firmware spells it that way.
    # Older notes claim "no_matte" on some models, so confirm rather than assume.
    try:
        mattes = await tv.get_matte_list()
        names = sorted(str(m.get("matte_type", m) if isinstance(m, dict) else m)
                       for m in mattes)
        print(f"matte types ({len(names)}): {', '.join(names)}")
        verdict = ("OK" if config.MATTE in names
                   else "NOT OFFERED, check the spelling against the list above")
        print(f"config.MATTE {config.MATTE!r}: {verdict}")
    except Exception as error:
        print(f"matte list: FAILED {error!r}")

    remote = await remote_content_ids(tv)
    print(f"user uploaded items on device: {len(remote)}")


async def cmd_upload(tv, force_all=False, limit=None, select_first=False):
    catalogue = json.loads(Path(config.METADATA_FILE).read_text())
    manifest = load_manifest()

    pending = [record for record in catalogue
               if record.get("prepared_path")
               and Path(record["prepared_path"]).exists()
               and (force_all or record["prepared_path"] not in manifest)]
    if limit is not None:
        pending = pending[:limit]
    if not pending:
        print("nothing to upload")
        return
    print(f"{len(pending)} to upload")

    known = await remote_content_ids(tv)
    first_uploaded = None

    for record in pending:
        prepared = record["prepared_path"]
        data = Path(prepared).read_bytes()
        try:
            content_id = await tv.upload(
                data,
                file_type="JPEG",
                matte=config.MATTE,
                portrait_matte=config.PORTRAIT_MATTE,
                timeout=UPLOAD_TIMEOUT_S,
            )
        except Exception as error:
            print(f"upload failed for {Path(prepared).name}: {error}")
            continue

        if not content_id:
            # The image has usually landed anyway and only the acknowledgement
            # was late. Recover the id by diffing the device listing, because
            # a null id in the manifest silently breaks --fix-mattes and
            # --prune for this item forever after.
            appeared = await remote_content_ids(tv) - known
            content_id = appeared.pop() if len(appeared) == 1 else None
            if not content_id:
                print(f"no content id for {Path(prepared).name}, not recording it")
                continue
            print(f"  recovered content id {content_id} by diffing the device")

        known.add(content_id)
        manifest[prepared] = {
            "content_id": content_id,
            "title": record.get("title"),
            "artist": record.get("artist"),
            "source": record.get("source"),
        }
        save_manifest(manifest)
        print(f"uploaded {content_id}  {record.get('title')}")
        first_uploaded = first_uploaded or content_id
        await asyncio.sleep(1.0)

    if select_first and first_uploaded:
        try:
            await tv.select_image(first_uploaded, show=True)
            print(f"selected {first_uploaded} for display")
        except Exception as error:
            print(f"select failed for {first_uploaded}: {error}")

    print(f"\n{len(manifest)} items tracked in {config.UPLOAD_MANIFEST_FILE}")


async def cmd_fix_mattes(tv):
    """Re-assert matte none on everything already on the device."""
    manifest = load_manifest()
    for prepared, entry in manifest.items():
        content_id = entry.get("content_id")
        if not content_id:
            print(f"no content id recorded for {Path(prepared).name}, skipping")
            continue
        try:
            await tv.change_matte(content_id, matte_id=config.MATTE)
            print(f"matte cleared on {content_id}")
        except Exception as error:
            print(f"matte change failed on {content_id}: {error}")
        await asyncio.sleep(0.5)


async def cmd_prune(tv):
    manifest = load_manifest()
    if not manifest:
        # Every user picture on the device would look stale, including any
        # put there by hand. Refuse rather than empty the gallery.
        print("manifest is empty, refusing to prune")
        return
    keep = {entry.get("content_id") for entry in manifest.values()}
    remote = await tv.available(USER_CATEGORY)
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
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many uploads")
    parser.add_argument("--select", action="store_true",
                        help="display the first newly uploaded piece")
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
            await cmd_upload(tv, force_all=args.force, limit=args.limit,
                             select_first=args.select)
            if config.PRUNE_REMOTE:
                await cmd_prune(tv)
    finally:
        await tv.close()


if __name__ == "__main__":
    asyncio.run(main())
