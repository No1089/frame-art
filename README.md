# Frame TV art pipeline: handoff brief

Target: Samsung The Frame, 32 inch, 2024. Goal is a local library of public
domain museum artwork, correctly sized, pushed over the network with the
matte overlay disabled, without paying for the Art Store subscription.

Three stages, three scripts, one config file. Intended to run unattended on
the Proxmox host.

```
fetch_art.py       museum APIs  ->  library/raw/       + catalogue.json
prepare_images.py  library/raw  ->  library/prepared/  (1920x1080 JPEG)
push_to_frame.py   library/prepared -> the TV, matte=none, over websocket
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install requests pillow
pip install git+https://github.com/NickWaterton/samsung-tv-ws-api.git
```

Then edit `config.py`. At minimum set `TV_HOST`, plus `ARTISTS` and/or
`CATEGORIES_ENABLED`.

```bash
python fetch_art.py --list-categories
python fetch_art.py --category impressionism --dry-run   # inspect the picks
python fetch_art.py
python prepare_images.py
python push_to_frame.py --check     # do this before the first real upload
python push_to_frame.py
```

## Selection: artists, categories, or both

`ARTISTS` and `CATEGORIES_ENABLED` are independent selectors. Both run, and
results are unioned and deduplicated on artist plus title. Every catalogue
record carries a `selected_by` field so you can see which query pulled it in.

Shipped presets: `impressionism`, `post-impressionism`, `ukiyo-e`,
`dutch-golden-age`, `art-nouveau`, `modernism`, `landscape`.

**Categories are harder than they look, and only AIC makes them easy.** The
three museums do not share a movement vocabulary:

- **AIC** has a genuine style facet, `style_titles`, with values like
  `Impressionism`, `Modernism` and `Japanese (culture or style)`. Its search
  endpoint is Elasticsearch backed and takes a query DSL body, so category
  filtering there is exact. This is the source to trust for style queries.
- **The Met** has no style field at all. A category becomes a keyword search
  narrowed by `dateBegin`/`dateEnd` and `departmentId`.
- **Cleveland** likewise. Keyword plus `created_after`/`created_before` plus
  `department`.

So each preset carries an `artist_hints` list of representative artists. For
the Met and Cleveland these produce far better precision than a bare keyword
search, because "impressionism" as free text also matches catalogue essays
about works that are nothing of the sort. Set
`CATEGORY_USE_ARTIST_HINTS = False` if you want keyword-only behaviour and
are willing to hand-cull the results.

Two consequences worth accepting up front. Category results are broader and
noisier than artist results, so always run `--dry-run` on a new preset before
committing to a download. And `ARTWORK_TYPES` matters more here than for
artist queries, since a department-wide sweep will otherwise hand you
furniture, coins and armour alongside the paintings.

Adding a preset is a dict entry in `config.CATEGORIES`. Copy the shape of
`impressionism`. Department names are resolved to Met ids at runtime via
`/departments`, so use display names and let the script look them up rather
than hardcoding ids that can rot.

## Things that will bite you if you assume otherwise

**The 32 inch Frame is 1920x1080, not 4K.** Every other size in the range is
3840x2160, so almost all published Frame image-prep advice targets the wrong
resolution for this panel. Config is set correctly.

**Use the NickWaterton fork, not the PyPI `samsungtvws` package.** The
upstream package predates the 2024 art API changes. The fork states support
for 2021 through 2024 models including LS03D, and recommends the async
interface as the more reliable of the two. The scripts here use async.

**Verify the art API method signatures against the installed source.** The
art module changes fairly often. Before debugging anything else:

```bash
python -c "import samsungtvws, os; print(os.path.dirname(samsungtvws.__file__))"
# read async_art.py: upload, change_matte, get_matte_list, available,
# delete_list, select_image, set_artmode
```

Assumed: `upload(data, file_type=, matte=, portrait_matte=)` returns a
content id, and `change_matte(content_id, matte_id=)` alters an existing item.
Call `get_matte_list()` once and confirm `none` is the literal accepted value
on this firmware rather than `no_matte` or similar.

**First connection needs physical confirmation.** The TV shows an allow
prompt. Accept it on the remote, after which the token in `TV_TOKEN_FILE`
persists. Uploads are unreliable while the TV is fully powered off at the
mains, so leave it in standby or art mode.

**Give the TV a DHCP reservation on the HomeVault subnet.** The token is
bound to the connection and a changed IP means re-pairing.

**Throttle.** AIC asks for no more than one request per second and no
parallel scrapers. `REQUEST_DELAY_S` defaults to 1.0. A category sweep with
artist hints enabled fires a lot of queries, so leave it alone.

**Rijksmuseum is not wired up, deliberately.** Their legacy API and its keys
were shut down in January 2026 and replaced by a keyless Linked Open Data
suite with a IIIF image endpoint. If you want Dutch holdings for the
`dutch-golden-age` preset, read the current docs at
https://data.rijksmuseum.nl/docs/ and add `rijks` searchers following the
shape of the existing ones. Do not port old example code, it targets dead
endpoints.

## Running on arrakis

An unprivileged Debian LXC is enough. No GPU, no special mounts. Pillow does
the resizing on CPU and a few hundred images take seconds.

```bash
apt install -y python3-venv python3-dev libjpeg-dev zlib1g-dev git
```

The container needs a route to the TV on the the TV subnet subnet and outbound
HTTPS to the museum APIs. No inbound ports.

Stage the tree with `pct push` as usual, then wire a timer if you want the
library to refresh periodically. `run_pipeline.sh` chains all three stages and
exits non-zero on the first failure, so a systemd timer or a cron entry can
drive it directly. Unit files are in `deploy/`.

Note that the first run must be interactive, or at least run while you can
reach the remote, because of the pairing prompt. After the token file exists
it is fully unattended. Back up `library/uploaded.json` and `tv-token.txt`
with the rest of the LXC, since together they are the only state that cannot
be regenerated.

## Fit modes

A 16:9 panel and a portrait canvas cannot both win. `FIT_MODE` picks the
compromise:

- `pad` fits the whole artwork inside the panel and fills the surround with a
  colour sampled from the artwork's own border and darkened by
  `PAD_COLOUR_DARKEN`. Default, and the most gallery-like result once the
  matte is off, because the TV is no longer drawing a competing border.
- `blur` fills the surround with a blurred scaled copy.
- `crop` fills the panel and discards the overflow. Only sensible for
  landscape works, which makes it a reasonable pairing with the `landscape`
  category and a bad one with `ukiyo-e`, where the prints are mostly tall.

`ARTWORK_MARGIN_FRACTION` controls breathing room. Set it to `0` for edge to
edge on landscape pieces.

`GAMMA_ADJUST` and `SATURATION_ADJUST` exist because Art Mode applies its own
ambient light curve using the front sensor. Leave both at `1.0` until you
have seen a batch on the wall, then pull gamma slightly below `1.0` if bright
canvases glare in a dim room.

## Sources currently wired

| Key | Museum | Licence filter | Style support |
|---|---|---|---|
| `aic` | Art Institute of Chicago | `is_public_domain` | Real style facet, exact |
| `met` | Metropolitan Museum | `isPublicDomain` | None, approximated by department and date |
| `cma` | Cleveland Museum of Art | `cc0=1` | None, approximated by department and date |

Worth adding if coverage is thin: National Gallery of Art open access,
Harvard Art Museums, Smithsonian Open Access, and Wikimedia Commons as a
general fallback. Wikimedia needs per file licence checking rather than a
single flag, so keep it behind its own function.

## Suggested acceptance check

1. `fetch_art.py --category impressionism --dry-run` returns recognisable
   works by recognisable artists. If it returns catalogue ephemera, the
   preset needs tightening before you download anything.
2. `push_to_frame.py --check` reports art mode supported and a current piece.
3. Upload exactly one image. Confirm on the wall that it appears with no
   mount and no crop.
4. Only then run the full batch.
5. Keep `library/uploaded.json`. It is the only record mapping local files to
   device content ids, and without it pruning and matte fixes cannot target
   the right items.
