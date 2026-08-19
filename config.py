"""
Central configuration for the Frame TV art pipeline.
Every tunable is a named variable. Nothing is hardcoded downstream.

Target hardware: Samsung The Frame, 32 inch. Confirmed on the wire as
QE32LS03CBUXXH, model string 23_KANTSU2E_FTV_OS80, i.e. the 2023 LS03C
on Tizen OS 8, not the 2024 LS03D the original brief assumed. Inside the
NickWaterton fork's 2021-2024 support range either way.

NOTE: the 32 inch Frame is a Full HD panel (1920x1080), NOT 4K.
All larger sizes are 3840x2160. Do not "upgrade" the target
resolution without checking the model number on the back plate.
The TV itself reports "resolution": "1920x1080" at
http://<host>:8001/api/v2/ if you want to re-confirm.
"""

# ---------------------------------------------------------------------------
# WHAT TO COLLECT
# ---------------------------------------------------------------------------
# Two independent selectors. Use either, or both. Results are unioned and
# deduplicated on artist plus title.

# Free text artist names, matched against each museum's artist field.
# The Impressionists themselves, which is a far tighter selector than any
# style facet. AIC's "Impressionism" style also covers the American
# Impressionists and sweeps in realists like Winslow Homer and Jules
# Bastien-Lepage, so a category query cannot express "the Impressionists".
ARTISTS = [
    "Claude Monet",
    "Pierre-Auguste Renoir",
    "Edgar Degas",
    "Camille Pissarro",
    "Alfred Sisley",
    "Berthe Morisot",
    "Mary Cassatt",
    "Gustave Caillebotte",
    "Edouard Manet",
    "Frederic Bazille",
    "Armand Guillaumin",
    "Eva Gonzales",
    "Marie Bracquemond",
]

# Keys from the CATEGORIES table further down.
# Empty on purpose. The artist roster above is the selector; adding the
# impressionism preset back would re-admit the works it was chosen to avoid.
CATEGORIES_ENABLED = []

# Which sources to query, in priority order. Earlier sources win on dedupe.
ENABLED_SOURCES = ["aic", "met", "cma"]

# Max artworks to keep per artist or category, per source.
# Per artist, per source. Thirteen artists across three museums, so this
# is breadth across the roster rather than depth on any one name.
MAX_PER_QUERY_PER_SOURCE = 10

# Restrict to these artwork types. Keeps coins, furniture and armour out.
# Set to None to accept anything the source returns.
ARTWORK_TYPES = ["Painting", "Drawing and Watercolor"]

# Reject anything whose native long edge is below this many pixels.
MIN_SOURCE_LONG_EDGE_PX = 1400

# IIIF size for Art Institute downloads. Their server returns 403 for both
# "full/full" and "full/max", so an explicit size is mandatory rather than a
# preference. "!w,h" means best fit inside that box with the aspect ratio
# kept, so this yields a 2560px long edge whatever the orientation, which is
# ample for a 1920x1080 panel and keeps files near a megabyte.
AIC_IMAGE_SIZE = "!2560,2560"

# Cleveland publishes three derivatives per work and the API calls the
# preservation master "full". That is a TIFF, and it can run to hundreds of
# megabytes: 1958.39_full.tif is 483 MB. Downloading those to feed a 1920x1080
# panel would be absurd, so prefer "print", a few megabyte JPEG at print
# resolution. "web" is around 800px, under MIN_SOURCE_LONG_EDGE_PX, so it is
# only a fallback and prepare_images will usually reject it anyway.
CMA_IMAGE_PREFERENCE = ["print", "web"]

# Only accept works flagged public domain / CC0 by the source API.
REQUIRE_PUBLIC_DOMAIN = True

# Contact string sent in User-Agent. The Art Institute asks for this.
HTTP_USER_AGENT = "frame-art-pipeline/1.0 (personal use; you@example.com)"

# Retries and timeout for museum HTTP calls. Image servers time out under
# load often enough to matter across a few hundred downloads, and a dropped
# response means the work is silently missing from the catalogue.
HTTP_RETRIES = 3
HTTP_TIMEOUT_S = 60

# Seconds between requests to any single API host.
# The Art Institute asks for no more than one request per second.
REQUEST_DELAY_S = 1.0

# ---------------------------------------------------------------------------
# CATEGORY PRESETS
# ---------------------------------------------------------------------------
# Museums do not agree on how to describe a movement, so a category is a
# bundle of per-source strategies rather than one search term.
#
#   terms            free text sent as the q parameter
#   year_from/to     creation date window, used by met and cma
#   aic_styles       exact values matched against AIC style_titles.keyword.
#                    AIC is the only one of the three with a real style facet.
#   met_departments  department NAMES, resolved to ids at runtime via
#                    /departments so no hardcoded id can silently rot
#   cma_departments  department names as CMA spells them
#   artist_hints     representative artists. For met and cma, which have no
#                    style field, these produce far better precision than a
#                    keyword search alone. Set CATEGORY_USE_ARTIST_HINTS to
#                    False if you want keyword-only behaviour.

CATEGORY_USE_ARTIST_HINTS = True

CATEGORIES = {
    "impressionism": {
        "terms": ["impressionism"],
        "year_from": 1860,
        "year_to": 1910,
        "aic_styles": ["Impressionism"],
        "met_departments": ["European Paintings", "Modern Art"],
        "cma_departments": ["Modern European Painting and Sculpture"],
        "artist_hints": [
            "Claude Monet", "Camille Pissarro", "Alfred Sisley",
            "Berthe Morisot", "Pierre-Auguste Renoir", "Edgar Degas",
            "Gustave Caillebotte", "Mary Cassatt", "Eva Gonzales",
        ],
    },
    "post-impressionism": {
        "terms": ["post-impressionism"],
        "year_from": 1880,
        "year_to": 1920,
        "aic_styles": ["Post-Impressionism"],
        "met_departments": ["European Paintings", "Modern Art"],
        "cma_departments": ["Modern European Painting and Sculpture"],
        "artist_hints": [
            "Vincent van Gogh", "Paul Cezanne", "Paul Gauguin",
            "Georges Seurat", "Paul Signac", "Henri de Toulouse-Lautrec",
        ],
    },
    "ukiyo-e": {
        "terms": ["ukiyo-e woodblock print"],
        "year_from": 1700,
        "year_to": 1900,
        "aic_styles": ["Japanese (culture or style)"],
        "met_departments": ["Asian Art"],
        "cma_departments": ["Japanese Art"],
        "artist_hints": [
            "Utagawa Hiroshige", "Katsushika Hokusai", "Kitagawa Utamaro",
            "Utagawa Kuniyoshi", "Torii Kiyonaga",
        ],
    },
    "dutch-golden-age": {
        "terms": ["Dutch golden age painting"],
        "year_from": 1600,
        "year_to": 1700,
        "aic_styles": [],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": [
            "Rembrandt van Rijn", "Johannes Vermeer", "Jacob van Ruisdael",
            "Pieter de Hooch", "Frans Hals", "Willem Kalf",
        ],
    },
    "art-nouveau": {
        "terms": ["art nouveau"],
        "year_from": 1885,
        "year_to": 1915,
        "aic_styles": ["Art Nouveau"],
        "met_departments": ["Drawings and Prints"],
        "cma_departments": ["Prints"],
        "artist_hints": [
            "Alphonse Mucha", "Gustav Klimt", "Aubrey Beardsley",
            "Henri Riviere", "Eugene Grasset",
        ],
    },
    "modernism": {
        "terms": ["modernism"],
        "year_from": 1900,
        "year_to": 1960,
        "aic_styles": ["Modernism"],
        "met_departments": ["Modern Art"],
        "cma_departments": ["Modern European Painting and Sculpture"],
        "artist_hints": [
            "Georgia O'Keeffe", "Wassily Kandinsky", "Paul Klee",
            "Piet Mondrian", "Hilma af Klint", "Sonia Delaunay",
        ],
    },
    "landscape": {
        "terms": ["landscape"],
        "year_from": 1700,
        "year_to": 1950,
        "aic_styles": [],
        # "The American Wing" is not a resolvable department: /departments
        # calls id 1 "American Decorative Arts", object records still say
        # "The American Wing", and searching id 1 returns nothing.
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": [
            "J. M. W. Turner", "Caspar David Friedrich", "John Constable",
            "Albert Bierstadt", "Ivan Shishkin",
        ],
    },
}

# ---------------------------------------------------------------------------
# DISPLAY TARGET
# ---------------------------------------------------------------------------

TARGET_WIDTH_PX = 1920
TARGET_HEIGHT_PX = 1080

# How to reconcile a portrait or square painting with a 16:9 panel.
#   "pad"   fit whole artwork inside the frame, fill the rest with a flat
#           colour sampled from the artwork edge. Preserves composition.
#   "crop"  fill the panel, centre crop the overflow. Loses composition.
#   "blur"  fit whole artwork, fill the rest with a blurred scaled copy.
FIT_MODE = "pad"

# For FIT_MODE = "pad". If None, sample the artwork's border pixels.
# Set to a hex string like "#1a1a1a" to force one colour for every image.
# Black, deliberately and for every image: on a panel hung as a picture the
# surround should disappear rather than glow, and a per artwork sampled
# colour makes the wall change tint every time the piece rotates.
PAD_COLOUR_OVERRIDE = "#000000"

# Multiply the sampled pad colour by this. No effect while
# PAD_COLOUR_OVERRIDE is set, since that short circuits the sampling.
# Below 1.0 darkens the surround,
# which reads as a gallery wall rather than a glowing border.
PAD_COLOUR_DARKEN = 0.72

# Inset the artwork so it does not run edge to edge. Fraction of panel height.
ARTWORK_MARGIN_FRACTION = 0.04

# For FIT_MODE = "blur".
BLUR_RADIUS_PX = 48
BLUR_BRIGHTNESS = 0.55

# ---------------------------------------------------------------------------
# MUSEUM LABEL
# ---------------------------------------------------------------------------
# The Frame shows no metadata at all for a user uploaded image: no title, no
# artist, nothing. The only place a caption can live is in the pixels, so it
# is burned in at prepare time. Changing any of this means re-running
# prepare_images.py --force and re-uploading, since the text is part of the
# JPEG.

LABEL_ENABLED = True

# "auto" picks by orientation, which is the only setting that treats both
# shapes well on a 16:9 panel:
#   portrait and square  caption in a column beside the artwork
#   landscape            artwork runs the full width, caption below it,
#                        tucked under its right hand end
# "side" and "bottom" force one layout for everything. "side" is the setting
# in use: a caption below a landscape costs it vertical space it was using,
# whereas beside it the artwork keeps the full panel height.
LABEL_POSITION = "side"

# Side layout. The artwork is fitted into the panel minus this column, then
# anchored left, and the caption gets everything left over. A portrait is
# limited by height, so it leaves a wide column with room for the blurb; a
# wide landscape is limited by width and leaves exactly the minimum, which
# holds the artist and title but not a paragraph.
LABEL_MIN_COLUMN_PX = 330

# Cap on the caption column. Without it a portrait leaves a column over
# 1100px wide and the blurb sets in 150 character lines, which is unreadable
# however nice the font is. Artwork and caption are centred as a pair, so the
# leftover width stays as margin rather than as a hole on the right.
LABEL_MAX_COLUMN_PX = 660
LABEL_GAP_PX = 38
LABEL_EDGE_MARGIN_PX = 40

# Only draw the blurb when the column is at least this wide. Below it the
# text wraps to two or three words a line and looks like a ransom note.
LABEL_BLURB_MIN_COLUMN_PX = 430

# Landscape layout. The caption sits below the artwork, its right edge
# aligned with the artwork's, and the pair is centred vertically. A very wide
# painting leaves room to spare below it and earns a blurb; a 4:3 one is
# limited by height instead and gets the tombstone only.
LABEL_CAPTION_GAP_PX = 42
LABEL_MIN_STRIP_PX = 150
LABEL_BLURB_MIN_STRIP_PX = 250

# Forced "bottom" layout only: strip height as a fraction of panel height.
LABEL_HEIGHT_FRACTION = 0.11

# Gallery convention: artist on the first line, then title and date. Keep the
# second line dimmer so the eye lands on the painting, not the caption.
LABEL_ARTIST_COLOUR = "#e6e2d9"
LABEL_DETAIL_COLOUR = "#8d877c"
LABEL_ARTIST_SIZE_PX = 31
LABEL_DETAIL_SIZE_PX = 26
LABEL_LINE_GAP_PX = 9

# Tombstone is the medium and credit line. Blurb is the wall text.
LABEL_TOMBSTONE_COLOUR = "#6f6a61"
LABEL_TOMBSTONE_SIZE_PX = 20
LABEL_BLURB_COLOUR = "#8d877c"
LABEL_BLURB_SIZE_PX = 20
LABEL_BLURB_LINE_SPACING = 1.45
LABEL_PARAGRAPH_GAP_PX = 26

# First path that exists wins. macOS first, then the Debian packages an LXC
# would have, then Pillow's built-in as a last resort.
LABEL_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Palatino.ttc",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
]
LABEL_FONT_ITALIC_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
]

# Museum credit lines are noise on a wall: strip "(French, 1848-1894)" and
# similar trailing parentheticals from the artist name. Cleveland attaches
# these to every creator string.
LABEL_STRIP_ARTIST_PARENTHETICAL = True

# ---------------------------------------------------------------------------
# OUTPUT ENCODING
# ---------------------------------------------------------------------------

OUTPUT_FORMAT = "JPEG"
JPEG_QUALITY = 92
STRIP_METADATA = True

# Art Mode applies its own ambient brightness curve. Values below 1.0 pull
# the midtones down and stop bright canvases blowing out in a dim room.
GAMMA_ADJUST = 1.0
SATURATION_ADJUST = 1.0

# Hard ceiling on a single uploaded file. Larger uploads get flaky.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

# ---------------------------------------------------------------------------
# THE FRAME
# ---------------------------------------------------------------------------

TV_HOST = "192.0.2.10"          # give this a DHCP reservation in UniFi
TV_PORT = 8002                      # 8002 is the TLS websocket endpoint
TV_TOKEN_FILE = "./tv-token.txt"    # created on first successful pairing

# This is the whole point of the exercise. "none" removes the mount overlay.
# Sent for both orientations because the library picks per image aspect.
MATTE = "none"
PORTRAIT_MATTE = "none"

# Delete previously uploaded items that are no longer in the local library.
# On for the monthly rotation: without it last month's theme stays on the TV
# for ever. Only content ids this pipeline recorded are ever deleted, so
# anything uploaded by hand is safe.
PRUNE_REMOTE = True

# Refuse a prune that would remove more than this share of tracked items. A
# fetch that half failed leaves a short catalogue, and reconciling against it
# would otherwise strip the wall bare.
PRUNE_MAX_FRACTION = 0.5

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

RAW_DIR = "./library/raw"
PREPARED_DIR = "./library/prepared"
METADATA_FILE = "./library/catalogue.json"
UPLOAD_MANIFEST_FILE = "./library/uploaded.json"

# ---------------------------------------------------------------------------
# SEASONAL THEMES
# ---------------------------------------------------------------------------
# The library is a permanent core plus a monthly overlay. The core is the
# ARTISTS roster above and stays on the wall all year; a theme is layered over
# it and swapped each month, so a thin month never leaves the wall empty.
#
# Themes deliberately reach outside Impressionism. The movement painted summer
# and snow far more often than it painted October, so the autumn months widen
# to Barbizon, the Hudson River School and ukiyo-e rather than return six
# sparse results and call it a season.
#
# A theme is the same shape as a CATEGORIES preset, so met and cma reuse the
# category searchers unchanged. Only AIC gains anything: subject_titles is a
# real controlled vocabulary facet and can be matched exactly, the way
# style_titles is. A Monet haystack carries subject_titles of seasons, nature,
# farm, trees, hills, landscapes and rural life, which is precisely the
# vocabulary a seasonal theme wants.
#
#   aic_subjects   exact values matched against AIC subject_titles.keyword
#   terms          free text for met and cma, and for AIC when aic_subjects
#                  is empty
#   artist_hints   representative painters; for met and cma these carry the
#                  precision that the missing subject facet cannot

THEME_ENABLED = True

# Kept per theme, per source. Smaller than the core on purpose: the theme is
# a seasonal accent over a permanent collection, not a replacement for it.
MAX_PER_THEME_PER_SOURCE = 8

THEMES = {
    1: {
        "name": "winter light",
        "terms": ["snow winter landscape"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["winter", "snow"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Claude Monet", "Alfred Sisley", "Camille Pissarro",
                         "Utagawa Hiroshige", "Pieter Bruegel"],
    },
    2: {
        # The thinnest month of the twelve. mothers was dropped from the
        # subjects: it is a 117 work facet and almost all of it is
        # Madonnas and Holy Families, which is not what February wants. Public domain holdings skew to
        # mother and child and to courtship rather than to romance, so this
        # reads as tenderness and domestic intimacy. Cassatt and Morisot
        # carry it. Expect to hand cull.
        "name": "love and intimacy",
        "terms": ["couple lovers embrace"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["love", "couples"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Mary Cassatt", "Berthe Morisot",
                         "Pierre-Auguste Renoir", "Henri de Toulouse-Lautrec",
                         "Jean-Honore Fragonard"],
    },
    3: {
        "name": "thaw",
        "terms": ["thaw river flood early spring"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["rivers", "seasons"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Alfred Sisley", "Claude Monet", "Charles Daubigny",
                         "Camille Corot"],
    },
    4: {
        "name": "blossom and gardens",
        "terms": ["blossom orchard garden flowering tree"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["gardens", "parks"],
        "met_departments": ["European Paintings", "Asian Art"],
        "cma_departments": ["Japanese Art"],
        "artist_hints": ["Claude Monet", "Vincent van Gogh",
                         "Utagawa Hiroshige", "Katsushika Hokusai"],
    },
    5: {
        "name": "flowers and promenades",
        "terms": ["flowers still life park promenade"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["gardens", "fruit"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Pierre-Auguste Renoir", "Henri Fantin-Latour",
                         "Edouard Manet", "Gustave Caillebotte"],
    },
    6: {
        "name": "water and boating",
        "terms": ["boats sailing river regatta"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["boats", "sailing", "rivers"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Claude Monet", "Gustave Caillebotte",
                         "Alfred Sisley", "Camille Pissarro"],
    },
    7: {
        "name": "seaside",
        "terms": ["beach seaside coast cliffs"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["beaches", "oceans", "boats"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Claude Monet", "Eugene Boudin", "Berthe Morisot",
                         "Winslow Homer"],
    },
    8: {
        "name": "harvest",
        "terms": ["harvest wheat field haystack"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["farm", "seasons"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Claude Monet", "Camille Pissarro",
                         "Jean-Francois Millet", "Vincent van Gogh"],
    },
    9: {
        "name": "late light",
        "terms": ["vineyard orchard fruit late summer"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["fruit", "farm"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Paul Cezanne", "Vincent van Gogh",
                         "Camille Pissarro", "Gustave Caillebotte"],
    },
    10: {
        # Impressionism is thin here, so this one reaches out to Barbizon and
        # the Hudson River School on purpose.
        "name": "autumn colour",
        "terms": ["autumn forest falling leaves"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["autumn", "forests"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Camille Corot", "Theodore Rousseau",
                         "Jasper Francis Cropsey", "Frederic Edwin Church",
                         "Vincent van Gogh"],
    },
    11: {
        "name": "rain and fog",
        "terms": ["rain fog mist wet street nocturne"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["rain", "cities"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["Gustave Caillebotte", "James McNeill Whistler",
                         "Camille Pissarro", "J. M. W. Turner",
                         "Utagawa Hiroshige"],
    },
    12: {
        "name": "night and interiors",
        "terms": ["night interior lamplight evening"],
        "year_from": 1600, "year_to": 1950,
        "aic_subjects": ["night", "interiors"],
        "met_departments": ["European Paintings"],
        "cma_departments": ["European Painting and Sculpture"],
        "artist_hints": ["James McNeill Whistler", "Edgar Degas",
                         "Vincent van Gogh", "Vilhelm Hammershoi"],
    },
}
