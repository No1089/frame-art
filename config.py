"""
Central configuration for the Frame TV art pipeline.
Every tunable is a named variable. Nothing is hardcoded downstream.

Target hardware: Samsung The Frame, 32 inch, 2024.
NOTE: the 32 inch Frame is a Full HD panel (1920x1080), NOT 4K.
All larger sizes are 3840x2160. Do not "upgrade" the target
resolution without checking the model number on the back plate.
"""

# ---------------------------------------------------------------------------
# WHAT TO COLLECT
# ---------------------------------------------------------------------------
# Two independent selectors. Use either, or both. Results are unioned and
# deduplicated on artist plus title.

# Free text artist names, matched against each museum's artist field.
ARTISTS = [
    # "Hilma af Klint",
    # "Vilhelm Hammershoi",
]

# Keys from the CATEGORIES table further down.
CATEGORIES_ENABLED = [
    "impressionism",
]

# Which sources to query, in priority order. Earlier sources win on dedupe.
ENABLED_SOURCES = ["aic", "met", "cma"]

# Max artworks to keep per artist or category, per source.
MAX_PER_QUERY_PER_SOURCE = 25

# Restrict to these artwork types. Keeps coins, furniture and armour out.
# Set to None to accept anything the source returns.
ARTWORK_TYPES = ["Painting", "Drawing and Watercolor"]

# Reject anything whose native long edge is below this many pixels.
MIN_SOURCE_LONG_EDGE_PX = 1400

# Only accept works flagged public domain / CC0 by the source API.
REQUIRE_PUBLIC_DOMAIN = True

# Contact string sent in User-Agent. The Art Institute asks for this.
HTTP_USER_AGENT = "frame-art-pipeline/1.0 (personal use; contact@example.com)"

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
        "met_departments": ["European Paintings", "Modern and Contemporary Art"],
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
        "met_departments": ["European Paintings", "Modern and Contemporary Art"],
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
        "met_departments": ["Modern and Contemporary Art"],
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
        "met_departments": ["European Paintings", "The American Wing"],
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
PAD_COLOUR_OVERRIDE = None

# Multiply the sampled pad colour by this. Below 1.0 darkens the surround,
# which reads as a gallery wall rather than a glowing border.
PAD_COLOUR_DARKEN = 0.72

# Inset the artwork so it does not run edge to edge. Fraction of panel height.
ARTWORK_MARGIN_FRACTION = 0.04

# For FIT_MODE = "blur".
BLUR_RADIUS_PX = 48
BLUR_BRIGHTNESS = 0.55

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

TV_HOST = "192.0.2.10"            # set to the TV's reserved DHCP address
TV_PORT = 8002                      # 8002 is the TLS websocket endpoint
TV_TOKEN_FILE = "./tv-token.txt"    # created on first successful pairing

# This is the whole point of the exercise. "none" removes the mount overlay.
# Sent for both orientations because the library picks per image aspect.
MATTE = "none"
PORTRAIT_MATTE = "none"

# Delete previously uploaded items that are no longer in the local library.
PRUNE_REMOTE = False

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

RAW_DIR = "./library/raw"
PREPARED_DIR = "./library/prepared"
METADATA_FILE = "./library/catalogue.json"
UPLOAD_MANIFEST_FILE = "./library/uploaded.json"
