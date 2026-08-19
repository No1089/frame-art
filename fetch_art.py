#!/usr/bin/env python3
"""
Stage 1: pull public domain artwork at the highest resolution each museum
offers, selected by artist name, by category, or both.

Sources, all keyless:
  aic  Art Institute of Chicago      https://api.artic.edu/docs/
  met  Metropolitan Museum of Art    https://metmuseum.github.io/
  cma  Cleveland Museum of Art       https://openaccess-api.clevelandart.org/

Only AIC exposes a real style facet (style_titles). For the Met and
Cleveland a category becomes a keyword search narrowed by date window,
department and, if CATEGORY_USE_ARTIST_HINTS is on, the representative
artists listed in the preset. Department names are resolved to ids at
runtime so no hardcoded id can silently rot.

Writes originals to config.RAW_DIR and a catalogue to config.METADATA_FILE.

Usage:
    python fetch_art.py
    python fetch_art.py --list-categories
    python fetch_art.py --category impressionism --source aic
    python fetch_art.py --artist "Hilma af Klint"
    python fetch_art.py --dry-run
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests

import config

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": config.HTTP_USER_AGENT,
                        "AIC-User-Agent": config.HTTP_USER_AGENT})

_MET_DEPARTMENTS = None


def _get(url, **kwargs):
    time.sleep(config.REQUEST_DELAY_S)
    response = SESSION.get(url, timeout=45, **kwargs)
    response.raise_for_status()
    return response


def _post(url, payload):
    time.sleep(config.REQUEST_DELAY_S)
    response = SESSION.post(url, json=payload, timeout=45)
    response.raise_for_status()
    return response


def type_allowed(type_name):
    if not config.ARTWORK_TYPES:
        return True
    if not type_name:
        return False
    return any(allowed.lower() in type_name.lower()
               for allowed in config.ARTWORK_TYPES)


# ---------------------------------------------------------------------------
# Art Institute of Chicago
# ---------------------------------------------------------------------------

AIC_FIELDS = ["id", "title", "artist_title", "date_display", "image_id",
              "is_public_domain", "style_titles", "artwork_type_title"]
AIC_SEARCH = "https://api.artic.edu/api/v1/artworks/search"


def _aic_run(must, limit):
    """AIC search is Elasticsearch backed and accepts a query DSL body."""
    payload = {"query": {"bool": {"must": must}},
               "fields": AIC_FIELDS,
               "limit": min(limit * 2, 100)}
    try:
        data = _post(AIC_SEARCH, payload).json()
    except requests.HTTPError:
        # Fallback for the GET-only bracketed parameter form.
        terms = " ".join(str(clause).replace("'", "") for clause in must)
        data = _get(AIC_SEARCH, params={"q": terms,
                                        "fields": ",".join(AIC_FIELDS),
                                        "limit": min(limit * 2, 100)}).json()

    results = []
    for item in data.get("data", []):
        if len(results) >= limit:
            break
        if not item.get("image_id"):
            continue
        if config.REQUIRE_PUBLIC_DOMAIN and not item.get("is_public_domain"):
            continue
        if not type_allowed(item.get("artwork_type_title")):
            continue
        results.append({
            "source": "aic",
            "source_id": str(item["id"]),
            "title": item.get("title") or "Untitled",
            "artist": item.get("artist_title") or "Unknown",
            "date": item.get("date_display") or "",
            "style": ", ".join(item.get("style_titles") or []),
            # full/full requests the largest derivative the IIIF server holds
            "image_url": (f"https://www.artic.edu/iiif/2/{item['image_id']}"
                          f"/full/full/0/default.jpg"),
        })
    return results


def aic_by_artist(artist, limit):
    must = [{"term": {"is_public_domain": True}},
            {"match": {"artist_title": {"query": artist, "operator": "and"}}}]
    return _aic_run(must, limit)


def aic_by_category(preset, limit):
    must = [{"term": {"is_public_domain": True}}]
    styles = preset.get("aic_styles") or []
    if styles:
        must.append({"terms": {"style_titles.keyword": styles}})
    else:
        must.append({"match": {"term_titles": " ".join(preset["terms"])}})
    return _aic_run(must, limit)


# ---------------------------------------------------------------------------
# Metropolitan Museum of Art
# ---------------------------------------------------------------------------
# Two quirks of /search, both verified against the live API rather than
# inferred from the docs:
#
#   1. It is parameter ORDER sensitive. Filters are only honoured when q comes
#      first. "impressionism" in European Paintings 1860-1910 returns 12 hits
#      with q leading and 241 with q trailing, i.e. with q last the department
#      and date filters are silently ignored. So Met params are built as
#      ordered lists of pairs with q at the front, never dict(base, q=...).
#
#   2. artistOrCulture=true is far lossier than it looks. Inside European
#      Paintings it returns nothing at all for Renoir, Cassatt, Morisot and
#      Caillebotte, where a plain q for the same names returns 38, 37, 29 and
#      17. It is dropped here in favour of post-filtering on
#      artistDisplayName, which _met_collect already does.

MET_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"


def met_department_ids(names):
    global _MET_DEPARTMENTS
    if _MET_DEPARTMENTS is None:
        data = _get(f"{MET_BASE}/departments").json()
        _MET_DEPARTMENTS = {d["displayName"].lower(): d["departmentId"]
                            for d in data.get("departments", [])}
    ids = []
    for name in names or []:
        found = _MET_DEPARTMENTS.get(name.lower())
        if found:
            ids.append(found)
        else:
            print(f"  met: unknown department {name!r}, ignoring")
    return ids


def _met_collect(params, limit, artist_filter=None):
    ids = (_get(f"{MET_BASE}/search", params=params).json().get("objectIDs") or [])
    results = []
    for object_id in ids[:limit * 6]:
        if len(results) >= limit:
            break
        try:
            item = _get(f"{MET_BASE}/objects/{object_id}").json()
        except requests.HTTPError:
            continue
        if config.REQUIRE_PUBLIC_DOMAIN and not item.get("isPublicDomain"):
            continue
        if not item.get("primaryImage"):
            continue
        # Met paintings often carry an empty classification but a usable
        # objectName. Bierstadt's The Rocky Mountains is one such record, and
        # classification alone would silently discard it.
        if not type_allowed(item.get("classification") or item.get("objectName")):
            continue
        artist_name = item.get("artistDisplayName") or ""
        if artist_filter and artist_filter.lower() not in artist_name.lower():
            continue
        results.append({
            "source": "met",
            "source_id": str(object_id),
            "title": item.get("title") or "Untitled",
            "artist": artist_name or "Unknown",
            "date": item.get("objectDate") or "",
            "style": item.get("period") or item.get("culture") or "",
            "image_url": item["primaryImage"],
        })
    return results


def met_by_artist(artist, limit):
    return _met_collect([("q", artist), ("hasImages", "true")], limit,
                        artist_filter=artist)


def met_by_category(preset, limit):
    department_ids = met_department_ids(preset.get("met_departments"))
    window = [("hasImages", "true"),
              ("dateBegin", preset["year_from"]),
              ("dateEnd", preset["year_to"])]
    # One query set per department. Only the first was used before, which
    # quietly discarded the second for every preset that names two.
    departments = [[("departmentId", d)] for d in department_ids] or [[]]

    queries = []
    for department in departments:
        queries.append(([("q", " ".join(preset["terms"]))] + window + department,
                        None))
        if config.CATEGORY_USE_ARTIST_HINTS:
            for hint in preset.get("artist_hints", []):
                # The hint is also the post-filter. Without it a fuzzy match
                # on a hint name pulls in whatever the search feels like,
                # which is how an Egyptian Book of the Dead scores highly for
                # "Albert Bierstadt".
                queries.append(([("q", hint)] + window + department, hint))

    per_query = max(2, limit // max(1, len(queries)))
    results = []
    for params, artist_filter in queries:
        if len(results) >= limit:
            break
        try:
            results.extend(_met_collect(params, per_query,
                                        artist_filter=artist_filter))
        except requests.RequestException as error:
            print(f"  met query failed: {error}")
    return results[:limit]


# ---------------------------------------------------------------------------
# Cleveland Museum of Art
# ---------------------------------------------------------------------------

CMA_URL = "https://openaccess-api.clevelandart.org/api/artworks/"


def _cma_collect(params, limit):
    data = _get(CMA_URL, params=params).json()
    results = []
    for item in data.get("data", []):
        if len(results) >= limit:
            break
        images = item.get("images") or {}
        best = images.get("full") or images.get("print") or images.get("web")
        if not best or not best.get("url"):
            continue
        if not type_allowed(item.get("type")):
            continue
        creators = ", ".join(c.get("description", "")
                             for c in item.get("creators", []))
        results.append({
            "source": "cma",
            "source_id": str(item.get("id")),
            "title": item.get("title") or "Untitled",
            "artist": creators or "Unknown",
            "date": item.get("creation_date") or "",
            "style": item.get("culture") and ", ".join(item["culture"]) or "",
            "image_url": best["url"],
        })
    return results


def cma_by_artist(artist, limit):
    return _cma_collect({"artists": artist, "cc0": 1, "has_image": 1,
                         "limit": limit * 2}, limit)


def cma_by_category(preset, limit):
    base = {"cc0": 1, "has_image": 1, "limit": limit * 2,
            "created_after": preset["year_from"],
            "created_before": preset["year_to"]}
    departments = preset.get("cma_departments") or []
    if departments:
        base["department"] = departments[0]

    queries = [dict(base, q=" ".join(preset["terms"]))]
    if config.CATEGORY_USE_ARTIST_HINTS:
        for hint in preset.get("artist_hints", []):
            queries.append(dict(base, artists=hint))

    per_query = max(2, limit // max(1, len(queries)))
    results = []
    for params in queries:
        if len(results) >= limit:
            break
        try:
            results.extend(_cma_collect(params, per_query))
        except requests.RequestException as error:
            print(f"  cma query failed: {error}")
    return results[:limit]


ARTIST_SEARCHERS = {"aic": aic_by_artist, "met": met_by_artist,
                    "cma": cma_by_artist}
CATEGORY_SEARCHERS = {"aic": aic_by_category, "met": met_by_category,
                      "cma": cma_by_category}


# ---------------------------------------------------------------------------

def slugify(text, max_length=60):
    slug = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:max_length] or "untitled"


def download(record, raw_dir):
    filename = (f"{slugify(record['artist'], 30)}__"
                f"{slugify(record['title'], 50)}__"
                f"{record['source']}-{record['source_id']}.jpg")
    path = raw_dir / filename
    if path.exists():
        record["raw_path"] = str(path)
        return True
    try:
        response = _get(record["image_url"], stream=True)
    except requests.RequestException as error:
        print(f"  download failed: {record['title']}: {error}")
        return False
    path.write_bytes(response.content)
    record["raw_path"] = str(path)
    record["sha256"] = hashlib.sha256(response.content).hexdigest()
    record["bytes"] = len(response.content)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist", action="append",
                        help="override config.ARTISTS, repeatable")
    parser.add_argument("--category", action="append",
                        choices=list(config.CATEGORIES),
                        help="override config.CATEGORIES_ENABLED, repeatable")
    parser.add_argument("--source", action="append",
                        choices=list(ARTIST_SEARCHERS),
                        help="override config.ENABLED_SOURCES, repeatable")
    parser.add_argument("--list-categories", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="search and report, download nothing")
    args = parser.parse_args()

    if args.list_categories:
        for key, preset in config.CATEGORIES.items():
            hints = ", ".join(preset.get("artist_hints", [])[:4])
            print(f"{key:22} {preset['year_from']}-{preset['year_to']}  {hints}")
        return

    artists = args.artist if args.artist is not None else config.ARTISTS
    categories = (args.category if args.category is not None
                  else config.CATEGORIES_ENABLED)
    sources = args.source or config.ENABLED_SOURCES
    if not artists and not categories:
        raise SystemExit("Nothing selected. Set ARTISTS or CATEGORIES_ENABLED.")

    raw_dir = Path(config.RAW_DIR)
    raw_dir.mkdir(parents=True, exist_ok=True)

    catalogue = []
    seen_keys = set()
    limit = config.MAX_PER_QUERY_PER_SOURCE

    jobs = ([("artist", name, ARTIST_SEARCHERS, name) for name in artists] +
            [("category", key, CATEGORY_SEARCHERS, config.CATEGORIES[key])
             for key in categories])

    for kind, label, searchers, argument in jobs:
        for source in sources:
            print(f"[{source}] {kind}: {label}")
            try:
                found = searchers[source](argument, limit)
            except requests.RequestException as error:
                print(f"  search failed: {error}")
                continue
            print(f"  {len(found)} candidates")

            for record in found:
                key = (slugify(record["artist"], 30), slugify(record["title"], 50))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                record["selected_by"] = f"{kind}:{label}"
                if args.dry_run:
                    print(f"    {record['artist']} - {record['title']}")
                    catalogue.append(record)
                elif download(record, raw_dir):
                    catalogue.append(record)

    if args.dry_run:
        print(f"\ndry run: {len(catalogue)} works would be downloaded")
        return

    metadata_path = Path(config.METADATA_FILE)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(catalogue, indent=2, ensure_ascii=False))
    print(f"\n{len(catalogue)} works in {metadata_path}")


if __name__ == "__main__":
    main()
