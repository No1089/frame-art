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
import random
from pathlib import Path

from samsungtvws import SamsungTVWS
from samsungtvws.async_art import SamsungTVAsyncArt

import config
import frame_control

# The TV's own category id for user uploaded pictures.
# MY-C0004 is favourites, MY-C0008 is the store.
USER_CATEGORY = "MY-C0002"

# The fork's upload() waits for an image_added event and returns None if it
# does not arrive in time. Its ten second default is tight for a megabyte
# over wifi, and a None return here is worse than a slow one.
UPLOAD_TIMEOUT_S = 30

# How long to leave the pairing prompt up waiting for someone to accept it.
PAIRING_TIMEOUT_S = 90


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

# The TV emits this when nobody approves the connection in time. It means the
# opposite of unreachable: the TV answered, it is simply waiting on a human.
PAIRING_HINT = (
    "The TV answered but the connection was never approved, so it timed out. "
    "On the first connection The Frame shows an allow prompt naming the "
    "client, here 'frame-art-pipeline'. Accept it with the remote while this "
    "is running. The prompt only appears when the TV is showing its own UI, "
    "so wake it out of art mode to the home screen first, and check "
    "Settings > General > External Device Manager > Device Connect Manager "
    "if it never appears or was previously denied."
)


def ensure_paired():
    """Get a token before touching the art channel.

    The art channel never raises the pairing prompt. Connecting to
    com.samsung.art-app without a token sits for exactly thirty seconds and
    then returns ms.channel.timeOut, with nothing shown on the TV, because
    the prompt lives on the remote control channel instead. Worse, with no
    token file the URL is built with a literal "token=None".

    The fork means to handle this. SamsungTVAsyncArt.get_token() carries the
    docstring "Open and close remote control websocket to get/check token",
    but its body only constructs a SamsungTVWS and discards it without ever
    opening a connection, so no token is obtained and no prompt appears.
    Opening that channel ourselves is what actually pairs.
    """
    if Path(config.TV_TOKEN_FILE).exists():
        return
    print("No token yet. Opening the remote control channel to pair.")
    print("Accept the allow prompt on the TV, client name frame-art-pipeline.")
    remote = SamsungTVWS(host=config.TV_HOST, port=config.TV_PORT,
                         token_file=config.TV_TOKEN_FILE,
                         name="frame-art-pipeline", timeout=PAIRING_TIMEOUT_S)
    try:
        remote.open()
    except Exception as error:
        raise SystemExit(f"pairing failed: {type(error).__name__}: {error}\n"
                         f"{PAIRING_HINT}")
    finally:
        try:
            remote.close()
        except Exception:
            pass
    if not Path(config.TV_TOKEN_FILE).exists():
        raise SystemExit(f"pairing produced no token.\n{PAIRING_HINT}")
    print(f"Paired. Token stored in {config.TV_TOKEN_FILE}.")


async def connect():
    ensure_paired()
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
        hint = PAIRING_HINT if "timeOut" in str(error) else OFFLINE_HINT
        raise SystemExit(
            f"could not open an art session on {config.TV_HOST}:{config.TV_PORT}: "
            f"{type(error).__name__}: {error}\n{hint}")
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


async def cmd_rotate(tv, only_in_artmode=False):
    """Show one work now. Shares its implementation with the web button.

    select_image forces art mode. Pressed by a person that is the intent;
    fired blindly on a timer it drops the HDMI signal and sleeps whatever is
    plugged into the Frame, which is what an unguarded five minute timer did
    24 times in two hours.

    only_in_artmode is what makes a timer safe. get_artmode reports "on"
    only when the TV is actually showing art and "off" while it is on an
    input, so with the guard the rotation is a no-op precisely when
    interrupting would be rude. The TV is already showing art when we act,
    so there is nothing to switch away from.
    """
    if only_in_artmode:
        try:
            mode = await tv.get_artmode()
        except Exception as error:
            print(f"cannot read art mode ({type(error).__name__}), leaving the TV alone")
            return
        if mode != "on":
            print(f"art mode is {mode!r}, leaving the TV alone")
            return

    shown = await frame_control.show_next(tv)
    if not shown:
        print("nothing in the manifest to show")
        return
    print(f"showing {shown['content_id']}  {shown['artist']} - {shown['title']}")


async def cmd_slideshow(tv, minutes):
    """Let the TV rotate its own art, over our uploads.

    Out of the box art mode shows the Art Store category, so the wall is
    stock landscapes and none of the library. Uploading does not change
    that, and neither does select_image: that sets the current artwork, but
    entering art mode with the power button falls back to this setting.
    Category 2 is MY-C0002, the user pictures.

    This is the TV rotating internally, which is the whole point. Driving it
    from outside means select_image with show=True, and that forces art
    mode: with the Frame on HDMI it drops the signal and sleeps whatever is
    plugged into it.

    Note the read back cannot be trusted. This firmware acknowledges the
    write with the right values and then reports value=off with an empty
    category, the same way get_current insists on an Art Store piece while
    something else is demonstrably on the wall. So this prints what was
    sent and what came back, and claims nothing about which is true. Watch
    the wall for a few minutes instead.
    """
    if minutes and minutes not in config.SLIDESHOW_INTERVALS:
        allowed = ", ".join(str(i) for i in config.SLIDESHOW_INTERVALS)
        raise SystemExit(
            f"the TV only accepts {allowed} minutes, or 0 for off; "
            f"{minutes} is rejected with error -7")

    before = await tv.get_slideshow_status()
    print(f"was:  value={before.get('value')!r} "
          f"category={before.get('category_id')!r} type={before.get('type')!r}")

    await tv.set_slideshow_status(duration=minutes or 0, type=True, category=2)
    print(f"sent: value={minutes or 'off'!r} category='MY-C0002' "
          f"type='shuffleslideshow'  (acknowledged by the TV)")

    await asyncio.sleep(2)
    after = await tv.get_slideshow_status()
    print(f"read: value={after.get('value')!r} "
          f"category={after.get('category_id')!r} type={after.get('type')!r}")
    if after.get("value") in (None, "", "off") and minutes:
        print("\nThe read back says off. That is expected on this firmware and\n"
              "does not mean the write failed. Put the TV in art mode and watch\n"
              f"for {minutes * 2} minutes: if the piece changes on its own, it worked.")



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
    """Make the device match the catalogue, not merely the manifest.

    Monthly rotation depends on this. The manifest accumulates every work
    ever uploaded, so pruning against it would never remove last month's
    theme; the catalogue is the statement of what the library should be
    right now, so that is what the device is reconciled against.

    Anything on the device that this pipeline never uploaded is left alone:
    only content ids the manifest claims are ever deleted.
    """
    manifest = load_manifest()
    if not manifest:
        # Every user picture on the device would look stale, including any
        # put there by hand. Refuse rather than empty the gallery.
        print("manifest is empty, refusing to prune")
        return

    try:
        catalogue = json.loads(Path(config.METADATA_FILE).read_text())
    except (OSError, ValueError) as error:
        print(f"cannot read the catalogue ({error}), refusing to prune")
        return
    wanted = {r.get("prepared_path") for r in catalogue if r.get("prepared_path")}

    ours = {entry.get("content_id") for entry in manifest.values()
            if entry.get("content_id")}
    keep = {entry["content_id"] for path, entry in manifest.items()
            if path in wanted and entry.get("content_id")}

    remote = {item.get("content_id") for item in await tv.available(USER_CATEGORY)}
    stale = sorted((ours & remote) - keep)
    if not stale:
        print("nothing to prune")
        return

    # A fetch that half failed leaves a short catalogue, and pruning against
    # it would strip the wall. Refuse anything that drastic and say so.
    share = len(stale) / max(1, len(ours))
    if share > config.PRUNE_MAX_FRACTION:
        print(f"refusing to prune {len(stale)} of {len(ours)} tracked items "
              f"({share:.0%} > {config.PRUNE_MAX_FRACTION:.0%}). "
              f"The catalogue looks incomplete; check the fetch log.")
        return

    print(f"deleting {len(stale)} items no longer in the catalogue")
    await tv.delete_list(stale)
    for path, entry in list(manifest.items()):
        if entry.get("content_id") in stale:
            del manifest[path]
    save_manifest(manifest)


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
    parser.add_argument("--rotate", action="store_true",
                        help="show one random work now")
    parser.add_argument("--only-in-artmode", action="store_true",
                        help="with --rotate, do nothing unless the TV is "
                             "already showing art; makes a timer safe")
    parser.add_argument("--quiet-if-offline", action="store_true",
                        help="exit 0 when the TV is unreachable, for timers")
    parser.add_argument("--slideshow", type=int, metavar="MINUTES",
                        help="shuffle art mode through the uploaded library, "
                             "changing every MINUTES; 0 turns rotation off")
    args = parser.parse_args()

    try:
        tv = await connect()
    except SystemExit:
        if args.quiet_if_offline:
            print("TV is not reachable; nothing to do")
            return
        raise
    try:
        if args.rotate:
            await cmd_rotate(tv, only_in_artmode=args.only_in_artmode)
        elif args.slideshow is not None:
            await cmd_slideshow(tv, args.slideshow)
        elif args.check:
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
