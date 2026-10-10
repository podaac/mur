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
# rescale is the load-bearing one: titiler stretches each request to the data
# range it happens to see, so a field drawn without an explicit range looks
# plausible and is not comparable between days or between tiles. These are the
# GHRSST valid ranges in the granule's own units -- Kelvin for sst, Kelvin for
# the anomaly, fraction for ice, flag values for mask.
#
# This table is duplicated in mur_maap/stac.py, which builds viewer URLs on
# the client side. tests/test_write_stac.py asserts the two agree; a parity
# test is preferred here over an import because this file has to run inside a
# container that cannot see the mur_maap package.
RENDER = {
    # unscale is the load-bearing one, and its absence is what made every
    # layer unreadable.
    #
    # GHRSST packs each field as a scaled integer -- analysed_sst is int16
    # with scale_factor 0.001 and add_offset 298.15 -- and gdal_translate
    # writes the RAW integers, carrying scale/offset across as band metadata
    # rather than applying them. So the file holds -26800..9207 while these
    # rescale values are in kelvin. Every pixel below 271.15 clamped to the
    # bottom of the ramp and the few raw DN above 310 clamped to the top,
    # drawing the globe as two bright bands on a dark field. `unscale=true`
    # makes titiler apply the band's own scale/offset first, which turns
    # -26800..9207 into 271.35..307.36 K.
    #
    # The alternative -- gdal_translate -unscale -ot Float32 -- bakes the
    # conversion into the file and quadruples the 1 km product to ~4.8 GiB
    # per field. Not worth it to avoid one query parameter.
    #
    # rescale itself matters nearly as much: without an explicit range titiler
    # stretches each request to whatever it happens to see, so a field is
    # drawn on a different colour scale every day and nothing on screen says
    # so. The ranges below are fixed physical ones in the granule's own units.
    "sst":  {"rescale": "271.15,310.15", "colormap_name": "thermal",
             "unscale": "true"},
    "anom": {"rescale": "-5,5", "colormap_name": "coolwarm",
             "unscale": "true"},
    # 0,1 rather than 0,2: measured against a real granule the analysis error
    # spanned 0.800..0.810 K, so a 0..2 ramp put the entire field in one
    # colour. Still a fixed range, so days stay comparable.
    "err":  {"rescale": "0,1", "colormap_name": "magma", "unscale": "true"},
    "ice":  {"rescale": "0,1", "colormap_name": "ice", "unscale": "true"},
    # Categorical: GHRSST packs water/land/lake/ice as bit flags, and a
    # continuous ramp over them is approximate by nature. Observed 1..9.
    "mask": {"rescale": "1,16", "colormap_name": "tab10", "unscale": "true"},
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
#   here -- keywords, providers and item_assets.
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
        "item_assets": {
            "data": {"type": NETCDF_TYPE, "roles": ["data"],
                     "title": "MUR L4 SST granule (1 km)",
                     "description": "Global 1 km foundation SST analysis, "
                                    "GHRSST L4 netCDF."},
            "data25": {"type": NETCDF_TYPE, "roles": ["data"],
                       "title": "MUR25 L4 SST granule (0.25 deg)",
                       "description": "The same analysis on a 0.25 degree "
                                      "grid, carrying all five fields."},
        },
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
        "item_assets": {
            key: {"type": COG_TYPE, "roles": ["data", "visual"],
                  "title": title}
            for key, title in (
                ("sst", "Analysed SST"),
                ("anom", "SST anomaly"),
                ("err", "Analysis error"),
                ("ice", "Sea ice fraction"),
                ("mask", "Land/sea/ice mask"),
            )
        },
    },
}


ASSET_TITLES = {
    "data": "MUR L4 SST granule (1 km)",
    "data25": "MUR25 L4 SST granule (0.25 deg)",
    "sst": "Analysed SST",
    "anom": "SST anomaly",
    "err": "Analysis error",
    "ice": "Sea ice fraction",
    "mask": "Land/sea/ice mask",
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


def build_item(item_id, collection, dt, assets, properties=None,
               depth=2):
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
        if key in RENDER:
            # Carried on the asset so a reader does not have to know MUR's
            # units to draw the layer correctly. mur_maap/stac.py reads this
            # back rather than re-deriving it.
            asset["mur:render"] = dict(RENDER[key])
        out[key] = asset

    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        # EPSG:4326 for both products and every field. Asserted rather than
        # measured: the netCDF path has no raster library, and GHRSST L4
        # carries no grid_mapping, which is the whole reason the COG step
        # passes -a_srs EPSG:4326.
        "stac_extensions": [
            "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
        ],
        "id": item_id,
        "collection": collection,
        "geometry": GLOBAL_GEOMETRY,
        "bbox": list(GLOBAL_BBOX),
        "properties": dict(props, **{"proj:epsg": 4326}),
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
        ],
    }


def build_collection(collection_id, title, description, items):
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
        "title": meta.get("title") or title,
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

    # item_assets documents each asset key once, at the collection level, so a
    # browser can label a layer without opening an item. STAC 1.1 has it in
    # core; under 1.0 it is an extension, which has to be declared or
    # validation fails. The ingest service rewrites to 1.1 and keeps the
    # field either way.
    if meta.get("item_assets"):
        out["item_assets"] = meta["item_assets"]
        out["stac_extensions"] = [
            "https://stac-extensions.github.io/item-assets/v1.0.0/schema.json",
        ]

    # Only when something here is actually renderable. The first ingested
    # collection came back with "renders": {} because the granules carry no
    # renderable field -- correct, and pure noise in the catalogue.
    renders = {
        key: dict(params, assets=[key], title=ASSET_TITLES.get(key, key))
        for key, params in RENDER.items()
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


def write_catalog(output_dir, collection_id, title, description, items):
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
         build_collection(collection_id, title, description, linked))
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
                      properties)
    written = write_catalog(
        args.output_dir, args.collection,
        args.collection_title or args.collection,
        args.collection_description or args.collection_title or args.collection,
        [item])

    print("STAC: %s with %d asset(s) -> catalog.json" % (
        args.item_id, len(assets)))
    for key, asset in sorted(item["assets"].items()):
        print("  %-7s %s" % (key, asset["href"]))
    print("  %d metadata file(s) written" % len(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
