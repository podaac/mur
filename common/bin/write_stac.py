#!/usr/bin/env python3
"""Write a self-contained STAC catalog into a DPS job's output directory.

WHY THIS EXISTS
    MAAP ingests STAC metadata that an algorithm writes alongside its normal
    outputs. A `catalog.json` at the root of the staged-out directory is
    picked up automatically and published to

        https://dps-stac.maap-project.org
        https://dps-stac.maap-project.org/catalogs/<username>
        https://dps-stac-browser.maap-project.org
        https://titiler-dps-stac.maap-project.org

    -- no registration request, no ticket, no public bucket. This is the
    documented mechanism (docs.maap-project.org, "Generating STAC metadata for
    DPS job outputs", 2026-01-06) and it is the reason the pipeline does not
    need to copy its products to invented S3 keys: the ingestion service
    resolves relative asset hrefs to absolute s3:// URLs, so the file stays
    exactly where DPS put it and the STAC Item becomes its stable address.

WHY NOT pystac
    The documented examples use pystac and rio-stac. Neither is present in
    the MUR images: cog is debian-slim plus gdal-bin, mrva is a MATLAB Runtime
    image, and both get python3 only as a transitive dependency of awscli --
    there is no pip. Adding one would mean a pip layer in a 20 GB MATLAB image
    to emit a few kilobytes of JSON.

    The catalog this writes is byte-equivalent in structure to what
    `Catalog.normalize_and_save()` produces, and `tests/test_write_stac.py`
    validates its output against pystac (a dev dependency, installed on the
    developer's machine, never in the image). Validation therefore happens
    before the image is built rather than inside it, which catches the same
    errors earlier.

LAYOUT
    Matching normalize_and_save() exactly, because that is the shape the
    ingestion service sees in practice:

        output/
          catalog.json
          <collection-id>/
            collection.json
            <item-id>/
              <item-id>.json
          <the data files themselves, wherever the algorithm put them>

USAGE
    write_stac.py --output-dir output \
        --collection mur-l4-sst \
        --collection-title "MUR L4 SST analysis" \
        --collection-description "..." \
        --item-id mur-l4-20261006-nrt \
        --datetime 2026-10-06T09:00:00Z \
        --property mur:mode=nrt --property mur:doy=279 \
        --asset data=netcdf/GLOB/JPL/MUR/v4/2026/279nrt/2026...fv04.1.nc \
        --asset sst=2026...-MUR-GLOB-v02.0-fv04.1_sst.tif
"""
import argparse
import datetime
import json
import os
import posixpath
import re
import sys

STAC_VERSION = "1.0.0"

# MUR L4 is a global analysis; every granule has the same footprint. Written
# as an explicit polygon rather than derived from the file because the
# netCDF path has no raster library to ask.
GLOBAL_BBOX = [-180.0, -90.0, 180.0, 90.0]
GLOBAL_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [-180.0, -90.0], [180.0, -90.0], [180.0, 90.0],
        [-180.0, 90.0], [-180.0, -90.0],
    ]],
}

COG_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"
NETCDF_TYPE = "application/x-netcdf"

# Render hints per field, keyed by the asset name the COG module uses.
#
# NO unscale HERE. The browse rasters hold real units -- celsius for SST,
# kelvin-equivalent differences for the anomaly and the error, a fraction for
# ice -- because the COG step converts them rather than passing GHRSST's
# packed integers through. An earlier generation of these files held raw
# int16 and needed unscale=true; items written by those builds carry it in
# their own stored render block, which is how a reader tells them apart.
#
# rescale still matters: without an explicit range titiler stretches each
# request to whatever it happens to see, so a field is drawn on a different
# colour scale every day and nothing on screen says so.
RENDER = {
    # Measured on a real granule: -1.8 .. 34.2 C.
    #
    # -2 rather than 0 as the floor, because seawater freezes near -1.8 and
    # the polar ocean really does sit there; a 0 C floor would clamp a
    # genuine part of the field flat. 35 rather than 34 at the top for the
    # same reason in reverse -- 34 was the first choice and a test caught
    # that it cut off the warmest water by two tenths of a degree.
    "sst":  {"rescale": "-2,35", "colormap_name": "thermal"},
    "anom": {"rescale": "-5,5", "colormap_name": "coolwarm"},
    # Measured 0.800..0.810 K on a real granule -- only two distinct values,
    # so a 0..2 ramp put the whole field in one colour. 0..1 is still fixed,
    # so days stay comparable.
    "err":  {"rescale": "0,1", "colormap_name": "magma"},
    "ice":  {"rescale": "0,1", "colormap_name": "ice"},
    # Categorical: GHRSST packs water/land/lake/ice as bit flags, this one is
    # left in its native integer type, and a continuous ramp over flags is
    # approximate by nature. Observed 1..9.
    "mask": {"rescale": "1,16", "colormap_name": "tab10"},
}

# What a pixel means, for the asset metadata. Browse rasters are useless if a
# reader has to guess whether a number is kelvin, celsius or a packed count.
UNITS = {
    "sst":  "degree_Celsius",
    "anom": "degree_Celsius",
    "err":  "degree_Celsius",
    "ice":  "1",
    "mask": "flag",
}

# Why the granules and the COGs are never assets of the same item:
# titiler computes an item's zoom bounds across all its assets, so an item
# holding a netCDF beside its GeoTIFFs fails to tile for every value of
# `assets=`, including the GeoTIFF's own key. Verified against
# titiler-dps-stac 2026-10-08. mur writes one item per asset family.
# Collection metadata, by the id the catalog declares.
#
# WHAT SURVIVES INGEST, AND WHAT DOES NOT
#   Verified against a real ingested collection on 2026-10-09
#   (jleach_jpl__mur-mrva_1756__2.0.14): title, description, extent, license
#   and renders all came through unchanged. Only the ID is rewritten. Three
#   more fields are preserved on other users' collections and so are included
#   here -- keywords and providers. item_assets is NOT used; see
#   build_collection for why it breaks tiling.
#
#   So the collection id is not the label. It is machine plumbing
#   (<username>__<algorithm>__<version>), and the human-readable name is the
#   title below. A browser listing shows the title; nothing but a URL shows
#   the id.
#
# Kept here rather than passed in as flags because it is prose with commas,
# quotes and nested structure, and threading that through bash would be all
# quoting and no clarity. The entrypoints name a collection; this says what
# that collection is.
COLLECTIONS = {
    "mur-l4-sst": {
        "title": "MUR L4 Sea Surface Temperature Analysis",
        "description": (
            "Multi-scale Ultra-high Resolution (MUR) Level 4 foundation sea "
            "surface temperature analysis. A variational analysis fuses "
            "infrared and microwave satellite radiometry with iQuam in-situ "
            "observations against a seasonal climatology and a daily "
            "land/ice mask, producing a gap-free global field. Each item "
            "carries the 1 km product and its 0.25 degree MUR25 sibling, "
            "both as GHRSST-conventions netCDF."
        ),
        "keywords": ["MUR", "SST", "GHRSST", "L4", "sea surface temperature",
                     "ocean", "analysis"],
        "providers": [
            {"name": "NASA JPL PO.DAAC", "roles": ["producer", "processor"],
             "url": "https://podaac.jpl.nasa.gov/"},
            {"name": "MUR SST", "roles": ["processor"],
             "url": "https://github.com/podaac/mur"},
        ],
    },
    "mur-l4-browse": {
        "title": "MUR L4 SST Browse Imagery",
        "description": (
            "Cloud-optimized GeoTIFF browse layers rendered from the MUR L4 "
            "sea surface temperature analysis, one per field, for display on "
            "a web map. Derived imagery -- for the analysis itself in netCDF, "
            "see the MUR L4 Sea Surface Temperature Analysis collection. "
            "Item ids carry the day and the resolution but not the analysis "
            "mode, so a reanalysis replaces that day's picture rather than "
            "adding a second layer for the same date."
        ),
        "keywords": ["MUR", "SST", "GHRSST", "COG", "browse", "visualization",
                     "sea surface temperature"],
        "providers": [
            {"name": "NASA JPL PO.DAAC", "roles": ["producer", "processor"],
             "url": "https://podaac.jpl.nasa.gov/"},
            {"name": "MUR SST", "roles": ["processor"],
             "url": "https://github.com/podaac/mur"},
        ],
    },
}


# What each asset actually is. STAC browsers show this when an asset is
# expanded; without it the panel falls back to the media type and reads
# "Cloud-Optimized GeoTIFF image", which tells a reader nothing they could
# not see from the icon.
ASSET_DESCRIPTIONS = {
    "data": "Global 1 km foundation SST analysis, GHRSST L4 netCDF, in the "
            "product's original packed form.",
    "data25": "The same analysis on a 0.25 degree grid, carrying all five "
              "fields, GHRSST L4 netCDF.",
    "sst": "Foundation sea surface temperature, degrees Celsius. Converted "
           "from the granule's packed integers so the pixel value is the "
           "temperature.",
    "anom": "Departure from the seasonal climatology, in degrees Celsius. A "
            "difference, so the number is the same in Celsius or Kelvin.",
    "err": "Estimated uncertainty of the analysis, in degrees Celsius.",
    "ice": "Sea ice concentration as a fraction from 0 to 1.",
    "mask": "GHRSST bit flags: water, land, lake and ice. Categorical, so it "
            "is left in its native integer type and not converted.",
}

ASSET_TITLES = {
    "data": "MUR L4 SST granule (1 km)",
    "data25": "MUR25 L4 SST granule (0.25 deg)",
    # The units are in the titles because a browse layer is read at a glance,
    # and "Analysed SST" alone leaves a viewer guessing whether 15 means
    # celsius, kelvin or a packed count. These files hold celsius.
    "sst": "Analysed SST (degC)",
    "anom": "SST anomaly (degC)",
    "err": "Analysis error (degC)",
    "ice": "Sea ice fraction",
    "mask": "Land/sea/ice mask (flags)",
}


def _scalar(text):
    """Cast a --property value the way a reader would expect.

    `mur:doy=279` must be a number: STAC properties are queryable, and a
    string "279" will not answer a numeric range filter. `key:=<json>` forces
    an exact type for the cases this heuristic gets wrong.
    """
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    return text


def _media_type(relpath):
    ext = posixpath.splitext(relpath)[1].lower()
    if ext == ".tif" or ext == ".tiff":
        return COG_TYPE
    if ext == ".nc":
        return NETCDF_TYPE
    return None


def _roles(key, relpath):
    ext = posixpath.splitext(relpath)[1].lower()
    if ext in (".tif", ".tiff"):
        # "data" because these are single-band quantitative rasters, not an
        # RGB composite; "visual" because they are nonetheless the browse
        # product, and that is the role clients look for when choosing
        # something to draw.
        return ["data", "visual"]
    return ["data"]


# MAAP's tiler, which serves anything in the DPS STAC.
TITILER = "https://titiler-dps-stac.maap-project.org"
TMS = "WebMercatorQuad"


def viewer_links(collection, item_id, asset_key, render):
    """Map and image URLs for one asset of one published item.

    `collection` is the id MAAP assigns at ingest, which this container has no
    way to know: it is <username>__<registered algorithm>__<version>, the
    registered name carries a suffix MAAP allocates, and none of that is
    visible from inside a job. The orchestrator knows it and passes it in; if
    it did not, these are left out rather than guessed, because a link that
    looks right and 404s is worse than no link.
    """
    from urllib.parse import quote, urlencode
    stem = f"{TITILER}/collections/{quote(collection)}/items/{quote(item_id)}"
    query = urlencode({"assets": asset_key, **render})
    return {
        "map": f"{stem}/{TMS}/map.html?{query}",
        "image": f"{stem}/preview.png?{urlencode({'assets': asset_key, 'max_size': 1024, **render})}",
    }


def preview_links(published_collection, item_id, asset_keys):
    """Viewer entries for the item's `links` array.

    LINKS, NOT ASSETS, and the distinction is load-bearing. titiler computes
    an item's zoom bounds across all of its ASSETS and fails on the first one
    it cannot open -- verified against the live service, where an item
    holding a GeoTIFF beside a Zarr would not tile for any value of
    `assets=`, including the GeoTIFF's own key. Adding a PNG and an HTML page
    as assets would reintroduce exactly that, breaking the tiling this is
    meant to make easier.

    These DO survive ingest, and STAC Browser renders both: rel=alternate
    appears under "Additional Resources" and rel=preview becomes the item's
    thumbnail. Confirmed on a live 2.0.19 item.

    That was briefly believed to be false. The 2.0.18 items came back from
    the API with exactly collection/parent/root/self, which looked like the
    ingest regenerating `links` -- stac-fastapi-pgstac does exactly that for
    some fields, so the theory fit. It was wrong: those items had no viewer
    links because that run never passed --stac-collection, so the guard below
    returned [] and nothing was ever written. An absent input and a stripped
    field are indistinguishable from the far end, which is why the check that
    settles it is the one on the emitted file, not the served one.

    One pair for the field a reader wants first, rather than a pair per
    field: MUR25 carries five, and ten more entries would bury the data.
    Every field's own URLs are on its asset as mur:map_url / mur:image_url.
    """
    primary = next((k for k in ("sst", "anom", "ice", "err", "mask")
                    if k in asset_keys and k in RENDER), None)
    if not (published_collection and primary):
        return []
    urls = viewer_links(published_collection, item_id, primary,
                        RENDER[primary])
    label = ASSET_TITLES.get(primary, primary)
    return [
        {"rel": "preview", "href": urls["image"], "type": "image/png",
         "title": f"Preview image ({label})"},
        {"rel": "alternate", "href": urls["map"], "type": "text/html",
         "title": f"Interactive map ({label})"},
    ]


def render_block(key):
    """One Render-extension entry for `key`, in the spec's own types.

    RENDER holds titiler's query-string spellings, because that is what the
    viewer URLs need: `rescale=-2,35`. The Render extension is JSON and types
    the same field as an array of min/max pairs -- [[-2, 35]] -- so a string
    there fails validation and is ignored by anything that reads the block
    for its defaults, which is the entire point of writing it. Converted
    here, once, rather than keeping two spellings of every range in RENDER.
    """
    params = dict(RENDER[key])
    lo, _, hi = params.pop("rescale", "").partition(",")
    block = {"assets": [key], "title": ASSET_TITLES.get(key, key)}
    if lo and hi:
        block["rescale"] = [[float(lo), float(hi)]]
    block.update(params)
    return block


def item_render_properties(item_id, assets, published_collection):
    """Render hints and viewer URLs, in the places the ingest preserves.

    `renders` is the STAC Render extension, and is the only thing here a
    generic client understands. Each entry names the assets to draw and the
    stretch to draw them with, so a viewer opens on the right colour scale
    instead of its own default -- and titiler's default for a Float32 band is
    the dtype range, -3.4e38..3.4e38, which maps the whole ocean onto one
    colour. The Collection already carried a renders block and it came
    through ingest intact, so this is a field the ingest preserves.

    mur:map_url / mur:image_url repeat the primary field's viewer URLs at the
    top level, where a reader can find them without opening an asset. They
    duplicate the links preview_links writes; both are cheap, and they fail
    in different ways -- a client that ignores one may honour the other.
    Omitted entirely when the published collection id is unknown, for the
    same reason preview_links omits them: a URL that looks right and 404s is
    worse than no URL.
    """
    out = {}

    renders = {key: render_block(key) for key in assets if key in RENDER}
    if renders:
        out["renders"] = renders

    primary = next((k for k in ("sst", "anom", "ice", "err", "mask")
                    if k in assets and k in RENDER), None)
    if published_collection and primary:
        urls = viewer_links(published_collection, item_id, primary,
                            RENDER[primary])
        out["mur:map_url"] = urls["map"]
        out["mur:image_url"] = urls["image"]

    return out


def build_item(item_id, collection, dt, assets, properties=None,
               depth=2, published_collection=""):
    """One STAC Item.

    `assets` maps asset key -> path relative to the output directory.
    `depth` is how many directory levels separate the item file from the
    output root, so asset hrefs can be made relative to the item itself --
    which is what the ingestion service resolves against.
    """
    props = {"datetime": dt}
    props.update(properties or {})

    up = "/".join([".."] * depth)
    out = {}
    for key, relpath in assets.items():
        asset = {"href": posixpath.normpath(posixpath.join(up, relpath))}
        mtype = _media_type(relpath)
        if mtype:
            asset["type"] = mtype
        asset["roles"] = _roles(key, relpath)
        if key in ASSET_TITLES:
            asset["title"] = ASSET_TITLES[key]
        if key in ASSET_DESCRIPTIONS:
            asset["description"] = ASSET_DESCRIPTIONS[key]
        if key in RENDER:
            # Carried on the asset so a reader does not have to know MUR's
            # units to draw the layer correctly. mur_maap/stac.py reads this
            # back rather than re-deriving it.
            asset["mur:render"] = dict(RENDER[key])
        if key in UNITS:
            asset["mur:units"] = UNITS[key]
        if published_collection and key in RENDER:
            links = viewer_links(published_collection, item_id, key,
                                 RENDER[key])
            asset["mur:map_url"] = links["map"]
            asset["mur:image_url"] = links["image"]
        out[key] = asset

    render_props = item_render_properties(item_id, out, published_collection)

    extensions = [
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
    ]
    # The Render extension is how a client is told which bands to draw and
    # with what stretch. Without it every viewer falls back to its own
    # defaults, and titiler's default for a Float32 band is the dtype range
    # -- -3.4e38..3.4e38 -- which maps the whole ocean onto one colour.
    #
    # Declared only when there is something to declare: the schema makes
    # `renders` a REQUIRED property of any item claiming the extension, so an
    # unconditional entry makes every granule item invalid. The granule items
    # are exactly the ones with nothing to render -- a netCDF is not a layer
    # a tile server can draw -- so this is the common case, not the edge.
    if render_props.get("renders"):
        extensions.append(
            "https://stac-extensions.github.io/render/v2.0.0/schema.json")

    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        # EPSG:4326 for both products and every field. Asserted rather than
        # measured: the netCDF path has no raster library, and GHRSST L4
        # carries no grid_mapping, which is the whole reason the COG step
        # passes -a_srs EPSG:4326.
        "stac_extensions": extensions,
        "id": item_id,
        "collection": collection,
        "geometry": GLOBAL_GEOMETRY,
        "bbox": list(GLOBAL_BBOX),
        "properties": dict(props, **render_props, **{"proj:epsg": 4326}),
        "assets": out,
        "links": [
            {"rel": "root", "href": "../../catalog.json",
             "type": "application/json"},
            {"rel": "collection", "href": "../collection.json",
             "type": "application/json"},
            {"rel": "parent", "href": "../collection.json",
             "type": "application/json"},
            {"rel": "self", "href": "%s.json" % item_id,
             "type": "application/geo+json"},
        ] + preview_links(published_collection, item_id, out),
    }


def versioned_title(title, published_collection):
    """`title`, with the algorithm version appended when it is knowable.

    Every version of an algorithm forks a new collection, and they all take
    the same title from COLLECTIONS -- so the catalogue lists four entries
    reading "MUR L4 SST Browse Imagery" with nothing to tell them apart, and
    the only way to find the current one is to open each and read the items.
    That has sent a reader to a stale collection more than once.

    The version is not otherwise visible from inside a job: MAAP stamps
    processing:version on ingest, the container never sees it. But the
    published collection id the orchestrator passes in ends in it --
    jleach_jpl__mur-cog_1756__2.0.19 -- so where that is known, so is the
    version. Where it is not, the title is left exactly as it was rather
    than guessed at.
    """
    if not published_collection or "__" not in published_collection:
        return title
    version = published_collection.rsplit("__", 1)[-1]
    # Only something that actually looks like a version. A collection id in
    # an unexpected shape should leave the title alone, not append a
    # fragment of itself to it.
    if not re.match(r"^\d+(\.\d+)+$", version):
        return title
    return "%s v%s" % (title, version)


def build_collection(collection_id, title, description, items,
                     published_collection=""):
    """The Collection every Item in this catalog belongs to.

    Exactly one, deliberately: the ingestion service requires a single
    distinct source collection id among the items it is given, and a single
    matching Collection in the catalog hierarchy.

    Its id is rewritten on ingest to
    <username>__<algorithm_name>__<algorithm_version> -- and the algorithm
    name there is the REGISTERED one, which MAAP suffixes
    (mur-mrva_1756, not mur-mrva). So the id declared here never survives and
    cannot be predicted from this file. The title is what a reader sees, and
    it does survive; see COLLECTIONS above for what else does.
    """
    items = sorted(items, key=lambda i: (i["properties"]["datetime"], i["id"]))
    datetimes = sorted(i["properties"]["datetime"] for i in items)
    meta = COLLECTIONS.get(collection_id, {})

    out = {
        "type": "Collection",
        "stac_version": STAC_VERSION,
        "id": collection_id,
        "title": versioned_title(meta.get("title") or title,
                                 published_collection),
        "description": meta.get("description") or description,
        "license": "proprietary",
        "extent": {
            "spatial": {"bbox": [list(GLOBAL_BBOX)]},
            "temporal": {"interval": [[datetimes[0], datetimes[-1]]]},
        },
        "links": [
            {"rel": "root", "href": "../catalog.json",
             "type": "application/json"},
            {"rel": "parent", "href": "../catalog.json",
             "type": "application/json"},
            {"rel": "self", "href": "collection.json",
             "type": "application/json"},
        ] + [
            {"rel": "item", "href": "%s/%s.json" % (i["id"], i["id"]),
             "type": "application/geo+json"}
            for i in items
        ],
    }

    for field in ("keywords", "providers"):
        if meta.get(field):
            out[field] = meta[field]

    # NO item_assets, deliberately.
    #
    # It is the natural place to document each asset key once, and MAAP's
    # STAC API merges it into EVERY item on read -- including the keys an
    # item does not have, with no href. titiler then walks the item's assets
    # and raises
    #
    #     {"detail": "'href'"}
    #
    # on the first one it finds. That broke the 1 km product specifically:
    # it produces sst and anom, so the err, ice and mask definitions were
    # merged in empty and every tile request 500'd, while MUR25 -- which
    # produces all five -- tiled fine. Verified against the live API.
    #
    # The titles, descriptions and units live on each item's own assets,
    # which is what a browser displays anyway. A collection-level copy is a
    # nicety; tiling the flagship product is not.

    # Only when something here is actually renderable. The first ingested
    # collection came back with "renders": {} because the granules carry no
    # renderable field -- correct, and pure noise in the catalogue.
    renders = {
        key: render_block(key) for key in RENDER
        if any(key in i["assets"] for i in items)
    }
    if renders:
        out["renders"] = renders

    return out


def build_catalog(collection_id):
    return {
        "type": "Catalog",
        "stac_version": STAC_VERSION,
        "id": "DPS",
        "description": "DPS output STAC items",
        "links": [
            {"rel": "root", "href": "catalog.json",
             "type": "application/json"},
            {"rel": "self", "href": "catalog.json",
             "type": "application/json"},
            {"rel": "child", "href": "%s/collection.json" % collection_id,
             "type": "application/json"},
        ],
    }


def existing_items(output_dir, collection_id, excluding=()):
    """Items already written into this collection directory.

    Rewriting collection.json from only the item in hand would silently drop
    the `item` links of anything written earlier -- and an item the collection
    does not link to is an item the ingestion service never walks to. In
    normal operation each job writes one item into its own stage-out
    directory and this finds nothing, but a caller that describes two
    granules in one directory (both L4 resolutions, say) must not lose the
    first one. Found by doing exactly that in a test.
    """
    cdir = os.path.join(output_dir, collection_id)
    found = []
    if not os.path.isdir(cdir):
        return found
    for name in sorted(os.listdir(cdir)):
        if name in excluding:
            continue
        path = os.path.join(cdir, name, name + ".json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as fh:
                item = json.load(fh)
        except (ValueError, OSError):
            # A damaged sibling is not worth failing this item over, but it
            # must not be linked as though it were readable.
            print("write_stac: ignoring unreadable item %s" % path,
                  file=sys.stderr)
            continue
        if item.get("id") == name and "properties" in item:
            found.append(item)
    return found


def write_catalog(output_dir, collection_id, title, description, items,
                  published_collection=""):
    """Write catalog.json, the collection, and every item. Returns paths."""
    written = []

    def dump(path, obj):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.write("\n")
        written.append(path)

    cdir = os.path.join(output_dir, collection_id)
    for item in items:
        dump(os.path.join(cdir, item["id"], item["id"] + ".json"), item)
    linked = list(items) + existing_items(
        output_dir, collection_id, excluding={i["id"] for i in items})
    dump(os.path.join(cdir, "collection.json"),
         build_collection(collection_id, title, description, linked,
                          published_collection))
    # Last, so a crash midway leaves no catalog.json for the ingest service
    # to find and reject. Absent metadata is a missing layer; half-written
    # metadata is a published lie.
    dump(os.path.join(output_dir, "catalog.json"),
         build_catalog(collection_id))
    return written


def _iso(text):
    """Normalize a datetime to the Z-suffixed form STAC requires."""
    raw = text.strip()
    if raw.endswith("Z"):
        probe = raw[:-1] + "+00:00"
    else:
        probe = raw
    try:
        dt = datetime.datetime.fromisoformat(probe)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "not an ISO-8601 datetime: %r" % text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output-dir", required=True)
    p.add_argument("--collection", required=True)
    p.add_argument("--collection-title", default="")
    p.add_argument("--collection-description", default="")
    p.add_argument("--item-id", required=True)
    p.add_argument("--datetime", required=True, type=_iso,
                   dest="dt", metavar="ISO8601")
    p.add_argument("--asset", action="append", default=[], metavar="KEY=PATH",
                   help="path is relative to --output-dir; repeatable")
    p.add_argument("--stac-collection", default="", metavar="ID",
                   help="The collection id MAAP will assign "
                        "(<user>__<algorithm>__<version>). When given, each "
                        "renderable asset gains map and image links. The "
                        "container cannot work this out for itself -- the id "
                        "is assigned at ingest -- so the caller supplies it "
                        "or the links are omitted.")
    p.add_argument("--property", action="append", default=[], dest="properties",
                   metavar="KEY=VALUE",
                   help="KEY=VALUE (scalars cast), or KEY:=<json> for an "
                        "exact type; repeatable")
    args = p.parse_args(argv)

    assets = {}
    for spec in args.asset:
        if "=" not in spec:
            p.error("--asset needs KEY=PATH, got %r" % spec)
        key, relpath = spec.split("=", 1)
        relpath = relpath.strip().lstrip("./")
        if not relpath:
            continue
        # A missing file is a caller bug, and publishing an item that points
        # at nothing is worse than publishing no item: the layer appears in
        # the catalog and fails only when someone tries to draw it.
        full = os.path.join(args.output_dir, relpath)
        if not os.path.exists(full):
            print("write_stac: no such output file: %s" % full,
                  file=sys.stderr)
            return 2
        assets[key.strip()] = relpath

    if not assets:
        print("write_stac: no assets; refusing to write an empty item",
              file=sys.stderr)
        return 2

    properties = {}
    for spec in args.properties:
        if ":=" in spec:
            key, raw = spec.split(":=", 1)
            properties[key.strip()] = json.loads(raw)
        elif "=" in spec:
            key, raw = spec.split("=", 1)
            properties[key.strip()] = _scalar(raw.strip())
        else:
            p.error("--property needs KEY=VALUE, got %r" % spec)

    if args.collection not in COLLECTIONS and not args.collection_title:
        print("write_stac: %r has no entry in COLLECTIONS and no "
              "--collection-title, so its catalogue label would be its id. "
              "Add it to the table in this file." % args.collection,
              file=sys.stderr)

    item = build_item(args.item_id, args.collection, args.dt, assets,
                      properties,
                      published_collection=args.stac_collection)
    written = write_catalog(
        args.output_dir, args.collection,
        args.collection_title or args.collection,
        args.collection_description or args.collection_title or args.collection,
        [item], published_collection=args.stac_collection)

    print("STAC: %s with %d asset(s) -> catalog.json" % (
        args.item_id, len(assets)))
    for key, asset in sorted(item["assets"].items()):
        print("  %-7s %s" % (key, asset["href"]))
    print("  %d metadata file(s) written" % len(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
